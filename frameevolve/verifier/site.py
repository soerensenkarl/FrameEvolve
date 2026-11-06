"""The site: everything a check reads about one frame on one house, worked out once, and the words checks share.

A check is a function check(site) -> list of faults. It reads the house's surfaces, the frame's members, the
contact graph (what bears on what, what touches what side by side, and where), which members are held up, the
members on each surface, and how far apart parallel joists and rafters are. It makes a fault at a member with
site.at, or on a surface with site.flag.

Checks read geometry and contacts, never a member's role label: a "stud" is anything upright, a "joist"
anything level with its depth standing up.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from frameevolve.geometry import EPS, Vec, cross, dot, sub, unit
from frameevolve.graph import Graph, build_graph
from frameevolve.model import Frame, House, Member, Surface, Wall
from frameevolve.verifier.report import Fault

SPACINGS = (12.0, 16.0, 19.2, 24.0)   # the IRC span tables' columns; a spacing is read in the next column up


@dataclass
class Site:
    house: House
    frame: Frame
    g: Graph = None
    by_id: dict[str, Member] = field(default_factory=dict)
    surfs: dict[str, Surface] = field(default_factory=dict)
    held: set[str] = field(default_factory=set)      # members with a chain of support to the ground
    on: dict[str, list[Member]] = field(default_factory=dict)     # surface id -> its members
    gaps: dict[str, float] = field(default_factory=dict)          # member id -> spacing to its neighbours, o.c.

    def __post_init__(self):
        from frameevolve.verifier.physical import supported
        self.g = build_graph(self.frame.members)
        self.by_id = {m.id: m for m in self.frame.members}
        self.surfs = {x.id: x for x in self.house.surfaces}
        self.held = supported(self.g, self.by_id)
        for m in self.frame.members:
            self.on.setdefault(m.surface, []).append(m)
        for sid, ms in self.on.items():
            if not isinstance(self.surfs.get(sid), Wall):
                self.gaps.update(spacings(ms))

    def at(self, m: Member, p: Vec, check: str, hard: bool, message: str, others=()) -> Fault:
        """A fault at world point p on member m (and others involved), located on m's surface for drawing."""
        w = self.surfs.get(m.surface)
        u, v = w.local(p)[:2] if w else (None, None)
        ms = [m, *others]
        return Fault(check, hard, message, m.surface or None, u, v, p, [x.id for x in ms], sorted({x.rule for x in ms}))

    def flag(self, check: str, hard: bool, message: str, surface: str, u: float, v: float, members=(),
             rules=()) -> Fault:
        """A fault on a surface at u, v rather than at one member."""
        x = self.surfs.get(surface)
        return Fault(check, hard, message, surface, u, v, x.world(u, v, 0) if x else None, list(members), list(rules))

    def point(self, m: Member, t: float) -> Vec:
        """The point t along m's centreline from its start."""
        a = axis(m)
        return tuple(m.start[k] + a[k] * t for k in range(3))


# ------------------------------------------------------------------------------- words the checks share

def name(m: Member) -> str:
    return f"{m.id} ({m.role or m.rule})"


def axis(m: Member) -> Vec:
    return unit(sub(m.end, m.start))


def vertical(m: Member) -> bool:
    """Upright: a stud, a post."""
    return abs(axis(m)[2]) > 0.9


def level(m: Member) -> bool:
    return abs(axis(m)[2]) < 0.05


def on_edge(m: Member) -> bool:
    """Its depth stands upright: a joist, a header, not a plate laid flat."""
    return abs(m.up[2]) > 0.9


def nominal(m: Member) -> int:
    """The nominal depth: 12 for a 2x12."""
    return int(m.section.split("x")[1])


def along(m: Member, p: Vec) -> float:
    """How far along m from its start a point is."""
    return dot(sub(p, m.start), axis(m))


def supports(s: Site, m: Member) -> list[float]:
    """Where along m it rests on something, from the contact graph."""
    return sorted(along(m, s.g.at[(m.id, n)]) for n in s.g.bears[m.id])


def column(spacing: float | None) -> float | None:
    """The span table column a spacing falls in: the next one up; None past 24". No neighbour: 24"."""
    if spacing is None:
        return SPACINGS[-1]
    return next((c for c in SPACINGS if spacing <= c + 0.5), None)


def spacings(ms: list[Member]) -> dict[str, float]:
    """For each level or sloped member, the larger distance to the nearest parallel member on either side that
    runs alongside it in the same layer, centre to centre. Doubled members (closer than 2") count as one."""
    out = {}
    lines = [(m, axis(m)) for m in ms if not vertical(m)]
    for m, a in lines:
        if abs(dot(a, m.up)) > 0.5:
            continue
        side = unit(cross(a, m.up))
        left = right = None
        for n, b in lines:
            if n is m or abs(dot(a, b)) < 0.99:
                continue
            ts = sorted(dot(sub(p, m.start), a) for p in (n.start, n.end))
            if min(m.length, ts[1]) - max(0.0, ts[0]) < 12.0 or abs(dot(sub(n.start, m.start), m.up)) > m.depth:
                continue        # not alongside, or in another layer
            d = dot(sub(n.start, m.start), side)
            if d > 2.0:
                left = d if left is None else min(left, d)
            elif d < -2.0:
                right = -d if right is None else min(right, -d)
        found = [x for x in (left, right) if x is not None]
        if found:
            out[m.id] = max(found)
    return out


def bearing_wall(s: Site, w: Wall) -> bool:
    """An exterior wall, or one that framing from a floor, ceiling or roof rests on."""
    if w.role == "exterior":
        return True
    return any(not isinstance(s.surfs.get(s.by_id[n].surface), Wall)
               for m in s.on.get(w.id, []) for n in s.g.carries[m.id] if n in s.by_id)


def floors_above(house: House, w: Wall) -> int:
    """How many floors stand over this wall (a ceiling under a roof does not count)."""
    mid = ((w.start[0] + w.end[0]) / 2 + 2 * w.normal[0], (w.start[1] + w.end[1]) / 2 + 2 * w.normal[1])
    return sum(1 for f in house.floors if f.role == "floor" and f.z > w.base + 1 and f.contains(mid))


def stud_range(s: Site, w: Wall) -> tuple[float, float] | None:
    """Where a wall's studs most often start and stop (v), so 'full height' means plate to plate."""
    bs = [w.local_box(m) for m in s.on.get(w.id, []) if vertical(m)]
    if not bs:
        return None
    lo = Counter(round(b.lo[1], 1) for b in bs).most_common(1)[0][0]
    hi = Counter(round(b.hi[1], 1) for b in bs).most_common(1)[0][0]
    return lo, hi


def full_height(s: Site, w: Wall) -> list[Member]:
    """The wall's upright members that run its studs' whole height."""
    r = stud_range(s, w)
    if r is None:
        return []
    return [m for m in s.on.get(w.id, []) if vertical(m)
            and w.local_box(m).lo[1] <= r[0] + 2.0 and w.local_box(m).hi[1] >= r[1] - 2.0 - EPS]
