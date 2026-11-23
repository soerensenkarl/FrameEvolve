"""The input houses page: Cambridge houses in 3D, each as the city's model and as the detailed House.

The workbench serves it at /houses/ (server.py hands everything under that to respond()). The page is built
afresh by a new Python on every load, so a reload shows the code and the amendments as they are now, with no
restart. On the page a pen marks what is wrong; each note is saved in data/cambridge/notes as a picture (the view
with the marks) and a JSON file (house, comment, status, reply); a house passed as good is a note with status
"ok" and no picture. The page's keys are listed under Shortcuts. `python -m frameevolve.cambridge_view [count]`
prints the page.
"""
from __future__ import annotations

import base64
import json
import random
import subprocess
import sys
import time
import traceback
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
            item["amended"] = len(house.amended)
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
    data.sort(key=lambda item: not item.get("amended"))       # the houses with amendments first, in their own group
    return (ROOT / "web" / "cambridge.html").read_text().replace("/*DATA*/", json.dumps(data))


def notes() -> list[dict]:
    """Every note, oldest first."""
    return [json.loads(p.read_text()) for p in sorted(NOTES.glob("*.json"))]


def respond(method: str, path: str, body: dict | None = None, count: int = 20) -> tuple[int, bytes, str]:
    """The page and its notes, for the workbench to serve under /houses/: (status, body, content type). "" is
    the page, built by a fresh Python so it is the code as it is now; notes are listed, added, changed and
    deleted under notes; a house's side photos are under evidence."""
    NOTES.mkdir(parents=True, exist_ok=True)
    note = NOTES / (Path(path).stem + ".json")            # the name only: nothing outside the notes folder
    if method == "GET" and path in ("", "index.html"):
        page = subprocess.run([sys.executable, "-m", "frameevolve.cambridge_view", str(count)], cwd=ROOT, capture_output=True)
        return 200, page.stdout or b"<pre>" + page.stderr, "text/html; charset=utf-8"
    if method == "GET" and path == "notes":
        return 200, json.dumps(notes()).encode(), "application/json"
    if method == "GET" and path.startswith("evidence/") and path.endswith(".jpg"):
        f = cambridge.OUT / "evidence" / Path(path).parent.name / Path(path).name
        return (200, f.read_bytes(), "image/jpeg") if f.exists() else (404, b"", "image/jpeg")
    if method == "GET" and path.endswith(".png") and note.with_suffix(".png").exists():
        return 200, note.with_suffix(".png").read_bytes(), "image/png"
    if method == "POST" and path == "notes":
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{body['house']}"
        if body.get("png"):
            (NOTES / f"{name}.png").write_bytes(base64.b64decode(body.pop("png").split(",", 1)[1]))
        (NOTES / f"{name}.json").write_text(json.dumps({"id": name, "status": "open", "reply": "", **body}, indent=1))
        return 200, b"{}", "application/json"
    if method == "PUT" and note.exists():
        note.write_text(json.dumps({**json.loads(note.read_text()), **body}, indent=1))
        return 200, b"{}", "application/json"
    if method == "DELETE":
        for f in (note, note.with_suffix(".png")):
            f.unlink(missing_ok=True)
        return 200, b"{}", "application/json"
    return 404, b"{}", "application/json"


if __name__ == "__main__":
    sys.stdout.write(build(int(sys.argv[1]) if len(sys.argv) > 1 else 20))
