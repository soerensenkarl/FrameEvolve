"""A page to look at Cambridge houses in 3D: each as the city's model and as the detailed House, one over the other.

`python -m frameevolve.cambridge_view [count]` details a spread of houses (by roof type) and serves the page at
http://localhost:8770, built afresh by a new Python on every load: a reload shows the code and the briefs as
they are now, with no restart. On the page a pen marks what is wrong; each note is saved in
data/cambridge/notes as a picture (the view with the marks) and a JSON file (house, comment, status, reply); a
house passed as good is a note with status "ok" and no picture. The page's keys are listed under "?".
"""
from __future__ import annotations

import base64
import json
import random
import subprocess
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from frameevolve import amend, cambridge, envelope
from frameevolve.check import problems

ROOT = Path(__file__).resolve().parents[1]
WOOD = ("Frame-Clapbrd", "Wood Shingle", "Aluminum-Vinyl", "Asbstos Shingl", "Ashalt Shingle")


def sample(houses: list[dict], count: int, seed: int = 0) -> list[dict]:
    """A spread of wood-framed houses: as many of each roof type as there are types to go round."""
    rng = random.Random(seed)
    by_roof: dict[str, list] = {}
    for h in houses:
        if h.get("exterior_walltype") in WOOD and h["off_m"] <= 8:
            by_roof.setdefault(h.get("exterior_rooftype", ""), []).append(h)
    out = []
    pools = [rng.sample(v, len(v)) for _, v in sorted(by_roof.items())]
    while len(out) < count and any(pools):
        for pool in pools:
            if pool and len(out) < count:
                out.append(pool.pop())
    return out


def surfaces(house) -> list[dict]:
    """Every surface as the page draws it: an origin, two axes, an outline and its openings in those axes."""
    out = []
    for x in house.surfaces:
        kind = "roof" if x.role == "roof" else x.role if x in house.floors else "wall"
        z = x.base if kind == "wall" else x.z if kind in ("floor", "ceiling") else None
        bearing = kind == "wall" and x.role == "interior" and x.id[1] in "sj"      # a bearing wall or a junction wall: it carries floors
        out.append({"id": x.id, "kind": kind, "role": x.role, "bearing": bearing, "z": z, "o": x.origin, "u": x.eu, "v": x.ev,
                    "outline": [list(p) for p in x.outline_uv],
                    "openings": [[o.kind, o.u0, o.v0, o.u1, o.v1] for o in x.openings]})
    return out


NOTES = cambridge.OUT / "notes"
PORT = 8770


def build(count: int = 20) -> str:
    houses = json.loads((cambridge.OUT / "houses.json").read_text())
    data = []
    for h in sample(houses, count):
        path = cambridge.OUT / "models" / f"{h['model']}.obj"
        item = {"name": h["address"], "id": h["model"], "info": f'{h["propertyclass"]}, {h.get("exterior_style", "")}, {h.get("exterior_numstories")} storeys, '
                f'{h.get("exterior_rooftype")} roof, {h.get("exterior_walltype")}, built {h.get("condition_yearbuilt")}'}
        try:
            env = envelope.envelope(path)
            vs = [env.place(tuple(map(float, l.split()[1:4]))) for l in path.read_text().splitlines() if l.startswith("v ")]
            tris = [[int(x.split("/")[0]) - 1 for x in l.split()[1:4]] for l in path.read_text().splitlines() if l.startswith("f ")]
            item["raw"] = {"v": [round(c, 1) for v in vs for c in v], "f": [i for t in tris for i in t]}
            house, _ = amend.build(h, env)
            missed = sum(not r.startswith("applied") and "placed" not in r for _, r in house.amended)
            item["lift"] = house.foundation
            item["surfaces"] = surfaces(house)
            wrong = problems(house)
            item["problems"] = wrong
            item["name"] = ("" if not wrong else "✗ ") + item["name"]
            item["info"] += (f'. Detailed: {len({w.base for w in house.walls})} storeys, {len(house.walls)} walls, '
                             f'{sum(len(w.openings) for w in house.walls)} openings, {len(house.roofs)} roof planes; '
                             f'taken off: {env.dropped or "nothing"}. '
                             + ("VALID: passes every check." if not wrong else "NOT VALID: " + "; ".join(wrong[:4]))
                             + (f" AMENDED: {len(house.amended)} amendments" + (f", {missed} not applied." if missed else ".") if house.amended else "")
                             + (" Has: " + ", ".join(sorted(house.has)) + "." if house.has else ""))
        except Exception:
            item["problems"] = ["detailing failed: " + traceback.format_exc().splitlines()[-1]]
        data.append(item)
    return (ROOT / "web" / "cambridge.html").read_text().replace("/*DATA*/", json.dumps(data))


def notes() -> list[dict]:
    """Every note, oldest first."""
    return [json.loads(p.read_text()) for p in sorted(NOTES.glob("*.json"))]


def serve(count: int) -> None:
    """The page and its notes: GET / builds the page; notes are listed, added, changed and deleted under /notes."""
    NOTES.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def send(self, body: bytes, kind: str = "application/json", code: int = 200) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def body(self) -> dict:
            return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

        def note(self) -> Path:
            return NOTES / (Path(self.path).stem + ".json")       # the name only: nothing outside the notes folder

        def do_GET(self):
            if self.path in ("/", "/index.html"):       # built by a fresh Python, so the page is the code as it is now
                page = subprocess.run([sys.executable, "-m", "frameevolve.cambridge_view", "--build", str(count)], cwd=ROOT, capture_output=True)
                self.send(page.stdout or b"<pre>" + page.stderr, "text/html; charset=utf-8")
            elif self.path == "/notes":
                self.send(json.dumps(notes()).encode())
            elif self.path.startswith("/evidence/") and self.path.endswith(".jpg"):
                f = cambridge.OUT / "evidence" / Path(self.path).parent.name / Path(self.path).name
                self.send(f.read_bytes(), "image/jpeg") if f.exists() else self.send(b"", code=404)
            elif self.path.endswith(".png") and self.note().with_suffix(".png").exists():
                self.send(self.note().with_suffix(".png").read_bytes(), "image/png")
            else:
                self.send(b"{}", code=404)

        def do_POST(self):
            d = self.body()
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-{d['house']}"
            if d.get("png"):
                (NOTES / f"{name}.png").write_bytes(base64.b64decode(d.pop("png").split(",", 1)[1]))
            (NOTES / f"{name}.json").write_text(json.dumps({"id": name, "status": "open", "reply": "", **d}, indent=1))
            self.send(b"{}")

        def do_PUT(self):
            p = self.note()
            p.write_text(json.dumps({**json.loads(p.read_text()), **self.body()}, indent=1))
            self.send(b"{}")

        def do_DELETE(self):
            for p in (self.note(), self.note().with_suffix(".png")):
                p.unlink(missing_ok=True)
            self.send(b"{}")

        def log_message(self, *args):
            pass

    print(f"http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--build"]:
        sys.stdout.write(build(int(sys.argv[2])))
    else:
        serve(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
