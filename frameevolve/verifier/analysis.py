"""Will it hold: a simple gravity-load analysis of the frame, by the hand methods an engineer checks a house with.

1. Loads on surfaces. Floors, ceilings and roofs carry area loads (dead, live, snow; pounds per square foot).
   Each level or sloped member on one carries a strip of it, half the way to its neighbours on each side, as a
   line load along its length (along its level run for a rafter: roof loads act on the plan area). A member
   with no neighbour alongside (a block, a band, a ridge, a hip) carries no strip: the framing around it does.
   The dead loads include the framing; a wall's members carry their own weight, and what bears on them.

2. Loads followed down. Members are taken from the top of the frame down, each after everything resting on it.
   A member's loads, its line load and the reactions of the members resting on it where they touch it, go to
   what holds it up as the reactions of simply supported beams: each span between two supports takes its load
   to the supports at its ends, an overhang goes to the support at its end, and what lies over a support goes
   straight into it (a plate laid along a rim joist). Spans run face to face of the supports plus half a
   1 1/2" bearing (NDS 3.2.1). What holds a member up is what it bears on, and, where nothing is under it, the
   side of a member its end butts: a joist in a hanger on a header or rim, a jack rafter on a valley. Where
   several supports touch at once, each takes the load right over it by the width it bears on. Upright
   members pass everything down, split by contact area. A rafter's top against a ridge board stops it bending
   but passes no load there: rafters tied across at their feet lean on each other at the ridge and carry the
   whole roof to their walls (a three-hinged arch; physical.rafters checks the ties), so that share goes to
   the rafter's nearest other support. Members on the ground pass their load out of the frame.

   Every span is cut free and simply supported, so the takedown is statically determinate: no stiffness enters
   it. Continuity over supports is ignored, which errs high on span moments and on overhang reactions. Members
   resting along one another for more than 6" (a rim on a plate) bend together: their sections add.

3. Checks, by NDS allowable stress design, under the ASCE 7 (2.4.1) combinations D + L (CD 1.0), D + S and
   D + 0.75 L + 0.75 S (CD 1.15, snow's two months). The takedown carries dead, live and snow separately (it is
   linear), so each member is checked under each combination, and the one with the highest ratio of stress to
   its allowable governs.
   - strength: bending fb = M / S in joists, rafters, headers and plates against Fb' = Fb CF Cr CD (Cfu for a
     plate laid flat), M the peak over each span and overhang; compression fc = P / A in studs and posts
     against Fc' = Fc CF CD CP, CP the column stability factor for buckling across the wall over the member's
     whole length (sheathing braces the other way). A plate laid flat on floor framing sits on the subfloor,
     which spreads its load to the joists: it is not checked in bending.
   - crushing: the largest reaction where a member bears on another, over the contact area, against Fc-perp
     times the bearing area factor Cb of each member pressed across its grain (NDS 3.10.4). End grain on end
     grain (a stud on a stud) crushes nothing.
   - deflection: each span of a joist, rafter or beam on edge, from the uniform load that gives the same peak
     moment (exact for a uniform load, 25% high for one load at mid-span): live load for floors, ceilings and
     roofs, the whole load for beams in walls.

Not modelled: wind and uplift, lateral loads, bending in studs, shear, connections, the foundation.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import NamedTuple

from frameevolve.geometry import EPS, Vec, cross, dot, sub
from frameevolve.graph import GROUND
from frameevolve.model import Floor, Member, Roof, Wall
from frameevolve.units import ftin, inches
from frameevolve.verifier.report import Fault
from frameevolve.verifier.site import Site, along, axis, level, name, nominal, vertical

PSF = 1 / 144            # pounds per square foot to pounds per square inch

# Area loads (dead, live, snow), psf. IRC Table R301.5: floors 40 live; attics without storage 10 live. ASCE 7
# dead loads for light framing with finishes: floors 10, ceilings 5, roofs 15 (shingles, sheathing, rafters).
# Snow, ASCE 7 ch. 7: flat-roof snow 0.7 x 40 psf ground snow (Cambridge, MA) = 28, taken as 30, on the plan area.
FLOOR_LOAD = (10.0, 40.0, 0.0)
CEILING_LOAD = (5.0, 10.0, 0.0)
ROOF_LOAD = (15.0, 0.0, 30.0)
DENSITY = 26 / 1728      # Spruce-Pine-Fir, about 26 lb per cubic foot, in lb per cubic inch
STRIP = 24.0             # no member carries more than half this past each side: the widest table spacing, inches

# NDS Supplement Table 4A, Spruce-Pine-Fir No. 2, psi.
FB = 875.0               # bending
FC = 1150.0              # compression parallel to grain
FC_PERP = 425.0          # compression perpendicular to grain (bearing); CD does not apply
# NDS 3.10.4 bearing area factor: a bearing shorter than 6" along the member pressed, at least 3" from its end,
# allows Cb = (lb + 0.375) / lb more (a stud on a plate: 1.25); otherwise 1.0.
CB_SHORT = 6.0
CB_END = 3.0
CB_ADD = 0.375
E = 1_400_000.0          # modulus of elasticity, for deflection
E_MIN = 510_000.0        # for stability (buckling)
# Size factors by nominal depth, and the flat use factor Cfu for a member bending about its weak axis.
CF_BENDING = {4: 1.5, 6: 1.3, 8: 1.2, 10: 1.1, 12: 1.0}
CF_COMPRESSION = {4: 1.15, 6: 1.1, 8: 1.05, 10: 1.0, 12: 1.0}
CF_FLAT = {4: 1.1, 6: 1.15, 8: 1.15, 10: 1.2, 12: 1.2}
CR = 1.15                # NDS 4.3.9 repetitive member factor: three or more, no more than 24" apart
REPETITIVE = 24.5        # the spacing up to which Cr applies, inches
C_SAWN = 0.8             # NDS 3.7.1: c for sawn lumber in the column stability factor

# Load combinations (ASCE 7 2.4.1, ASD): weights on (dead, live, snow) and the load duration factor CD.
COMBOS = (("D + L", (1.0, 1.0, 0.0), 1.0), ("D + S", (1.0, 0.0, 1.0), 1.15),
          ("D + 0.75 L + 0.75 S", (1.0, 0.75, 0.75), 1.15))
LIVE = ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.75, 0.75))   # the same, without the dead load, for sag

# IRC Table R301.7 deflection limits: span / k, for live load unless noted.
SAG_FLOOR = 360          # floor joists
SAG_CEILING = 240        # ceiling joists
SAG_ROOF = 180           # rafters, on their level span
SAG_BEAM = 240           # beams and headers in walls, under the whole load

NEAR = 1.0               # contacts closer than this along a member act as one support, inches
MIN_BEARING = 1.5        # IRC R502.6: the bearing a joist or beam needs; spans run to half of it past each face
LONG = 6.0               # a member resting along another for longer than this bends with it


class Load(NamedTuple):
    """Dead, live and snow parts of a load (lb, or lb per inch for a line load)."""
    dead: float = 0.0
    live: float = 0.0
    snow: float = 0.0

    def __add__(self, o: "Load") -> "Load":
        return Load(self.dead + o.dead, self.live + o.live, self.snow + o.snow)

    def __mul__(self, k: float) -> "Load":
        return Load(self.dead * k, self.live * k, self.snow * k)

    def under(self, weights) -> float:
        return self.dead * weights[0] + self.live * weights[1] + self.snow * weights[2]

    @property
    def sum(self) -> float:
        """Dead, live and snow together, unfactored."""
        return self.dead + self.live + self.snow


NONE = Load()


def total(loads) -> Load:
    out = NONE
    for x in loads:
        out = out + x
    return out


# ------------------------------------------------------------------------------- 1. loads on surfaces

def area_load(s: Site, m: Member) -> Load:
    """The area load (psi) on the floor, ceiling or roof a level or sloped member frames; none in a wall."""
    w = s.surfs.get(m.surface)
    if vertical(m) or isinstance(w, Wall) or w is None:
        return NONE
    psf = ROOF_LOAD if isinstance(w, Roof) else CEILING_LOAD if w.role == "ceiling" else FLOOR_LOAD
    return Load(*psf) * PSF


def plies(s: Site, m: Member) -> int:
    """How many members lie face to face here along most of m's length, m included: a doubled trimmer is 2."""
    a = axis(m)
    return 1 + sum(1 for n, area in s.g.side[m.id].items()
                   if s.by_id[n].surface == m.surface and abs(dot(a, axis(s.by_id[n]))) > 0.99
                   and abs(dot(s.g.facing[(m.id, n)], a)) < 0.1 and area >= m.length * m.depth / 2)


