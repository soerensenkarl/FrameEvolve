"""The workbench: a local web page to look at houses, grammars and frames, and to work on them.

    uv run python -m frameevolve serve        then open http://localhost:8765

Standard library only. The page talks to a small JSON API; every build is computed fresh on request.
"""
from __future__ import annotations

import ast
import json
import random
import re
import tempfile
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from frameevolve import houses, jobs as jobs_mod, surface
from frameevolve.builder import build
from frameevolve.geometry import EPS
from frameevolve.model import Frame, House
from frameevolve.verifier import CHECKS, verify

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
HOUSES = ROOT / "data" / "houses"
GRAMMARS = ROOT / "grammars"
RUNS = ROOT / "runs"
NAME = re.compile(r"^[A-Za-z0-9_\-]+$")
FILE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9]+$")
JOBS = jobs_mod.Jobs()
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".png": "image/png"}


def jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # a line being written right now
    return out


def run_dir(name: str) -> Path | None:
    p = RUNS / name
    return p if NAME.match(name) and (p / "config.json").is_file() else None


def total(scores: dict, houses: list[str]) -> list:
    hs = [h for h in houses if h in scores]
    return [sum(scores[h][0] for h in hs), sum(scores[h][1] for h in hs), round(sum(scores[h][2] for h in hs), 2)]


def run_summary(p: Path) -> dict:
    config = json.loads((p / "config.json").read_text())
    return {"name": p.name, "model": config.get("model"), "candidates": len(jsonl(p / "candidates.jsonl")),
            "iterations": len(jsonl(p / "iterations.jsonl"))}


def run_payload(p: Path) -> dict:
    """A run as the page shows it: config, candidates with totals, iterations, and the Pareto set."""
    from frameevolve.search import Run, pareto
    config = json.loads((p / "config.json").read_text())
    house_ids = []
    for h in config.get("train", []):
        hp = Path(h) if Path(h).is_absolute() else ROOT / h
        try:
            house_ids.append(House.load(hp).id)
        except Exception:
            house_ids.append(Path(h).stem)
    cands = jsonl(p / "candidates.jsonl")
    for c in cands:
        c["total"] = total(c["scores"], house_ids)
    run = Run(p)
    return {"name": p.name, "config": config, "houses": house_ids, "candidates": cands,
            "iterations": jsonl(p / "iterations.jsonl"), "pareto": pareto(run.cands, house_ids) if run.cands else {}}


def transcript_summary(path: Path) -> dict:
    """Each tool call the proposer made (name and a short preview of its input), and its final note."""
    try:
        msgs = json.loads(path.read_text())
    except Exception as e:
        return {"error": f"could not read transcript: {e}", "calls": [], "note": ""}
    calls, note, usage = [], "", {"input_tokens": 0, "output_tokens": 0}
    for i, m in enumerate(msgs if isinstance(msgs, list) else []):
        texts = []
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                inp = b.get("input") or {}
                preview = ", ".join(f"{k}={json.dumps(v)[:80]}" for k, v in inp.items()) if isinstance(inp, dict) else str(inp)
                calls.append({"turn": i + 1, "name": b.get("name", "?"), "input": preview[:220]})
            elif b.get("type") == "text" and b.get("text", "").strip():
                texts.append(b["text"].strip())
        if texts:
            note = " ".join(texts)
        u = m.get("usage") or {}
        for k in usage:
            usage[k] += u.get(k) or 0
    return {"calls": calls, "note": note[:3000], "turns": len(msgs) if isinstance(msgs, list) else 0, "usage": usage}


def proposal_payload(run: Path, n: int) -> dict | None:
    d = run / "proposals" / f"{n:04d}"
    if not d.is_dir():
        return None
    files = sorted(f.name for f in d.iterdir() if f.is_file())
    read = lambda name: (d / name).read_text() if (d / name).is_file() else None  # noqa: E731
    return {"iteration": n, "files": files, "images": [f for f in files if f.endswith(".png")],
            "prompt": read("prompt.md"), "proposed": read("proposed.py"),
            "transcript": transcript_summary(d / "transcript.json") if (d / "transcript.json").is_file() else None}


