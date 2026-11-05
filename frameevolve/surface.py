"""What a wall's faces see of the frame: where sheathing or drywall would have nothing behind it.

Each wall has two faces: the outer face (its surface, w = 0) and the inner face (w = the framing depth).
Along any height, backing must reach every edge of a face and must not leave more than MAX_CLEAR between
members. Edges are the wall ends, the opening sides, and the sides of any stretch where another wall's
framing sits against the face (a corner or a partition), since the board stops there. Members of other walls
count as backing too, which is how a corner backs the end of the wall that butts into it.
"""
from __future__ import annotations

from collections import Counter

from dataclasses import dataclass

from frameevolve.geometry import EPS
from frameevolve.model import Member, Wall

MAX_CLEAR = 22.5  # 24" stud centres less one 1 1/2" stud


@dataclass(frozen=True)
class Gap:
    u0: float
    u1: float
    v0: float
    v1: float
    kind: str  # "edge": a board edge with nothing behind it; "field": too wide between backing
    face: str = "outer"


def subtract(intervals, cuts):
    out = list(intervals)
    for c0, c1 in cuts:
        nxt = []
        for a, b in out:
            if c1 <= a + EPS or c0 >= b - EPS:
                nxt.append((a, b))
                continue
            if c0 > a + EPS:
                nxt.append((a, c0))
            if c1 < b - EPS:
                nxt.append((c1, b))
        out = nxt
    return out


def depth(wall: Wall, members: list[Member]) -> float | None:
    """The wall's framing depth: how far its own members most often reach in from the surface."""
    reach = Counter(round(b.hi[2], 3) for m in members if m.surface == wall.id
                    for b in [wall.local_box(m.box)] if abs(b.lo[2]) <= EPS)
    return reach.most_common(1)[0][0] if reach else None


def gaps(wall: Wall, members: list[Member], max_clear: float = MAX_CLEAR, face: str = "outer",
         walls: dict[str, Wall] | None = None) -> list[Gap]:
    """walls: every wall of the house by id, needed to stop a face at the walls it meets."""
    L, H = wall.length, wall.height
    f = 0.0 if face == "outer" else depth(wall, members)
    if f is None:
        return []
    out = face == "outer"            # the board is on the -w side of the outer face, the +w side of the inner
    first, last = 0.0, L             # a face inside the house stops at the inner face of the walls it meets
    if (not out or wall.role == "interior") and walls:
        if wall.start_meets in walls:
            first = depth(walls[wall.start_meets], members) or 0.0
        if wall.end_meets in walls:
            last = L - (depth(walls[wall.end_meets], members) or 0.0)
    backing, covered = [], []
    for m in members:
        b = wall.local_box(m.box)
        if b.hi[0] <= EPS or b.lo[0] >= L - EPS or b.hi[1] <= EPS or b.lo[1] >= H - EPS:
            continue
        if abs((b.lo[2] if out else b.hi[2]) - f) <= EPS:
            backing.append(b)
        elif m.surface != wall.id and (b.lo[2] < f - EPS <= b.hi[2] if out else b.lo[2] <= f + EPS < b.hi[2]):
            covered.append(b)        # another wall's framing against or through this face: no board there
    levels = {0.0, H} | {o.v0 for o in wall.openings} | {o.v1 for o in wall.openings}
    levels |= {min(max(v, 0.0), H) for b in backing + covered for v in (b.lo[1], b.hi[1])}
    levels = sorted(levels)
    found: list[Gap] = []
    for h0, h1 in zip(levels, levels[1:]):
        if h1 - h0 <= EPS:
            continue
        vm = (h0 + h1) / 2
        solid = subtract([(first, last)], [(o.u0, o.u1) for o in wall.openings if o.v0 < vm < o.v1]
                         + [(b.lo[0], b.hi[0]) for b in covered if b.lo[1] < vm < b.hi[1]])
        backed = [(b.lo[0], b.hi[0]) for b in backing if b.lo[1] < vm < b.hi[1]]
        for s0, s1 in solid:
            for g0, g1 in subtract([(s0, s1)], backed):
                if g0 <= s0 + EPS or g1 >= s1 - EPS:
                    found.append(Gap(g0, g1, h0, h1, "edge", face))
                elif g1 - g0 > max_clear:
                    found.append(Gap(g0, g1, h0, h1, "field", face))
    merged: list[Gap] = []
    for g in sorted(found, key=lambda g: (g.kind, g.u0, g.u1, g.v0)):
        p = merged[-1] if merged else None
        if p and (p.kind, p.u0, p.u1) == (g.kind, g.u0, g.u1) and abs(p.v1 - g.v0) <= EPS:
            merged[-1] = Gap(p.u0, p.u1, p.v0, g.v1, p.kind, face)
        else:
            merged.append(g)
    return merged
