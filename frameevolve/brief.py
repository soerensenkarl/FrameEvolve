"""Try a brief: detail a house from it, say what came of it, and draw the result beside the photos.

`python -m frameevolve.brief <model>` reads data/cambridge/briefs/<model>.json (none: the detailer alone), details
the house, prints its storeys, how many of the brief's openings were placed and which found no place, and what
check.py finds wrong; and draws each side of the detailed house on the photos' ruler
(data/cambridge/evidence/<model>/detailed_<side>.png), to hold against <side>.jpg. With `--photos` it also
(re)makes the four side photos.

A brief is JSON, written from the four photos (south, east, north, west: the house seen from outside, square on):

  {"by": "who wrote it", "notes": "what was seen, what was hidden",
   "floors_ft": [3.5, 13.5],                  the top of each floor over the ground, lowest first, read off the
                                              cyan scale: a window's sill is about 2 1/2 to 3 ft over its floor
   "sides": {"south": {"1": [{"at": 0.20, "kind": "window", "w": 32, "h": 60},
                             {"at": 0.55, "kind": "door", "w": 36}],
                       "2": [...]},
             "east": null, ...}}

"at" is the opening's middle on the red ruler under the photo (0 at the house's left end, 1 at its right); "w"
and "h" are inches; a storey is counted from the ground floor, 1. A side that cannot be seen is null and a storey
of a side that cannot be seen is left out: the detailer then makes those up. An empty list says the storey was
seen and has no openings.
"""
from __future__ import annotations

import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

from frameevolve import cambridge, envelope, photos
from frameevolve.check import problems
from frameevolve.detail import detail

BRIEFS = cambridge.OUT / "briefs"


def load(model: str):
    """(record, envelope, brief or None, house) of a model id."""
    record = next(h for h in json.loads((cambridge.OUT / "houses.json").read_text()) if h["model"] == model)
    path = cambridge.OUT / "models" / f"{model}.obj"
    env = envelope.envelope(path)
    f = BRIEFS / f"{model}.json"
    brief = json.loads(f.read_text()) if f.exists() else None
    return record, env, brief, detail(env, record, 0, model, brief), path


def draw(house, side: str, out) -> None:
    """One side of a detailed house as the photos show it: the same ruler, heights over the ground in feet."""
    d = photos.SIDES[side]
    r0, r1 = photos.extent(house, side)
    fig, ax = plt.subplots(figsize=(7, 5))
    walls = [w for w in house.walls if w.role == "exterior" and -(w.normal[0] * d[0] + w.normal[1] * d[1]) > 0.5]
    at = lambda w, u, v: (((-d[1] * w.world(u, v, 0)[0] + d[0] * w.world(u, v, 0)[1]) - r0) / (r1 - r0), (w.base + v + house.foundation) / 12)
    for w in sorted(walls, key=lambda w: (w.start[0] + w.end[0]) * d[0] + (w.start[1] + w.end[1]) * d[1]):
        ax.add_patch(Polygon([at(w, u, v) for u, v in w.outline_uv], closed=True, fc="#efe9de", ec="#333", lw=0.8))
        for o in w.openings:
            ax.add_patch(Polygon([at(w, o.u0, o.v0), at(w, o.u1, o.v0), at(w, o.u1, o.v1), at(w, o.u0, o.v1)], closed=True,
                                 fc="#9cc9ea" if o.kind == "window" else "#b9824f", ec="#333", lw=0.6))
    for r in house.roofs:
        pts = [r.world(u, v, 0) for u, v in r.outline]
        ax.add_patch(Polygon([(((-d[1] * p[0] + d[0] * p[1]) - r0) / (r1 - r0), (p[2] + house.foundation) / 12) for p in pts],
                             closed=True, fc="#c8a27e", ec="#6b4b2a", lw=0.5, alpha=0.35))
    for k, base in enumerate(sorted({w.base for w in house.walls})):
        ax.axhline((base + house.foundation) / 12, color="#c9a400", lw=0.6, ls="--")
        ax.text(1.01, (base + house.foundation) / 12, f"floor {k + 1}", fontsize=7, color="#8a7000", va="center")
    ax.set_xlim(-0.05, 1.12)
    ax.set_ylim(0, max((w.base + max(v for _, v in w.outline_uv) + house.foundation) / 12 for w in house.walls) + 8)
    ax.set_xticks([i / 10 for i in range(11)])
    ax.set_xlabel(f"{side} side: the ruler of the photo")
    ax.set_ylabel("ft over the ground")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=80)
    plt.close(fig)


def main(model: str, with_photos: bool = False) -> None:
    record, env, brief, house, path = load(model)
    folder = photos.EVIDENCE / model
    folder.mkdir(parents=True, exist_ok=True)
    if with_photos:
        photos.evidence(house, record, env, path)
    for side in photos.SIDES:
        draw(house, side, folder / f"detailed_{side}.png")
    outer = [w for w in house.walls if w.role == "exterior"]
    asked = sum(len(v or []) for s in ((brief or {}).get("sides") or {}).values() if s for v in s.values())
    levels = sorted({w.base for w in house.walls})
    print(f"{record['address']} ({model}); assessor: {record.get('exterior_style')}, {record.get('exterior_numstories')} storeys, "
          f"{record.get('exterior_rooftype')} roof, built {record.get('condition_yearbuilt')}")
    print(f"floors at {[round((b + house.foundation) / 12, 1) for b in levels]} ft over the ground; "
          f"top of the highest wall {max((w.base + max(v for _, v in w.outline_uv) + house.foundation) / 12 for w in outer):.1f} ft")
    print(f"openings outside: {sum(len(w.openings) for w in outer)} in all" +
          (f"; of the brief's {asked}, {house.placed} placed (the rest of those in all are made up where the brief was silent)" if brief else " (no brief)"))
    for side, d in photos.SIDES.items():
        rows = {}
        for w in outer:
            if -(w.normal[0] * d[0] + w.normal[1] * d[1]) > 0.5:
                rows.setdefault(levels.index(w.base) + 1, []).extend(o.kind[0] for o in w.openings)
        print(f"  {side}: " + "; ".join(f"storey {k}: {''.join(sorted(v)) or '-'}" for k, v in sorted(rows.items())) + "   (w window, d door)")
    if house.missed:
        print("found no place:", "; ".join(house.missed))
    wrong = problems(house)
    print("VALID: passes every check" if not wrong else "NOT VALID: " + "; ".join(wrong))
    print(f"drawn: {folder}/detailed_<side>.png")


if __name__ == "__main__":
    main(sys.argv[1], "--photos" in sys.argv)
