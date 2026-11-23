"""Is a detailed house a design that could be built? What is wrong with it, in words.

A house from detail.py is made up to fit a real envelope, so nothing guarantees it: every house is checked, and
only one with nothing wrong belongs in a dataset. The checks are of the design, before any framing:

  standing   every wall above the ground floor stands on a floor
  walls      no two walls of a storey cross or lie along each other; none is a sliver
  openings   each lies in its wall clear of the ends, of the other openings and of the walls that meet it, and
             under the wall's top
  rooms      every room of a storey can be reached, through doors, from outside or from the stair
  stair      a house of more than one storey has a stair opening in every floor
  meeting    every edge of a roof plane lies along another roof plane's edge, a wall's top, or a wall's face
  roof       there is a roof over all of it and none runs out beyond the walls; no bearing wall or partition stands through the roof over it
  loads      all the load on the surfaces comes down to the ground (loads.py)

`framing=True` adds whether the seed grammar frames it without a rule error. That is kept apart: the seed is
bare (it cannot yet frame the pointed end of a hip, say), and what it cannot frame is the search's to learn.
"""
from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from frameevolve.builder import build
from frameevolve.detail import rooms_of, top_over
from frameevolve.geometry import inside
from frameevolve.loads import Takedown
from frameevolve.model import House

SEED = Path(__file__).resolve().parents[1] / "grammars" / "seed.py"
SLIVER = 12.0      # a wall shorter than this is a fault of the envelope, not a wall
LOST = 0.005       # the share of the load that may go astray


def unmet(house: House, near: float = 0.1) -> list[tuple]:
    """The roof edges that meet nothing, as (roof id, end, end, inches unmet): every edge of a roof plane should
    lie along an edge of another roof plane (a ridge, a hip, a valley), along the top of a wall, or against a
    wall's face. Measured at three points an edge, to a tenth of an inch."""
    def off(p, a, b):
        ab = [b[i] - a[i] for i in range(3)]
        L2 = sum(x * x for x in ab) or 1e-12
        t = min(1.0, max(0.0, sum((p[i] - a[i]) * ab[i] for i in range(3)) / L2))
        return sum((p[i] - a[i] - t * ab[i]) ** 2 for i in range(3)) ** 0.5
    edges = {r.id: [(r.world(*a, 0), r.world(*b, 0)) for a, b in zip(r.outline, r.outline[1:] + r.outline[:1])] for r in house.roofs}
    tops = []
    for w in house.walls:
        line = [w.world(u, v, 0) for u, v in w.outline_uv[2:]]
        tops += list(zip(line, line[1:]))
    out = []
    for r in house.roofs:
        for a, b in edges[r.id]:
            L = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
            loose = 0.0
            for t in (0.2, 0.5, 0.8):
                p = tuple(a[i] + t * (b[i] - a[i]) for i in range(3))
                met = any(off(p, c, d) < near for q, es in edges.items() if q != r.id for c, d in es) or any(off(p, c, d) < near for c, d in tops)
                if not met:                    # against the face of a wall that goes on up past it
                    for w in house.walls:
                        u, v, d = w.local(p)
                        if abs(d) < near and -near <= u <= w.length + near and -near <= v <= top_over(w, max(u - 0.5, 0), min(u + 0.5, w.length)) + near:
                            met = True
                            break
                loose += 0.0 if met else L / 3
            if loose:
                out.append((r.id, a, b, loose))
    return out