def strips(s: Site) -> dict[str, float]:
    """The width of surface each level or sloped member carries: half the way to the nearest parallel member
    alongside it in the same layer on each side, at most STRIP / 2 a side (no span table spaces framing wider;
    wider is an opening or an edge), nothing past an edge. A member with no such neighbour (a block, a band
    across the joist ends, a ridge or hip) carries none: the framing around it carries the surface. Doubled
    members (closer than 2") count as one and share their strip."""
    out = {}
    for sid, ms in s.on.items():
        if isinstance(s.surfs.get(sid), Wall):
            continue
        lines = [(m, axis(m)) for m in ms if not vertical(m)]
        for m, a in lines:
            side, near = cross(a, m.up), {1: None, -1: None}
            for n, b in lines:
                if n is m or abs(dot(a, b)) < 0.99:
                    continue
                ts = sorted(dot(sub(p, m.start), a) for p in (n.start, n.end))
                if min(m.length, ts[1]) - max(0.0, ts[0]) < 12.0 or abs(dot(sub(n.start, m.start), m.up)) > m.depth:
                    continue
                d = dot(sub(n.start, m.start), side)
                if abs(d) > 2.0:
                    k = 1 if d > 0 else -1
                    near[k] = abs(d) if near[k] is None else min(near[k], abs(d))
            out[m.id] = sum(min(d, STRIP) / 2 for d in near.values() if d is not None) / plies(s, m)
    return out