def grammar_rules(source: str) -> list[dict]:
    """The rules in a grammar's source, read without running it: name, priority, docstring, lines."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [{"error": f"syntax error line {e.lineno}: {e.msg}"}]
    out = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "rule" and d.args:
                prio = d.args[0].value if isinstance(d.args[0], ast.Constant) else None
                kw = {k.arg: k.value for k in d.keywords}
                match = kw.get("match", d.args[1] if len(d.args) > 1 else None)
                when = kw.get("when", d.args[2] if len(d.args) > 2 else None)
                out.append({"name": node.name, "priority": prio, "doc": ast.get_docstring(node) or "",
                            "match": match.value if isinstance(match, ast.Constant) else None,
                            "when": ast.get_source_segment(source, when.body if isinstance(when, ast.Lambda) else when)
                            if when is not None else None,
                            "line": node.lineno, "end": node.end_lineno})
    return sorted(out, key=lambda r: (r["priority"] if r["priority"] is not None else 1e9, r["name"]))


def frame_payload(house: House, frame: Frame, source: str) -> dict:
    report = verify(house, frame)
    g = report.graph
    gone = {m.id for m in frame.removed}
    members = []
    for m in frame.members + frame.removed:
        w = house.wall(m.surface) if m.surface else None
        lb = w.local_box(m.box) if w else None
        members.append({
            "id": m.id, "rule": m.rule, "role": m.role, "section": m.section, "surface": m.surface,
            "length": round(m.length, 1), "lo": m.box.lo, "hi": m.box.hi, "removed": m.id in gone,
            "local": [lb.lo, lb.hi] if lb else None,
            "bears": list(g.bears.get(m.id, {})), "carries": list(g.carries.get(m.id, {})),
            "side": list(g.side.get(m.id, {})),
        })
    walls = []
    by_id = {w.id: w for w in house.walls}
    for w in house.walls:
        face = []
        for m in frame.members:
            if m.surface == w.id:
                continue
            b = w.local_box(m.box)
            if abs(b.lo[2]) <= EPS and b.hi[0] > EPS and b.lo[0] < w.length - EPS:
                face.append({"id": m.id, "lo": b.lo, "hi": b.hi})
        gaps = []
        for side in ("outer", "inner"):
            # drawn just off the face: outside the outer face, inside the inner one
            off = -0.2 if side == "outer" else (surface.depth(w, frame.members) or 0.0) + 0.2
            for gp in surface.gaps(w, frame.members, face=side, walls=by_id):
                corners = [w.world(u, v, off) for u, v in ((gp.u0, gp.v0), (gp.u1, gp.v0), (gp.u1, gp.v1), (gp.u0, gp.v1))]
                gaps.append({**asdict(gp), "face": side, "world": corners})
        walls.append({"id": w.id, "length": w.length, "height": w.height, "base": w.base, "start": w.start,
                      "end": w.end, "role": w.role, "start_meets": w.start_meets, "end_meets": w.end_meets,
                      "tees": [asdict(t) for t in w.tees],
                      "openings": [asdict(o) for o in w.openings], "neighbours": face, "gaps": gaps})
    m = report.metrics
    return {
        "house": house.id, "walls": walls, "members": members, "rules": grammar_rules(source),
        "steps": frame.steps, "errors": frame.errors,
        "faults": [asdict(f) for f in report.faults], "checks": CHECKS, "report": report.text(),
        "stats": {"members": m["members"], "hard": report.hard, "soft": report.soft, "cost": m["cost"],
                  "bought_ft": m["bought_ft"], "waste_pct": m["waste_pct"], "steps": len(frame.steps)},
    }


def build_source(name: str, source: str, house: House) -> Frame:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"{name}.py"
        p.write_text(source)
        return build(p, house)


def rule_demo(name: str, source: str, rule: str, firing: int | None = None) -> dict:
    """What one rule does, shown on the toy house: the wall just before one of its firings, and what it placed
    and removed there. `firing` picks which firing (0 = first); by default the first one on w0."""
    house = houses.toy()
    frame = build_source(name, source, house)
    doc = next((r.get("doc", "") for r in grammar_rules(source) if r.get("name") == rule), "")
    steps = frame.steps
    fired = [i for i, s in enumerate(steps) if s["rule"] == rule]
    out = {"rule": rule, "doc": doc, "house": house.id, "fired": len(fired), "errors": frame.errors[:3],
           "span": [max(w.length for w in house.walls), max(w.height for w in house.walls)]}  # one scale for every wall
    if not fired:
        out["message"] = "This rule did nothing on the toy house."
        return out
    if firing is None:
        firing = next((k for k, i in enumerate(fired) if steps[i]["wall"] == "w0"), 0)
    firing = max(0, min(len(fired) - 1, firing))
    i = fired[firing]
    step = steps[i]
    w = house.wall(step["wall"])
    placed_at, removed_at = {}, {}
    for k, s in enumerate(steps):
        for mid in s["placed"]:
            placed_at[mid] = k
        for mid in s["removed"]:
            removed_at[mid] = k
    allm = {m.id: m for m in frame.members + frame.removed}

    def box(m) -> dict:
        b = w.local_box(m.box)
        return {"id": m.id, "rule": m.rule, "role": m.role, "u0": b.lo[0], "v0": b.lo[1], "u1": b.hi[0], "v1": b.hi[1],
                "w0": b.lo[2]}

    before = [m for m in allm.values() if placed_at.get(m.id, -1) < i and removed_at.get(m.id, 10**9) >= i]
    own = [box(m) for m in before if m.surface == w.id]
    near = []
    for m in before:
        if m.surface == w.id:
            continue
        b = box(m)
        if abs(b["w0"]) <= EPS and b["u1"] > EPS and b["u0"] < w.length - EPS:
            near.append(b)
    out.update({
        "firing": firing, "pass": step["pass"], "match": step.get("match"), "target": step.get("target"),
        "wall": {"id": w.id, "length": w.length, "height": w.height, "openings": [asdict(o) for o in w.openings],
                 "tees": [asdict(t) for t in w.tees]},
        "firings": [{"wall": steps[k]["wall"], "pass": steps[k]["pass"]} for k in fired],
        "before": own, "neighbours": near,
        "placed": [box(allm[mid]) for mid in step["placed"] if mid in allm],
        "removed": [box(allm[mid]) for mid in step["removed"] if mid in allm],
    })
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def send(self, code: int, body, ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/":
                return self.send(200, (WEB / "index.html").read_bytes(), "text/html")
            if path.startswith("/web/"):
                f = (WEB / path[5:]).resolve()
                if WEB in f.parents and f.is_file():
                    return self.send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
                return self.send(404, {"error": "not found"})
            if path == "/api/houses":
                out = []
                for p in sorted(HOUSES.glob("*.json")):
                    h = House.load(p)
                    out.append({"id": h.id, "walls": len(h.walls),
                                "openings": sum(len(w.openings) for w in h.walls),
                                "size": [round(max(w.end[0] for w in h.walls)), round(max(w.end[1] for w in h.walls))]})
                return self.send(200, out)
            if path == "/api/grammars":
                return self.send(200, [p.stem for p in sorted(GRAMMARS.glob("*.py"))])
            if path.startswith("/api/grammar/"):
                name = path.split("/")[-1]
                if not NAME.match(name) or not (GRAMMARS / f"{name}.py").is_file():
                    return self.send(404, {"error": "no such grammar"})
                src = (GRAMMARS / f"{name}.py").read_text()
                return self.send(200, {"name": name, "source": src, "rules": grammar_rules(src)})
            if path == "/api/jobs":
                return self.send(200, {"jobs": JOBS.list(), "credentials": jobs_mod.credentials()})
            if path.startswith("/api/job/"):
                try:
                    return self.send(200, JOBS.get(path.split("/")[3]))
                except ValueError as e:
                    return self.send(404, {"error": str(e)})
            if path == "/api/runs":
                runs =[run_summary(p.parent) for p in sorted(RUNS.glob("*/config.json"), key=lambda q: -q.stat().st_mtime)
                        if NAME.match(p.parent.name)] if RUNS.is_dir() else []
                return self.send(200, runs)
            if path.startswith("/api/run/"):
                parts = path[len("/api/run/"):].strip("/").split("/")
                run = run_dir(parts[0])
                if run is None:
                    return self.send(404, {"error": "no such run"})
                if len(parts) == 1:
                    return self.send(200, run_payload(run))
                if len(parts) == 3 and parts[1] == "grammar" and NAME.match(parts[2]):
                    f = run / "grammars" / f"{parts[2]}.py"
                    if not f.is_file():
                        return self.send(404, {"error": "no such candidate"})
                    src = f.read_text()
                    return self.send(200, {"id": parts[2], "source": src, "rules": grammar_rules(src)})
                if len(parts) in (3, 4) and parts[1] == "proposal" and parts[2].isdigit():
                    n = int(parts[2])
                    if len(parts) == 3:
                        out = proposal_payload(run, n)
                        return self.send(200, out) if out else self.send(404, {"error": "no proposal folder"})
                    f = run / "proposals" / f"{n:04d}" / parts[3]
                    if not FILE.match(parts[3]) or not f.is_file():
                        return self.send(404, {"error": "no such file"})
                    return self.send(200, f.read_bytes(), TYPES.get(f.suffix, "text/plain; charset=utf-8"))
                return self.send(404, {"error": "not found"})
            return self.send(404, {"error": "not found"})
        except Exception as e:
            return self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            b = self.body()
            if path == "/api/build":
                if not NAME.match(str(b.get("house", ""))):
                    return self.send(400, {"error": "bad house name"})
                house = House.load(HOUSES / f"{b['house']}.json")
                name = b["grammar"]
                if not NAME.match(name):
                    return self.send(400, {"error": "bad grammar name"})
                source = b.get("source")
                if source is None:
                    source = (GRAMMARS / f"{name}.py").read_text()
                frame = build_source(name, source, house)
                return self.send(200, frame_payload(house, frame, source))
            if path == "/api/jobs":
                try:
                    return self.send(200, JOBS.start(str(b.get("kind", "")), b.get("settings") or {}))
                except ValueError as e:
                    return self.send(400, {"error": str(e)})
            if path.startswith("/api/job/"):
                parts = path.strip("/").split("/")   # api job <id> stop|kill
                if len(parts) == 4 and parts[3] in ("stop", "kill"):
                    try:
                        return self.send(200, (JOBS.stop if parts[3] == "stop" else JOBS.kill)(parts[2]))
                    except ValueError as e:
                        return self.send(404, {"error": str(e)})
                return self.send(404, {"error": "not found"})
            if path == "/api/rule_demo":
                name = b["grammar"]
                if not NAME.match(name):
                    return self.send(400, {"error": "bad grammar name"})
                source = b.get("source")
                if source is None:
                    source = (GRAMMARS / f"{name}.py").read_text()
                firing = b.get("firing")
                return self.send(200, rule_demo(name, source, str(b["rule"]), None if firing is None else int(firing)))
            if path == "/api/houses":
                if b.get("seed") is None:
                    # a random seed whose house does not exist yet
                    taken = {p.stem for p in HOUSES.glob("*.json")}
                    free = [n for n in range(1000) if f"h{n:03d}" not in taken]
                    seed = random.choice(free) if free else random.randrange(1000, 10**6)
                else:
                    seed = int(b["seed"])
                house = houses.generate(seed)
                HOUSES.mkdir(parents=True, exist_ok=True)
                house.save(HOUSES / f"{house.id}.json")
                return self.send(200, {"id": house.id})
            return self.send(404, {"error": "not found"})
        except Exception as e:
            return self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_PUT(self):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/grammar/"):
                name = path.split("/")[-1]
                if not NAME.match(name):
                    return self.send(400, {"error": "bad grammar name"})
                (GRAMMARS / f"{name}.py").write_text(self.body()["source"])
                return self.send(200, {"saved": name})
            return self.send(404, {"error": "not found"})
        except Exception as e:
            return self.send(500, {"error": f"{type(e).__name__}: {e}"})


def serve(port: int = 8765) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"FrameEvolve workbench on http://localhost:{port}", flush=True)
    server.serve_forever()