def problems(house: House, framing: bool = False) -> list[str]:
    """Everything that keeps a house from being a buildable design; empty if nothing does."""
    out = []
    bases = sorted({w.base for w in house.walls})
    for w in house.walls:
        if w.base > 0 and w.below is None:
            out.append(f"standing: wall {w.id} stands on no floor")
        if w.length < SLIVER:
            out.append(f"walls: {w.id} is only {w.length:.0f} in. long")
        for o in w.openings:
            if o.u0 < 3.9 or o.u1 > w.length - 3.9:
                out.append(f"openings: {o.id} is at the end of wall {w.id}")
            if top_over(w, o.u0, o.u1) < o.v1 + 5:
                out.append(f"openings: {o.id} reaches the top of wall {w.id}")
            if any(o.u0 - 3 < t.u < o.u1 + 3 for t in w.tees):
                out.append(f"openings: wall {next(t.wall for t in w.tees if o.u0 - 3 < t.u < o.u1 + 3)} ends in {o.kind} {o.id}")
        for a, b in zip(w.openings, w.openings[1:]):
            if b.u0 < a.u1 + 3:
                out.append(f"openings: {a.id} and {b.id} overlap")
    for base in bases:
        walls = [w for w in house.walls if w.base == base]
        lines = {w.id: LineString([w.start, w.end]) for w in walls}
        for i, a in enumerate(walls):
            for b in walls[i + 1:]:
                la, lb = lines[a.id], lines[b.id]
                if la.crosses(lb) and min(la.project(la.intersection(lb)), la.length - la.project(la.intersection(lb)),
                                          lb.project(la.intersection(lb)), lb.length - lb.project(la.intersection(lb))) > 3:
                    out.append(f"walls: {a.id} and {b.id} cross")
                elif la.buffer(1.0).intersection(lb).length > 12:
                    out.append(f"walls: {a.id} and {b.id} lie along each other")
        _, rooms, _, _, reached = rooms_of(house, base, house.stair if base > 0 else None)
        if len(reached) < len(rooms):
            out.append(f"rooms: {len(rooms) - len(reached)} of {len(rooms)} rooms on storey {bases.index(base) + 1} cannot be reached")
    floors = [f for f in house.floors if f.role == "floor"]
    if len(bases) > 1 and (not floors or any(not any(o.kind == "stair" for o in f.openings) for f in floors if f.id[2:] == "")):
        out.append("stair: a floor has no stair opening")
    for w in house.walls:
        if w.id[1] not in "sp":           # a junction wall's top is its own mass's roof, at the roof's edge
            continue
        for u in (w.length * k / 6 for k in range(1, 6)):
            x, y, _ = w.world(u, 0, 0)
            over = [r.height(x, y) for r in house.roofs if inside(r.local((x, y, r.height(x, y)))[:2], r.outline_uv)]
            if over and w.base + top_over(w, u - 0.5, u + 0.5) > max(over) + 0.5:
                out.append(f"roof: wall {w.id} stands through the roof")
                break
    ground = [w for w in house.walls if w.base == 0 and w.role == "exterior"]
    if ground:
        plan = unary_union(list(polygonize(unary_union([LineString([w.start, w.end]) for w in ground]))))
        roofs = unary_union([Polygon([r.world(u, v, 0)[:2] for u, v in r.outline]).buffer(0.5) for r in house.roofs])
        bare = plan.difference(roofs).area / 144
        if bare > 3:
            out.append(f"roof: {bare:.0f} sq ft of the house has no roof over it")
        hull = unary_union([Point(p) for w in house.walls for p in (w.start, w.end)]).convex_hull
        beyond = max(Point(r.world(u, v, 0)[:2]).distance(hull) for r in house.roofs for u, v in r.outline)
        if beyond > 30:
            out.append(f"roof: a roof plane runs {beyond / 12:.0f} ft out beyond the walls")
    loose = sum(x[3] for x in unmet(house))
    if loose > 6:
        out.append(f"meeting: {loose:.0f} in. of roof edge meets neither another roof plane nor a wall")
    try:
        td = Takedown(house)
        lost = sum(l.sum for _, l, _ in td.lost) / td.applied.sum
        if lost > LOST:
            where = sorted({s for s, _, _ in td.lost})
            out.append(f"loads: {100 * lost:.0f}% of the load reaches no wall (on {', '.join(where[:6])})")
    except Exception as e:
        out.append(f"loads: the takedown fails ({type(e).__name__}: {e})")
    if framing:
        try:
            errors = build(SEED, house).errors
            if errors:
                out.append(f"framing: {len(errors)} rule error(s) in the seed, first: {errors[0][:110]}")
        except Exception as e:
            out.append(f"framing: the seed fails ({type(e).__name__}: {e})")
    return out
