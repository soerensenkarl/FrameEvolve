"""The workbench: a local web page to look at houses, grammars and frames, and to work on them.

    uv run python -m frameevolve serve        then open http://localhost:8765

Standard library only. The page talks to a small JSON API; every build is computed fresh on request.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import random
import re
import tempfile
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from frameevolve import houses, jobs as jobs_mod, model, solid, surface, verifier
from frameevolve.builder import build
from frameevolve.geometry import EPS
from frameevolve.model import SECTIONS, Floor, Frame, House, Member, Roof, Wall
from frameevolve.verifier import CHECKS, verify

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
HOUSES = ROOT / "data" / "houses"
GRAMMARS = ROOT / "grammars"
RUNS = ROOT / "runs"
NAME = re.compile(r"^[A-Za-z0-9_\-]+$")
FILE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9]+$")
RUN_GRAMMAR = re.compile(r"^([A-Za-z0-9_\-]+)\.(c\d{3})$")   # "first.c003": a grammar a search kept
JOBS = jobs_mod.Jobs()
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".png": "image/png"}


def grammar_file(name: str) -> Path | None:
    """grammars/<name>.py, or for "run.cid" the grammar that run kept. None if there is no such file."""
    m = RUN_GRAMMAR.match(name)
    p = RUNS / m[1] / "grammars" / f"{m[2]}.py" if m else GRAMMARS / f"{name}.py" if NAME.match(name) else None
    return p if p and p.is_file() else None


def source_of(b: dict) -> str | None:
    """The grammar source a request means: the one it sends (unsaved edits), else the file it names, else None."""
    if b.get("source") is not None:
        return b["source"]
    f = grammar_file(str(b.get("grammar", "")))
    return f.read_text() if f else None


def grammar_names() -> list[str]:
    """The saved grammars, then every grammar each run kept, newest run first."""
    out = [p.stem for p in sorted(GRAMMARS.glob("*.py"))]
    runs = sorted(RUNS.glob("*/grammars"), key=lambda d: d.stat().st_mtime, reverse=True)
    return out + [f"{d.parent.name}.{p.stem}" for d in runs for p in sorted(d.glob("c*.py"))]


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


def live_now(run: Path) -> bool:
    """Whether a search is writing to this run: its live files say so and changed in the last ten minutes."""
    try:
        live = json.loads((run / "live.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    files = [run / "live.json", run / "proposals" / str(live.get("proposal", "-")) / "live.jsonl"]
    newest = max(f.stat().st_mtime for f in files if f.is_file())
    return live.get("stage") != "stopped" and time.time() - newest < 600


def run_summary(p: Path) -> dict:
    config = json.loads((p / "config.json").read_text())
    return {"name": p.name, "model": config.get("model"), "candidates": len(jsonl(p / "candidates.jsonl")),
            "iterations": len(jsonl(p / "iterations.jsonl")), "live": live_now(p)}


def run_payload(p: Path) -> dict:
    """A run as the page shows it: config, candidates with their totals over the validation houses (the ones the
    search judges by), iterations, the Pareto set, and each validation house's footprint as wall segments
    [x0, y0, x1, y1, interior] for a thumbnail."""
    from frameevolve.search import Run
    run = Run(p)
    house_ids, footprints = [], {}
    for h in run.val:
        hp = h if h.is_absolute() else ROOT / h
        try:
            house = House.load(hp)
        except Exception:
            house_ids.append(h.stem)
            continue
        house_ids.append(house.id)
        ground = min(w.base for w in house.walls)
        footprints[house.id] = [[*w.start, *w.end, w.role == "interior"] for w in house.walls if w.base == ground]
    cands = jsonl(p / "candidates.jsonl")
    for c, cand in zip(cands, run.cands):
        c["total"] = cand.total([h for h in house_ids if h in cand.scores])
    return {"name": p.name, "config": run.config, "houses": house_ids, "footprints": footprints, "candidates": cands,
            "iterations": jsonl(p / "iterations.jsonl"), "pareto": run.pareto() if run.cands else {}}


def jobs_now() -> list[dict]:
    """Every job; one the workbench lost track of on a restart counts as running while its process lives."""
    out = JOBS.list()
    for j in out:
        if j["status"] == "lost" and j.get("pid"):
            try:
                os.kill(j["pid"], 0)
                j["status"], j["detached"] = "running", True
            except OSError:
                pass
    return out


def live_payload(run: Path, proposal: str, after: int) -> dict:
    """What a search is doing now: live.json, the proposer's actions after the first `after` of `proposal`
    (all of them when the search has moved to another proposal), its current draft, and the running job."""
    try:
        live = json.loads((run / "live.json").read_text())
    except (OSError, json.JSONDecodeError):
        live = None   # not written yet, or written by a search older than the live view
    job = next((j for j in jobs_now() if j["kind"] == "evolve" and j["status"] == "running"
                and j["settings"].get("run") == run.name), None)
    out = {"live": live, "job": None, "active": bool(job) or live_now(run), "events": [], "count": 0, "draft": None}
    if job:
        # iterations this job has finished, from its log, to say "iteration 3 of 5"
        log = (JOBS.root / job["id"] / "log.txt").read_text(errors="replace")
        done = sum(1 for line in log.splitlines() if re.match(r"iteration \d+:", line))
        out["job"] = {"id": job["id"], "title": job["title"], "started": job["started"], "done": done,
                      "of": int(job["settings"].get("iterations", 0))}
    name = (live or {}).get("proposal")
    if name and FILE.match(name + ".x"):
        d = run / "proposals" / name
        events = jsonl(d / "live.jsonl")
        out["count"] = len(events)
        out["events"] = events[after:] if name == proposal else events
        if (d / "draft.py").is_file():
            out["draft"] = (d / "draft.py").read_text()
    return out


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


def polys(w, m: Member) -> dict:
    """A member's outlines on surface w (u, v polygons), when it is not square to it: {} for a plain box."""
    if w is None or w.square(m):
        return {}
    return {"poly": [[[round(u, 3), round(v, 3)] for u, v in poly] for poly in surface.outlines(w, m)]}