def line_load(s: Site, m: Member, run: float, strip: float) -> Load:
    """m's own load per inch of its level run (all of it, for an upright one): its strip of the floor, ceiling or
    roof it frames, or else its own weight."""
    q = area_load(s, m)
    if q != NONE:
        return q * strip        # the surface's dead load includes its framing
    return Load(DENSITY * m.width * m.depth * (1 / run if run > EPS else m.length))


# ------------------------------------------------------------------------------- 2. loads followed down

@dataclass
class Support:
    """Something holding a member up, over lo..hi along the member's level run (a point when lo == hi)."""
    n: str
    lo: float
    hi: float
    area: float
    bearing: bool          # m rests on it; else m's end hangs from its side
    passes: bool = True    # it takes load (a ridge board a rafter leans on does not)


@dataclass
class Piece:
    """A stretch of a member between supports: a span, an overhang past its end support, or a stretch resting
    on a long bearing; with its line load and the point loads on it (x from the member's start)."""
    kind: str              # "span", "overhang", "rest"
    x0: float
    x1: float
    w: Load
    points: list[tuple[float, Load]]
    left: int | None       # index of the support group at each end
    right: int | None


@dataclass
class Beam:
    """One member in the takedown: its level run, its loads, its supports, and what it passes to each."""
    m: Member
    run: float             # level length per unit of length (1 for a joist, 0 for a stud)
    length: float          # level run (for a stud, its length)
    w: Load
    supports: list[Support]
    points: list[tuple[float, Load]] = field(default_factory=list)
    groups: list[list[Support]] = field(default_factory=list)
    pieces: list[Piece] = field(default_factory=list)
    reactions: dict[str, Load] = field(default_factory=dict)
    riders: list[Member] = field(default_factory=list)    # members resting along it, which bend with it

    @property
    def load(self) -> Load:
        own = self.w * (self.length if self.run > EPS else 1.0)
        return own + total(p for _, p in self.points)

    def x(self, p: Vec) -> float:
        """Where a point falls along the level run."""
        return min(max(along(self.m, p) * self.run, 0.0), self.length)

    def world(self, x: float) -> Vec:
        t = x / self.run if self.run > EPS else 0.0
        a, m = axis(self.m), self.m
        return tuple(m.start[k] + a[k] * t for k in range(3))


