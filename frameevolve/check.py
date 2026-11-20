"""Is a detailed house a design that could be built? What is wrong with it, in words.

A house from detail.py is made up to fit a real envelope, so nothing guarantees it: every house is checked, and
only one with nothing wrong belongs in a dataset. The checks are of the design, before any framing:

  standing   every wall above the ground floor stands on a floor
  walls      no two walls of a storey cross or lie along each other; none is a sliver
  openings   each lies in its wall clear of the ends, of the other openings and of the walls that meet it, and
             under the wall's top
  rooms      every room of a storey can be reached, through doors, from outside or from the stair
  stair      a house of more than one storey has a stair opening in every floor
  roof       no bearing wall or partition stands through the roof over it
  loads      all the load on the surfaces comes down to the ground (loads.py)

`framing=True` adds whether the seed grammar frames it without a rule error. That is kept apart: the seed is
bare (it cannot yet frame the pointed end of a hip, say), and what it cannot frame is the search's to learn.
"""
from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString

from frameevolve.builder import build
from frameevolve.detail import rooms_of, top_over
from frameevolve.geometry import inside
from frameevolve.loads import Takedown
from frameevolve.model import House

SEED = Path(__file__).resolve().parents[1] / "grammars" / "seed.py"
SLIVER = 12.0      # a wall shorter than this is a fault of the envelope, not a wall
LOST = 0.005       # the share of the load that may go astray


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
    if len(bases) > 1 and (not floors or any(not f.openings for f in floors if f.id[2:] == "")):
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
