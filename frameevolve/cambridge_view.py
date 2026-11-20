"""A page to look at Cambridge houses in 3D: each as the city's model and as the detailed House, one over the other.

`python -m frameevolve.cambridge_view [count]` details a spread of houses (by roof type) and writes
out/cambridge.html, one file that opens without a server.
"""
from __future__ import annotations

import json
import random
import sys
import traceback
from pathlib import Path

from frameevolve import cambridge, envelope
from frameevolve.detail import detail

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
        out.append({"id": x.id, "kind": kind, "role": x.role, "o": x.origin, "u": x.eu, "v": x.ev,
                    "outline": [list(p) for p in x.outline_uv],
                    "openings": [[o.kind, o.u0, o.v0, o.u1, o.v1] for o in x.openings]})
    return out


def build(count: int = 20) -> Path:
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
            house = detail(env, h, 0, h["model"])
            item["lift"] = house.foundation
            item["surfaces"] = surfaces(house)
            item["info"] += (f'. Detailed: {len({w.base for w in house.walls})} storeys, {len(house.walls)} walls, '
                             f'{sum(len(w.openings) for w in house.walls)} openings, {len(house.roofs)} roof planes; '
                             f'taken off: {env.dropped or "nothing"}')
        except Exception:
            item["info"] += ". Detailing failed: " + traceback.format_exc().splitlines()[-1]
        data.append(item)
    out = ROOT / "out" / "cambridge.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text((ROOT / "web" / "cambridge.html").read_text().replace("/*DATA*/", json.dumps(data)))
    return out


if __name__ == "__main__":
    print(build(int(sys.argv[1]) if len(sys.argv) > 1 else 20))