def run_of(m: Member) -> float:
    a = axis(m)
    return 0.0 if vertical(m) else math.hypot(a[0], a[1])


def deep(m: Member) -> bool:
    """Its depth stands in the upright plane through its axis: a joist, header or rafter, not a plate laid flat."""
    return abs(cross(axis(m), m.up)[2]) < 0.1


def hangs(s: Site, m: Member, n: str) -> bool:
    """m's end butts the side of n, which does not run on in line with it: a joist in a hanger at a header or
    rim, a rafter at a ridge, a jack rafter on a hip or valley."""
    o = s.by_id[n]
    if n in s.g.bears[m.id] or vertical(m) or (level(m) and not level(o) and not vertical(o)):
        return False      # nor does a level member hang from a sloped one (a ceiling joist nailed to a valley)
    a, t = axis(m), along(m, s.g.at[(m.id, n)])
    near_end = min(t, m.length - t) <= max(m.depth, 3.0)
    return near_end and abs(dot(s.g.facing[(m.id, n)], a)) > 0.5 and abs(dot(a, axis(o))) < 0.95


def leans(s: Site, m: Member, n: str) -> bool:
    """A sloped member's upper end against a level one: a rafter at a ridge board. Rafters tied across at their
    feet lean on each other there (a three-hinged arch) and carry the whole roof to their walls; physical.rafters
    checks the ties."""
    a, t = axis(m), along(m, s.g.at[(m.id, n)])
    return run_of(m) < 0.99 and level(s.by_id[n]) and (t > m.length / 2) == (a[2] > 0)


def extent(s: Site, b: "Beam", n: str, area: float) -> tuple[float, float]:
    """Where along b's level run it rests on n: from the two boxes for square members, else the contact's
    length (its area over b's bearing face) around its middle."""
    m, o = b.m, s.by_id[n]
    if m.aligned and o.aligned and b.run > EPS:
        k = max(range(3), key=lambda j: abs(axis(m)[j]))
        ends = [list(m.start), list(m.start)]
        ends[0][k], ends[1][k] = max(m.box.lo[k], o.box.lo[k]), min(m.box.hi[k], o.box.hi[k])
        x0, x1 = sorted(b.x(tuple(e)) for e in ends)
        return x0, x1
    x = b.x(s.g.at[(m.id, n)])
    half = area / (m.width if deep(m) else m.depth) / 2 * b.run
    return max(x - half, 0.0), min(x + half, b.length)


def supports_of(s: Site, b: "Beam") -> list[Support]:
    m, out = b.m, []
    for n, area in s.g.bears[m.id].items():
        lo, hi = (0.0, b.length) if n == GROUND else extent(s, b, n, area)
        out.append(Support(n, lo, hi, area, True))
    for n, area in s.g.side[m.id].items():
        if hangs(s, m, n):
            x = b.x(s.g.at[(m.id, n)])
            out.append(Support(n, x, x, area, False, not leans(s, m, n)))
    return sorted(out, key=lambda x: x.lo)


def beams(s: Site) -> dict[str, Beam]:
    """Every member as a beam with its loads and supports."""
    out, strip = {}, strips(s)
    for m in s.frame.members:
        run = run_of(m)
        b = Beam(m, run, m.length * run if run > EPS else m.length, line_load(s, m, run, strip.get(m.id, 0.0)), [])
        b.supports = supports_of(s, b)
        out[m.id] = b
    return out