def shape(m: Member, w) -> dict:
    """How to draw a member: its world box, and where it is not a plain box, a triangle mesh (flat xyz list and
    index triples) and its outlines on its own surface."""
    out = {"lo": m.box.lo, "hi": m.box.hi, **polys(w, m)}
    if not m.plain:
        verts, idx = solid.triangles(m.pieces)
        out["mesh"] = {"verts": [round(c, 3) for p in verts for c in p], "idx": idx}
    return out


def surfaces_payload(house: House, members: list, gaps_too: bool = True) -> dict:
    """Every surface for drawing: its outline and openings, how deep the framing on it is and, unless told not
    to, where its sheathing has no backing."""
    walls = {w.id: w for w in house.walls}
    level = storeys(house)
    out = {"walls": [], "floors": [], "roofs": []}
    for x in house.surfaces:
        d = surface.depth(x, members) or 0.0
        gaps = []
        for side in x.faces if gaps_too else ():
            off = -0.2 if side == "outer" else d + 0.2   # drawn just off the face, outside the framing
            for gp in surface.gaps(x, members, face=side, walls=walls):
                corners = [x.world(u, v, off) for u, v in ((gp.u0, gp.v0), (gp.u1, gp.v0), (gp.u1, gp.v1), (gp.u0, gp.v1))]
                gaps.append({**asdict(gp), "world": corners})
        item = {"id": x.id, "role": x.role, "size": x.size, "outline": outline_uv(x), "storey": level[x.id], "depth": d,
                "origin": x.origin, "eu": x.eu, "ev": x.ev, "ew": x.ew, "openings": [asdict(o) for o in x.openings],
                "gaps": gaps}
        if isinstance(x, Wall):
            face = []   # other walls' members against this wall's face, drawn grey in its elevation
            for m in members:
                if m.surface != x.id and isinstance(house.surface(m.surface), Wall):
                    b = x.local_box(m)
                    if abs(b.lo[2]) <= EPS and b.hi[0] > EPS and b.lo[0] < x.length - EPS and b.hi[1] > EPS and b.lo[1] < x.height - EPS:
                        face.append({"id": m.id, "lo": b.lo, "hi": b.hi})
            item.update({"kind": "wall", "length": x.length, "height": x.height, "base": x.base, "start": x.start,
                         "end": x.end, "start_meets": x.start_meets, "end_meets": x.end_meets, "above": x.above,
                         "below": x.below, "tees": [asdict(t) for t in x.tees], "neighbours": face})
            out["walls"].append(item)
        elif isinstance(x, Roof):
            item.update({"kind": "roof", "pitch": x.pitch, "start": x.start, "end": x.end, "z": x.z,
                         "seams": [asdict(sm) for sm in x.seams]})
            out["roofs"].append(item)
        else:
            item.update({"kind": "floor", "z": x.z,
                         **{k: [{**asdict(b), "along_u": b.along_u, "depth": surface.depth(walls[b.wall], members) or 0.0}
                                for b in getattr(x, k)] for k in ("bearers", "loads")}})
            out["floors"].append(item)
    return out


