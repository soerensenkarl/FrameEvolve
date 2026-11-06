"""What a surface's faces see of the frame: where sheathing, subfloor or drywall would have nothing behind it.

Each surface has two faces: the outer face (the surface itself, w = 0: sheathing on a wall, subfloor on a
floor) and the inner face (w = the framing depth: drywall, or a ceiling under a floor). A board needs support
within 24" in at least one direction, as advanced framing allows: a stretch is a fault only if it is wider
than MAX_CLEAR both along u and along v. A board edge (a wall end, an opening side, or where another wall's
framing meets a wall's face) needs backing at least every MAX_EDGE along it, so ladder blocking or clips
will do. Members of other surfaces count as backing, which is how a corner backs the wall butting into it.
"""
from __future__ import annotations

from collections import Counter

from dataclasses import dataclass

from frameevolve.geometry import EPS, dot, scan
from frameevolve.solid import points, section
from frameevolve.model import Member, Wall

MAX_CLEAR = 22.5  # 24" stud centres less one 1 1/2" stud
MAX_EDGE = 24.0   # longest stretch of a board edge with nothing behind it


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


def in_the_way(wall: Wall, other: Wall | None, end: str, members: list[Member]) -> float:
    """How far another wall's framing reaches into this wall's face at an end: its depth if it lies across
    the face's path there, else nothing."""
    if other is None:
        return 0.0
    across = wall.dir[0] * other.normal[0] + wall.dir[1] * other.normal[1]
    return (depth(other, members) or 0.0) if (across > 0 if end == "start" else across < 0) else 0.0


def depth(wall: Wall, members: list[Member]) -> float | None:
    """The wall's framing depth: how far its own members most often reach in from the surface."""
    reach = Counter(round(b.hi[2], 3) for m in members if m.surface == wall.id
                    for b in [wall.local_box(m)] if abs(b.lo[2]) <= EPS)
    return reach.most_common(1)[0][0] if reach else None


def gaps(wall: Wall, members: list[Member], max_clear: float = MAX_CLEAR, face: str = "outer",
         walls: dict[str, Wall] | None = None) -> list[Gap]:
    """`wall` is any surface: a wall, a floor or ceiling, a roof plane. walls: every wall of the house by id,
    needed to stop a wall's face at the walls it meets. Another surface's framing against a wall's face, or
    through any surface's face, leaves no room for a board there."""
    L, H = wall.size
    is_wall = isinstance(wall, Wall)
    f = 0.0 if face == "outer" else depth(wall, members)
    if f is None:
        return []
    out = face == "outer"            # the board is on the -w side of the outer face, the +w side of the inner
    first, last = 0.0, L             # a face inside the house stops at the inner face of the walls it meets
    if is_wall and (not out or wall.role == "interior") and walls:
        first = in_the_way(wall, walls.get(wall.start_meets), "start", members)
        last = L - in_the_way(wall, walls.get(wall.end_meets), "end", members)
    backing, covered = [], []        # polygons in u, v
    for m in members:
        b = wall.local_box(m)
        if b.hi[0] <= EPS or b.lo[0] >= L - EPS or b.hi[1] <= EPS or b.lo[1] >= H - EPS:
            continue
        if b.hi[2] < f - EPS or b.lo[2] > f + EPS:
            continue
        mine = m.surface == wall.id
        if wall.square(m):           # a box square to the surface: its faces are where its box says
            rect = [(b.lo[0], b.lo[1]), (b.hi[0], b.lo[1]), (b.hi[0], b.hi[1]), (b.lo[0], b.hi[1])]
            board = b.lo[2] < f - EPS <= b.hi[2] if out else b.lo[2] <= f + EPS < b.hi[2]
            frame = b.lo[2] <= f + EPS < b.hi[2] if out else b.lo[2] < f - EPS <= b.hi[2]
            if abs((b.lo[2] if out else b.hi[2]) - f) <= EPS:
                backing.append(rect)
            elif not mine and board and (is_wall or frame):
                covered.append(rect)
            continue
        n, d = wall.ew, dot(wall.ew, wall.origin) + f   # anything else: where it crosses the face, just either side
        side = -1 if out else 1
        board = section(m.pieces, n, d + side * EPS)
        frame = section(m.pieces, n, d - side * EPS)
        uv = lambda polys: [[wall.local(q)[:2] for q in poly] for poly in polys]
        if frame and not board:
            backing += uv(frame)
        elif board and not mine and (is_wall or frame):
            covered += uv(board)
    levels = {0.0, H} | {o.v0 for o in wall.openings} | {o.v1 for o in wall.openings} | {v for _, v in wall.outline_uv}
    levels |= {min(max(v, 0.0), H) for poly in backing + covered for _, v in poly}
    levels = sorted(levels)
    found: list[Gap] = []
    for h0, h1 in zip(levels, levels[1:]):
        if h1 - h0 <= EPS:
            continue
        vm = (h0 + h1) / 2
        inside = [(max(a, first), min(b, last)) for a, b in scan(wall.outline_uv, vm) if min(b, last) > max(a, first)]
        solid = subtract(inside, [(o.u0, o.u1) for o in wall.openings if o.v0 < vm < o.v1]
                         + [i for poly in covered for i in scan(poly, vm)])
        backed = [i for poly in backing for i in scan(poly, vm)]
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
    return [g for g in merged if (g.v1 - g.v0 > MAX_EDGE if g.kind == "edge"
                                  else min(g.u1 - g.u0, g.v1 - g.v0) > max_clear)]


def outlines(x, m: Member) -> list[list[tuple[float, float]]]:
    """A member seen square to surface x: one convex outline per piece, in x's u, v (a box square to the
    surface is its rectangle)."""
    if x.square(m):
        b = x.local_box(m)
        return [[(b.lo[0], b.lo[1]), (b.hi[0], b.lo[1]), (b.hi[0], b.hi[1]), (b.lo[0], b.hi[1])]]
    return [hull([x.local(p)[:2] for p in points(piece)]) for piece in m.pieces]


def hull(pts):
    """Convex hull of points in a plane, counter-clockwise."""
    pts = sorted(set((round(u, 6), round(v, 6)) for u, v in pts))
    if len(pts) < 3:
        return pts
    turn = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]