def top_down(bs: dict[str, Beam]) -> list[Beam]:
    """The beams in an order where each comes after everything that rests on it (cycles broken highest first)."""
    below = {mid: {x.n for x in b.supports if x.passes and x.n in bs} for mid, b in bs.items()}
    resting = {mid: 0 for mid in bs}
    for ns in below.values():
        for n in ns:
            resting[n] += 1
    ready = [mid for mid, k in resting.items() if k == 0]
    order, done = [], set()
    while len(order) < len(bs):
        if not ready:
            ready = [max((mid for mid in bs if mid not in done), key=lambda mid: bs[mid].m.box.hi[2])]
        mid = ready.pop()
        if mid in done:
            continue
        done.add(mid)
        order.append(bs[mid])
        for n in below[mid]:
            resting[n] -= 1
            if resting[n] == 0 and n not in done:
                ready.append(n)
    return order


def group(supports: list[Support]) -> list[list[Support]]:
    """Supports that overlap or lie within NEAR of each other act as one; where something is under the member,
    a hanger there carries nothing."""
    out: list[list[Support]] = []
    for x in supports:
        if out and x.lo <= max(y.hi for y in out[-1]) + NEAR:
            out[-1].append(x)
        else:
            out.append([x])
    return [[x for x in g if x.bearing] or g for g in out]


def faces(g: list[Support]) -> tuple[float, float]:
    """Where a group's spans end on either side: NDS 3.2.1, face to face of the supports plus half the bearing
    a member needs (1 1/2") at each; what lies between rests on the support."""
    lo, hi = min(x.lo for x in g), max(x.hi for x in g)
    inset = min(MIN_BEARING / 2, (hi - lo) / 2)
    return lo + inset, hi - inset


def cut(b: Beam) -> None:
    """Cut a member at its supports into overhangs, spans and stretches resting on a support."""
    b.groups = group(b.supports)
    where = [faces(g) for g in b.groups]
    edges = [(0.0, where[0][0], "overhang", None, 0)]
    for i, (lo, hi) in enumerate(where):
        if hi > lo:
            edges.append((lo, hi, "rest", i, i))
        if i + 1 < len(where):
            edges.append((hi, where[i + 1][0], "span", i, i + 1))
    edges.append((where[-1][1], b.length, "overhang", len(where) - 1, None))
    edges = [e for e in edges if e[1] - e[0] > EPS or e[2] == "span"]
    starts = [e[0] for e in edges]
    found = [[] for _ in edges]
    for x, p in b.points:
        found[max(bisect_right(starts, x) - 1, 0)].append((x, p))
    b.pieces = [Piece(kind, x0, x1, b.w, pts, l, r) for (x0, x1, kind, l, r), pts in zip(edges, found)]


def ends(p: Piece) -> tuple[Load, Load]:
    """What a span passes to the supports at its left and right ends, as a simply supported beam."""
    l = p.x1 - p.x0
    load = p.w * l + total(q for _, q in p.points)
    if l <= EPS:
        return load * 0.5, load * 0.5
    right = p.w * (l / 2) + total(q * ((x - p.x0) / l) for x, q in p.points)
    return load + right * -1, right


def shares(b: Beam) -> list[list[tuple[float | None, Load]]]:
    """For each support group, the loads it takes and where along the member they arrive (None: a span's end
    reaction, which the whole group takes, as one bearing: a header end on two jacks bears on both)."""
    got = [[] for _ in b.groups]
    for p in b.pieces:
        if p.kind == "span":
            left, right = ends(p)
            got[p.left].append((None, left))
            got[p.right].append((None, right))
            continue
        i = p.left if p.left is not None else p.right
        if p.kind == "overhang":
            got[i].append((p.x1 if p.left is None else p.x0, p.w * (p.x1 - p.x0) + total(q for _, q in p.points)))
            continue
        k = max(1, math.ceil((p.x1 - p.x0) / 12))       # resting: the line load arrives along it, a foot at a time
        got[i] += [(p.x0 + (j + 0.5) * (p.x1 - p.x0) / k, p.w * ((p.x1 - p.x0) / k)) for j in range(k)] + p.points
    return got