def frame_payload(house: House, frame: Frame, source: str) -> dict:
    t = time.perf_counter()
    report = verify(house, frame)
    verify_s = time.perf_counter() - t
    g = report.graph
    gone = {m.id for m in frame.removed}
    members = []
    for m in frame.members + frame.removed:
        w = house.surface(m.surface) if m.surface else None
        lb = w.local_box(m) if w else None
        members.append({
            "id": m.id, "rule": m.rule, "role": m.role, "section": m.section, "surface": m.surface, "panel": m.panel,
            "length": round(m.length, 1), **shape(m, w), "removed": m.id in gone,
            "local": [lb.lo, lb.hi] if lb else None,
            "bears": list(g.bears.get(m.id, {})), "carries": list(g.carries.get(m.id, {})),
            "side": list(g.side.get(m.id, {})),
        })
    m = report.metrics
    return {
        "house": house.id, **surfaces_payload(house, frame.members), "members": members,
        "rules": grammar_rules(source), "guides": [guide_payload(house, gd) for gd in frame.guides],
        "steps": frame.steps, "errors": frame.errors,
        "faults": [asdict(f) for f in report.faults], "checks": CHECKS, "report": report.text(),
        "timing": {"verify": verify_s},
        "stats": {"members": m["members"], "hard": report.hard, "soft": report.soft, "cost": m["cost"],
                  "bought_ft": m["bought_ft"], "waste_pct": m["waste_pct"], "steps": len(frame.steps),
                  "by_section": m["by_section"], "panels": m["panels"], "site_pieces": m["site_pieces"]},
    }


def guide_payload(house: House, gd) -> dict:
    """A guide with its ends in the world, for drawing: on its surface, or in plan at the ground."""
    if gd.surface:
        x = house.surface(gd.surface)
        a, b = x.world(*gd.a, 0), x.world(*gd.b, 0)
    else:
        a, b = (*gd.a, 0.0), (*gd.b, 0.0)
    return {**gd.to_dict(), "world": [a, b]}


def outline_uv(x) -> list:
    """A surface's outline in its own u, v, as lists for JSON."""
    return [list(p) for p in x.outline_uv]


def storeys(house: House) -> dict[str, int]:
    """Each surface's storey, from 1: walls by their base, a floor with the walls that stand on it, a ceiling and
    the roof with the top storey."""
    bases = sorted({round(w.base, 3) for w in house.walls})
    out = {w.id: bases.index(round(w.base, 3)) + 1 for w in house.walls}
    for f in house.floors:
        out[f.id] = next((i + 1 for i, b in enumerate(bases) if abs(b - f.z) <= EPS), len(bases) + 1)
        if f.role == "ceiling":
            out[f.id] = max([out[b.wall] for b in f.bearers] or [len(bases)])
    for r in house.roofs:
        out[r.id] = len(bases)
    return out


CODE = re.compile(r"IRC (?:Table )?R[\d.]+(?:\([\d.]+\))?|WFCM[ \d.]*|NDS[ \d.]*|energy code")


def constants() -> dict:
    """The limits at the top of each verifier module (and surface.py, model.py): value, module, and the comment
    beside or above each, which says what it means and which code it comes from."""
    out = {}
    for mod in (*verifier.MODULES, surface, model):
        lines = inspect.getsource(mod).splitlines()
        for node in ast.parse("\n".join(lines)).body:
            name = node.targets[0].id if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) else None
            if not name or not name.isupper() or name in ("CHECKS", "ORDER", "MODULES"):
                continue
            note = lines[node.lineno - 1].split("#", 1)[1].strip() if "#" in lines[node.lineno - 1] else ""
            if not note:   # a block comment above instead
                i, above = node.lineno - 2, []
                while i >= 0 and lines[i].lstrip().startswith("#"):
                    above.insert(0, lines[i].strip()[1:].strip())
                    i -= 1
                note = " ".join(above)
            value = getattr(mod, name)
            if isinstance(value, (int, float, str, tuple, dict)):
                out[name] = {"value": jsonable(value), "note": note, "module": mod.__name__.split(".")[-1]}
    return out


def jsonable(v):
    """A limit as JSON can hold it: tuples as lists, dict keys as text ("1, 5.5" for a tuple key)."""
    if isinstance(v, dict):
        return {(", ".join(map(str, k)) if isinstance(k, tuple) else str(k)): jsonable(x) for k, x in v.items()}
    if isinstance(v, (tuple, list)):
        return [jsonable(x) for x in v]
    return v


