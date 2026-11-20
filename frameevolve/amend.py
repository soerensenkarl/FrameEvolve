"""A house's amendments to the general procedure: the file, and a tool to try them.

The detailer (detail.py) is the general procedure: it covers most houses. What one house needs different is
written in its own file, data/amendments/<model>.json, as the building code is amended town by town:

  {"house": "CAM_...", "address": "...",
   "amendments": [
     {"set": {"floors_ft": [3.5, 13.5]}, "by": "who", "from": "the four side photos", "why": "a raised basement"},
     {"openings": {"side": "south", "storey": 1, "items": [{"at": 0.2, "kind": "window", "w": 32, "h": 60}]}, ...},
     ...]}

Each amendment has one verb, and may say who made it ("by"), from what ("from") and why. They are taken in order.

  settings for the procedure
    set        floors_ft   the top of each floor over the ground, feet, lowest first (a sill is 2 1/2 to 3 ft over
                           its floor; a raised basement is not a storey)
               span        "long" (bearing walls laid for 22 ft spans) or "standard" (16 ft)
               attic       "ceiling", "open" (the top storey open to the roof) or "loft" (a ceiling over part)
               windows     {"width": 32, "height": 60, "head": 82.5}: the house's usual window, inches
               seed        another roll of the dice for everything the procedure makes up
  changes to what it made
    openings   {"side", "storey", "items"}: the openings of one storey of one side (south, east, north, west: the
               house seen from outside), each {"at", "kind": "window" or "door", "w", "h"}; "at" is the opening's
               middle on the side's ruler, 0 at its left end and 1 at its right; an empty list is a blank wall
    porch      {"near_ft": [x, y], "open": true}: the mass at that place is a porch open between corner posts (or,
               false, a room)
    stair      {"at_ft": [x, y], "long": "y"}: the stair opening's corner and the way its long side runs
    void       {"at_ft": [x, y], "size_ft": [12, 14]}: a room of double height, the opening in the floor over the
               ground storey; or false for none
    wall       {"storey", "from_ft", "to_ft", "bearing": false}: a wall inside
    no_wall    {"storey", "near_ft"}: take out the wall inside that passes within 3 ft of that place
    open       {"storey", "near_ft"}: the bearing wall there opened into posts and a beam; close: kept solid
    door       {"storey", "near_ft", "w": 34}: a door in the wall inside nearest that place
  a step replaced
    interior   {"storey", "walls": [{"from_ft", "to_ft", "bearing"}]}: this storey's inside walls, all of them
  and, for a house the procedure cannot do at all, in place of "amendments":
    "script": "CAM_....py"   a Python file beside the JSON with build(env, record) -> House

Plan places are feet in the house's own coordinates, as the plan drawings show them. An amendment names a place,
never the procedure's name for a thing, so it survives changes to the procedure; if it finds nothing to act on
it is reported as not applied, and check.py judges the house as it does any other.

`python -m frameevolve.amend <model>` details the house with its amendments, prints what came of each, what
the procedure chose where nothing was amended, and check.py's verdict; and draws the result to hold against the
photos: detailed_<side>.png on each side photo's ruler, plan_<storey>.png in feet (data/cambridge/evidence/<model>).
`--photos` also (re)makes the side photos.
"""
from __future__ import annotations

import importlib.util
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

from frameevolve import cambridge, envelope, photos
from frameevolve.check import problems
from frameevolve.detail import detail

FILES = cambridge.OUT.parent / "amendments"


def read(model: str) -> dict:
    """A house's amendment file, or an empty one."""
    f = FILES / f"{model}.json"
    return json.loads(f.read_text()) if f.exists() else {"house": model, "amendments": []}