def under(g: list[Support], x: float | None) -> list[tuple[Support, float]]:
    """The supports of a group that take a load at x, and their shares: those right under it, by the width
    they bear on (contact area over length); else the nearest. x None: every support of the group, by its
    contact area (a span's end reaction on the group as one bearing)."""
    ok = [y for y in g if y.passes]
    if x is None:
        whole = sum(y.area for y in ok)
        return [(y, y.area / whole) for y in ok] if whole > 0 else [(y, 1 / len(ok)) for y in ok]
    over = [y for y in ok if y.lo - EPS <= x <= y.hi + EPS] or [min(ok, key=lambda y: min(abs(x - y.lo), abs(x - y.hi)))]
    width = [y.area / (y.hi - y.lo) if y.hi - y.lo > EPS else y.area for y in over]
    whole = sum(width)
    return [(y, k / whole) for y, k in zip(over, width)]


def pass_down(b: Beam, arriving: dict[str, list[tuple[Vec, Load]]]) -> None:
    """Split b's load among what holds it up, and add it to what each of those carries."""
    b.points = [(b.x(p), q) for p, q in arriving.get(b.m.id, [])]
    if not b.supports or not any(x.passes for x in b.supports):
        return
    if b.run <= EPS:              # upright: everything goes down, split by contact area
        b.groups = [b.supports]
        got = [[(None, b.load)]]
    else:
        cut(b)
        got = shares(b)
    takers = [i for i, g in enumerate(b.groups) if any(x.passes for x in g)]
    for i, g in enumerate(b.groups):
        if i not in takers:       # a ridge board's share goes to the nearest support that takes load
            mid = (g[0].lo + g[-1].hi) / 2
            j = min(takers, key=lambda j: abs((b.groups[j][0].lo + b.groups[j][-1].hi) / 2 - mid))
            got[j] += got[i]
    for i in takers:
        for x, q in got[i]:
            for y, share in under(b.groups[i], x):
                b.reactions[y.n] = b.reactions.get(y.n, NONE) + q * share
                if y.n != GROUND:
                    at = (y.lo + y.hi) / 2 if x is None else min(max(x, y.lo), y.hi)
                    arriving.setdefault(y.n, []).append((b.world(at), q * share))


def takedown(s: Site) -> dict[str, Beam]:
    """Every member's loads and reactions, followed from the top of the frame to the ground."""
    bs = beams(s)
    arriving: dict[str, list[tuple[Vec, Load]]] = {}
    for b in top_down(bs):
        pass_down(b, arriving)
        for x in b.supports:
            if x.n in bs and x.hi - x.lo > LONG and abs(dot(axis(b.m), axis(bs[x.n].m))) > 0.99:
                bs[x.n].riders.append(b.m)
    return bs


# ------------------------------------------------------------------------------- 3. checks

def peak_moment(p: Piece, weights) -> tuple[float, float]:
    """The largest bending moment in a piece (in-lb) and where it is, for one combination of loads."""
    w = p.w.under(weights)
    pts = sorted((x - p.x0, q.under(weights)) for x, q in p.points)
    l = p.x1 - p.x0
    if p.kind == "rest" or l <= EPS:
        return 0.0, p.x0
    if p.kind == "overhang":      # a cantilever from its support
        root = p.x1 if p.left is None else p.x0
        return w * l * l / 2 + sum(q * abs(p.x0 + x - root) for x, q in pts), root
    ra = w * l / 2 + sum(q * (l - x) / l for x, q in pts)

    def m_at(x):
        return ra * x - w * x * x / 2 - sum(q * (x - a) for a, q in pts if a < x)
    best = (0.0, l / 2)
    marks = [0.0] + [x for x, _ in pts] + [l]
    passed = 0.0
    for i in range(len(marks) - 1):
        a, c = marks[i], marks[i + 1]
        if i > 0:
            passed += pts[i - 1][1]
        candidates = [a, c]
        if w > 0:
            z = (ra - passed) / w
            if a < z < c:
                candidates.append(z)
        for x in candidates:
            best = max(best, (m_at(x), x))
    return best[0], p.x0 + best[1]