def verifier_info() -> dict:
    """Every check (its meaning, hard or soft, the module it lives in, the limits that module sets and the codes
    they cite) and how a frame is scored. Hard or soft is read from the calls that make each fault."""
    hard, home, uses = {}, {}, {}
    consts = constants()
    for mod in verifier.MODULES:
        tree = ast.parse(inspect.getsource(mod))
        calls = {f.name: {n.func.id for n in ast.walk(f) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                 for f in tree.body if isinstance(f, ast.FunctionDef)}
        names = {f.name: {n.id for n in ast.walk(f) if isinstance(n, ast.Name) and n.id in consts}
                 for f in tree.body if isinstance(f, ast.FunctionDef)}
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                kind = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                i = {"Fault": 0, "flag": 0, "at": 2}.get(kind)
                if i is None or len(node.args) <= i + 1 or not all(isinstance(a, ast.Constant) for a in node.args[i:i + 2]):
                    continue
                check = node.args[i].value
                hard[check] = node.args[i + 1].value
                home.setdefault(check, mod.__name__.split(".")[-1])
                # the limits of this check: constants its function reads, and those of the helpers it calls
                used = set(names[fn.name]).union(*(names.get(c, set()) for c in calls[fn.name]))
                uses.setdefault(check, set()).update(used)
    checks = []
    for name, meaning in CHECKS.items():
        mod = home.get(name)
        limits = sorted(uses.get(name, ()), key=list(consts).index)
        text = " ".join([meaning] + [consts[n]["note"] for n in limits])
        checks.append({"name": name, "meaning": meaning, "hard": hard.get(name, True), "module": mod,
                       "limits": limits, "code": sorted(set(CODE.findall(text)))})
    return {"checks": checks, "constants": consts, "cost": [k for k, c in consts.items() if c["module"] == "cost"],
            "sections": {k: v[1] for k, v in SECTIONS.items()}, "about": inspect.getdoc(verifier)}


def build_source(name: str, source: str, house: House, on_step=None) -> Frame:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"{name.replace('.', '_')}.py"
        p.write_text(source)
        return build(p, house, on_step=on_step)


def rule_demo(name: str, source: str, rule: str, firing: int | None = None) -> dict:
    """What one rule does, shown on the toy house: the surface just before one of its firings, and what it placed
    and removed there. `firing` picks which firing (0 = first); by default the first one on wall 1w0."""
    house = houses.toy()
    frame = build_source(name, source, house)
    doc = next((r.get("doc", "") for r in grammar_rules(source) if r.get("name") == rule), "")
    steps = frame.steps
    fired = [i for i, s in enumerate(steps) if s["rule"] == rule]
    out = {"rule": rule, "doc": doc, "house": house.id, "fired": len(fired), "errors": frame.errors[:3]}
    if not fired:
        out["message"] = "This rule did nothing on the toy house."
        return out
    if firing is None:
        firing = next((k for k, i in enumerate(fired) if steps[i]["surface"] == "1w0"), 0)
    firing = max(0, min(len(fired) - 1, firing))
    i = fired[firing]
    step = steps[i]
    w = house.surface(step["surface"])
    same = [x for x in house.surfaces if type(x) is type(w)]
    out["span"] = [max(x.size[0] for x in same), max(x.size[1] for x in same)]   # one scale for surfaces of its kind
    placed_at, removed_at = {}, {}
    for k, s in enumerate(steps):
        for mid in s["placed"]:
            placed_at[mid] = k
        for mid in s["removed"]:
            removed_at[mid] = k
    allm = {m.id: m for m in frame.members + frame.removed}

    def box(m) -> dict:
        b = w.local_box(m)
        return {"id": m.id, "rule": m.rule, "role": m.role, "u0": b.lo[0], "v0": b.lo[1], "u1": b.hi[0], "v1": b.hi[1],
                "w0": b.lo[2], **polys(w, m)}

    before = [m for m in allm.values() if placed_at.get(m.id, -1) < i and removed_at.get(m.id, 10**9) >= i]
    own = [box(m) for m in before if m.surface == w.id]
    near = []
    for m in before if isinstance(w, Wall) else []:
        if m.surface == w.id:
            continue
        b = box(m)
        if abs(b["w0"]) <= EPS and b["u1"] > EPS and b["u0"] < w.length - EPS:
            near.append(b)
    shape = {"id": w.id, "kind": "wall" if isinstance(w, Wall) else "roof" if isinstance(w, Roof) else "floor",
             "role": w.role, "size": w.size, "outline": outline_uv(w), "openings": [asdict(o) for o in w.openings],
             "tees": [asdict(t) for t in w.tees] if isinstance(w, Wall) else [],
             "bearers": [{**asdict(b), "depth": surface.depth(house.wall(b.wall), frame.members) or 0.0}
                         for b in w.bearers] if isinstance(w, Floor) else []}
    out.update({
        "firing": firing, "pass": step["pass"], "match": step["match"], "target": step["target"],
        "surface": shape,
        "firings": [{"surface": steps[k]["surface"], "pass": steps[k]["pass"]} for k in fired],
        "before": own, "neighbours": near,
        "placed": [box(allm[mid]) for mid in step["placed"] if mid in allm],
        "removed": [box(allm[mid]) for mid in step["removed"] if mid in allm],
        "shaped": [box(allm[mid]) for mid in step["shaped"] if mid in allm and allm[mid].surface == w.id],
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

    def stream_build(self, name: str, source: str, house: House) -> None:
        """Build and stream it as it happens: the house's surfaces, one JSON line per step with the pieces it placed,
        then the frame."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def line(d: dict) -> None:
            self.wfile.write(json.dumps(d).encode() + b"\n")
            self.wfile.flush()

        def on_step(step: dict, members: dict) -> None:
            draw = lambda ids: [{"id": i, "rule": m.rule, "panel": m.panel, **shape(m, None)} for i in ids
                                if (m := members.get(i))]
            line({"step": {"rule": step["rule"], "surface": step["surface"], "t": step["t"], "placed": draw(step["placed"]),
                           "removed": step["removed"], "shaped": draw(step["shaped"]),
                           "assigned": [{"id": i, "panel": members[i].panel} for i in step["assigned"] if i in members]}})

        try:
            line({"house": {"house": house.id, **surfaces_payload(house, [], gaps_too=False)}})
            t = time.perf_counter()
            frame = build_source(name, source, house, on_step)
            build_s = time.perf_counter() - t
            line({"built": build_s})
            out = frame_payload(house, frame, source)
            out["timing"]["build"] = build_s
            line({"frame": out})
        except Exception as e:   # the headers are sent: report it in the stream
            line({"frame": {"error": f"{type(e).__name__}: {e}"}})

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
                    xs = [p[0] for w in h.walls for p in (w.start, w.end)]
                    ys = [p[1] for w in h.walls for p in (w.start, w.end)]
                    out.append({"id": h.id, "walls": len(h.walls), "storeys": len({round(w.base, 3) for w in h.walls}),
                                "openings": sum(len(x.openings) for x in h.surfaces),
                                "size": [round(max(xs) - min(xs)), round(max(ys) - min(ys))]})
                return self.send(200, out)
            if path == "/api/verifier":
                return self.send(200, verifier_info())
            if path == "/api/grammars":
                return self.send(200, grammar_names())
            if path.startswith("/api/grammar/"):
                name = path.split("/")[-1]
                if not grammar_file(name):
                    return self.send(404, {"error": "no such grammar"})
                src = grammar_file(name).read_text()
                return self.send(200, {"name": name, "source": src, "rules": grammar_rules(src)})
            if path == "/api/jobs":
                return self.send(200, {"jobs": jobs_now(), "credentials": jobs_mod.credentials()})
            if path.startswith("/api/job/"):
                try:
                    return self.send(200, JOBS.get(path.split("/")[3]))
                except ValueError as e:
                    return self.send(404, {"error": str(e)})
            if path == "/api/runs":
                runs = [run_summary(p.parent) for p in sorted(RUNS.glob("*/config.json"), key=lambda q: -q.stat().st_mtime)
                        if NAME.match(p.parent.name)] if RUNS.is_dir() else []
                return self.send(200, runs)
            if path.startswith("/api/run/"):
                parts = path[len("/api/run/"):].strip("/").split("/")
                run = run_dir(parts[0])
                if run is None:
                    return self.send(404, {"error": "no such run"})
                if len(parts) == 1:
                    return self.send(200, run_payload(run))
                if len(parts) == 2 and parts[1] == "live":
                    q = parse_qs(urlparse(self.path).query)
                    return self.send(200, live_payload(run, q.get("proposal", [""])[0], int(q.get("after", ["0"])[0])))
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
                source = source_of(b)
                if source is None:
                    return self.send(400, {"error": "no such grammar"})
                return self.stream_build(b["grammar"], source, House.load(HOUSES / f"{b['house']}.json"))
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
                source = source_of(b)
                if source is None:
                    return self.send(400, {"error": "no such grammar"})
                firing = b.get("firing")
                return self.send(200, rule_demo(b["grammar"], source, str(b["rule"]), None if firing is None else int(firing)))
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
                if RUN_GRAMMAR.match(name):
                    return self.send(400, {"error": "a run's grammar is kept as the search found it; copy it into "
                                                    "grammars/ to change it"})
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