def build(record: dict, env=None):
    """A house detailed by the general procedure and its amendments (or by its own script): (house, envelope)."""
    model = record["model"]
    env = env or envelope.envelope(cambridge.OUT / "models" / f"{model}.obj")
    file = read(model)
    if file.get("script"):
        spec = importlib.util.spec_from_file_location(model, FILES / file["script"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        house = module.build(env, record)
        house.amended = [({"script": file["script"]}, "applied")]
        return house, env
    return detail(env, record, 0, model, file), env


def record_of(model: str) -> dict:
    return next(h for h in json.loads((cambridge.OUT / "houses.json").read_text()) if h["model"] == model)


def draw_side(house, side: str, out) -> None:
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


def draw_plan(house, storey: int, out) -> None:
    """A storey's plan in feet, the house's own coordinates: outside walls black, bearing walls inside red,
    partitions blue, windows cyan, doors orange, openings in the floor hatched."""
    base = sorted({w.base for w in house.walls})[storey - 1]
    fig, ax = plt.subplots(figsize=(8, 7))
    for f in house.floors:
        if f.role == "floor" and abs(f.z - base) < 1:
            ax.add_patch(Polygon([(x / 12, y / 12) for x, y in f.outline], closed=True, fc="#f6efdf", ec="none"))
            for o in f.openings:
                c = [f.world(u, v, 0)[:2] for u, v in [(o.u0, o.v0), (o.u1, o.v0), (o.u1, o.v1), (o.u0, o.v1)]]
                ax.add_patch(Polygon([(x / 12, y / 12) for x, y in c], closed=True, fc="none", ec="#c0392b", hatch="///"))
                ax.text(sum(x for x, _ in c) / 48, sum(y for _, y in c) / 48, o.kind, fontsize=7, ha="center", color="#c0392b")
    for w in house.walls:
        if w.base != base:
            continue
        colour = "#222" if w.role == "exterior" else "#c0392b" if w.id[1] in "sj" else "#2a6fb0"
        marks = [0.0] + [u for o in w.openings for u in (o.u0, o.u1)] + [w.length]
        for a, b in zip(marks[::2], marks[1::2]):
            p, q = w.world(a, 0, 0), w.world(b, 0, 0)
            ax.plot([p[0] / 12, q[0] / 12], [p[1] / 12, q[1] / 12], color=colour, lw=3 if w.role == "exterior" else 2, solid_capstyle="butt")
        for o in w.openings:
            p, q = w.world(o.u0, 0, 0), w.world(o.u1, 0, 0)
            ax.plot([p[0] / 12, q[0] / 12], [p[1] / 12, q[1] / 12], color="#35a7e0" if o.kind == "window" else "#e08a1e", lw=1.5)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.grid(alpha=0.3)
    ax.set_xlabel("x, ft (south is down: the south side photo looks at this plan from below)")
    ax.set_ylabel("y, ft")
    ax.set_title(f"storey {storey}: outside black, bearing inside red, partitions blue, windows cyan, doors orange")
    fig.tight_layout()
    fig.savefig(out, dpi=80)
    plt.close(fig)


def main(model: str, with_photos: bool = False) -> None:
    record = record_of(model)
    house, env = build(record)
    folder = photos.EVIDENCE / model
    folder.mkdir(parents=True, exist_ok=True)
    if with_photos:
        photos.evidence(house, record, env, cambridge.OUT / "models" / f"{model}.obj")
    for side in photos.SIDES:
        draw_side(house, side, folder / f"detailed_{side}.png")
    levels = sorted({w.base for w in house.walls})
    for k in range(1, len(levels) + 1):
        draw_plan(house, k, folder / f"plan_{k}.png")
    outer = [w for w in house.walls if w.role == "exterior"]
    xs = [p[0] for w in outer for p in (w.start, w.end)]
    ys = [p[1] for w in outer for p in (w.start, w.end)]
    print(f"{record['address']} ({model}); assessor: {record.get('exterior_style')}, {record.get('exterior_numstories')} storeys, "
          f"{record.get('exterior_rooftype')} roof, built {record.get('condition_yearbuilt')}, {record.get('interior_totalrooms')} rooms, "
          f"{record.get('interior_numunits')} unit(s)")
    print(f"plan {max(xs) / 12:.1f} by {max(ys) / 12:.1f} ft; floors at {[round((b + house.foundation) / 12, 1) for b in levels]} ft over the ground; "
          f"top of the highest wall {max((w.base + max(v for _, v in w.outline_uv) + house.foundation) / 12 for w in outer):.1f} ft")
    print(f"walls: {len(outer)} outside, {sum(w.id[1] in 'sj' for w in house.walls if w.role == 'interior')} bearing inside, "
          f"{sum(w.id[1] == 'p' for w in house.walls)} partitions; openings outside: {sum(len(w.openings) for w in outer)}")
    for side, d in photos.SIDES.items():
        rows = {}
        for w in outer:
            if -(w.normal[0] * d[0] + w.normal[1] * d[1]) > 0.5:
                rows.setdefault(levels.index(w.base) + 1, []).extend(o.kind[0] for o in w.openings)
        print(f"  {side}: " + "; ".join(f"storey {k}: {''.join(sorted(v)) or '-'}" for k, v in sorted(rows.items())) + "   (w window, d door)")
    if house.stair is not None:
        x0, y0, x1, y1 = house.stair.bounds
        print(f"stair opening from ({x0 / 12:.1f}, {y0 / 12:.1f}) to ({x1 / 12:.1f}, {y1 / 12:.1f}) ft")
    print("the procedure gave it: " + (", ".join(sorted(house.has)) or "nothing special"))
    for k, (a, result) in enumerate(house.amended):
        verb = next((v for v in a if v not in ("by", "from", "why")), "?")
        where = {key: a[verb][key] for key in ("side", "storey", "near_ft", "at_ft") if isinstance(a[verb], dict) and key in a[verb]}
        print(f"amendment {k + 1} ({verb}{' ' + json.dumps(where) if where else ''}): {result}")
    if house.missed:
        print("found no place: " + "; ".join(house.missed))
    wrong = problems(house)
    print("VALID: passes every check" if not wrong else "NOT VALID: " + "; ".join(wrong))
    print(f"drawn in {folder}: detailed_<side>.png, plan_<storey>.png")


if __name__ == "__main__":
    main(sys.argv[1], "--photos" in sys.argv)