def section(m: Member) -> tuple[float, float]:
    """Section modulus S and moment of inertia I about the axis gravity bends m about."""
    b, d = (m.width, m.depth) if deep(m) else (m.depth, m.width)
    return b * d * d / 6, b * d ** 3 / 12


def stiffened(b: Beam) -> tuple[float, float]:
    """S and I of a member with the members resting along it (a rim on a plate, a doubled top plate): they bend
    together."""
    ss = [section(m) for m in [b.m, *b.riders]]
    return sum(x for x, _ in ss), sum(y for _, y in ss)


def bending_allowed(s: Site, m: Member, cd: float) -> float:
    k = nominal(m)
    f = FB * CF_BENDING[k] * cd
    if not deep(m):
        f *= CF_FLAT[k]
    if not isinstance(s.surfs.get(m.surface), Wall) and (s.gaps.get(m.id) or 99) <= REPETITIVE:
        f *= CR
    return f


def compression_allowed(m: Member, cd: float) -> float:
    """Fc' = Fc CF CD CP, buckling over the member's length across its depth (NDS 3.7.1)."""
    fc = FC * CF_COMPRESSION[nominal(m)] * cd
    fce = 0.822 * E_MIN / (m.length / m.depth) ** 2
    a = fce / fc
    h = (1 + a) / (2 * C_SAWN)
    return fc * (h - math.sqrt(h * h - a / C_SAWN))


def on_subfloor(s: Site, b: Beam) -> bool:
    """A plate laid flat on floor framing: the subfloor under it spreads its load to the joists."""
    rests = [x.n for x in b.supports if x.bearing]
    return (not deep(b.m) and bool(rests) and all(x != GROUND and isinstance(s.surfs.get(s.by_id[x].surface), Floor)
                                                  and s.surfs[s.by_id[x].surface].role == "floor" for x in rests))


def lb(x: float) -> str:
    return f"{x:,.0f} lb"


def strength(s: Site, b: Beam) -> Fault | None:
    """Bending in a level or sloped member, compression and buckling in an upright one: the worse combination."""
    m = b.m
    if b.run > EPS and on_subfloor(s, b):
        return None
    worst = None
    for label, weights, cd in COMBOS:
        if b.run <= EPS:
            p = b.load.under(weights)
            stress, allowed, x = p / (m.width * m.depth), compression_allowed(m, cd), 0.0
        else:
            moments = [peak_moment(p, weights) for p in b.pieces]
            mx, x = max(moments, default=(0.0, 0.0))
            stress, allowed = mx / stiffened(b)[0], bending_allowed(s, m, cd)
        if worst is None or stress / allowed > worst[0]:
            worst = (stress / allowed, stress, allowed, x, label, b.load.under(weights))
    ratio, stress, allowed, x, label, carried = worst
    if ratio <= 1.0:
        return None
    if b.run <= EPS:
        what = (f"compression {stress:,.0f} psi, allowed {allowed:,.0f} psi for a {m.section} SPF No. 2 "
                f"{ftin(m.length)} long (buckling across the wall)")
        at = min(m.start, m.end, key=lambda p: p[2])
    else:
        what = f"bending {stress:,.0f} psi, allowed {allowed:,.0f} psi for a {m.section} SPF No. 2"
        if b.riders:   # say that the plies resting on it were counted: they bend with it
            what += (f", with {', '.join(r.id for r in b.riders)} resting along it and bending with it "
                     f"({1 + len(b.riders)} plies together)")
        at = b.world(x)
    return s.at(m, at, "strength", True, f"{name(m)} carries {lb(carried)} ({label}); {what}")


def bearing(s: Site, p: Member, m: Member, n: Member, area: float) -> tuple[float, float]:
    """How long the bearing between m (on top) and n is along member p, one of the two, and how far it stops
    short of p's nearer end: from the boxes for square members, else the contact's area over p's face."""
    if m.aligned and n.aligned:
        k = max(range(3), key=lambda j: abs(axis(p)[j]))
        lo, hi = max(m.box.lo[k], n.box.lo[k]), min(m.box.hi[k], n.box.hi[k])
        return hi - lo, min(lo - p.box.lo[k], p.box.hi[k] - hi)
    t, lb = along(p, s.g.at[(m.id, n.id)]), area / (p.width if deep(p) else p.depth)
    return lb, min(t, p.length - t) - lb / 2


def bearing_factor(s: Site, p: Member, m: Member, n: Member, area: float) -> float:
    """NDS 3.10.4: Cb for member p, pressed across its grain where m bears on n."""
    lb, end = bearing(s, p, m, n, area)
    return (lb + CB_ADD) / lb if EPS < lb < CB_SHORT and end >= CB_END - EPS else 1.0


def crushing(s: Site, b: Beam) -> Fault | None:
    """The hardest a member presses into one it bears on, against what the member pressed across its grain
    allows (the weaker, when both are)."""
    m = b.m
    worst = None
    for x in b.supports:
        if not x.bearing or x.n == GROUND or x.n not in b.reactions or x.area <= EPS:
            continue
        n = s.by_id[x.n]
        pressed = [p for p in (m, n) if not vertical(p)]
        if not pressed:
            continue
        allowed = FC_PERP * min(bearing_factor(s, p, m, n, x.area) for p in pressed)
        r = max(b.reactions[x.n].under(w) for _, w, _ in COMBOS)
        if worst is None or r / x.area / allowed > worst[0]:
            worst = (r / x.area / allowed, r, x, n, allowed)
    if worst is None or worst[0] <= 1.0:
        return None
    ratio, r, x, n, allowed = worst
    return s.at(m, s.g.at[(m.id, n.id)], "crushing", True,
                f"{name(m)} presses {lb(r)} into {name(n)} over {x.area:.1f} sq in: {r / x.area:,.0f} psi across the "
                f"grain, allowed {allowed:,.0f} psi", [n])


def sag_limit(s: Site, m: Member) -> tuple[int, tuple, str] | None:
    """The span / k a member may sag, the combinations of load it is checked under, and their name."""
    w = s.surfs.get(m.surface)
    if isinstance(w, Wall):
        return SAG_BEAM, [x for _, x, _ in COMBOS], "its whole load"
    if isinstance(w, Roof):
        return SAG_ROOF, LIVE, "snow"
    if isinstance(w, Floor):
        return (SAG_CEILING if w.role == "ceiling" else SAG_FLOOR), LIVE, "live load"
    return None


def deflection(s: Site, b: Beam) -> Fault | None:
    """The span that sags most against its limit, from the uniform load that gives the same peak moment."""
    m = b.m
    rule = sag_limit(s, m)
    if b.run <= EPS or not deep(m) or rule is None:
        return None
    k, weights, what = rule
    inertia = stiffened(b)[1]
    worst = None
    for p in b.pieces:
        l = p.x1 - p.x0
        if p.kind != "span" or l <= EPS:
            continue
        mx = max(peak_moment(p, w)[0] for w in weights)
        sag = 5 * mx * l * l / (48 * E * inertia)
        if worst is None or sag * k / l > worst[0]:
            worst = (sag * k / l, sag, l, p)
    if worst is None or worst[0] <= 1.0:
        return None
    _, sag, l, p = worst
    return s.at(m, b.world((p.x0 + p.x1) / 2), "deflection", False,
                f"{name(m)} sags {inches(sag)} under {what} over a {ftin(l)} span, allowed L/{k} = {inches(l / k)}")


def loads(s: Site) -> list[Fault]:
    """Follow the loads down the frame and check each held member that carries some and has support."""
    out = []
    for b in takedown(s).values():
        if b.m.id not in s.held or not b.supports or b.load.under((1, 1, 1)) <= 0:
            continue
        out += [f for f in (strength(s, b), crushing(s, b), deflection(s, b)) if f]
    return out
