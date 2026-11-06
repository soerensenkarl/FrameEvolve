"""The shared data model: houses as labelled surfaces (walls, floors, ceilings, roofs), frames as lists of members.
Inches, z up."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path

from frameevolve import solid
from frameevolve.geometry import EPS, Box, Vec, add, axis_aligned, corners, cross, dot, inside, mul, sub, unit

THICK = 1.5
# nominal name: (actual width, actual depth), inches
SECTIONS = {"2x4": (1.5, 3.5), "2x6": (1.5, 5.5), "2x8": (1.5, 7.25), "2x10": (1.5, 9.25), "2x12": (1.5, 11.25)}
STOCK = (96, 120, 144, 168, 192, 216, 240)   # 8 to 20 ft


@dataclass
class Opening:
    id: str
    kind: str   # "window" or "door"
    u0: float   # along the wall from its start
    u1: float
    v0: float   # up from the wall's base
    v1: float

    @property
    def width(self) -> float:
        return self.u1 - self.u0

    @property
    def height(self) -> float:
        return self.v1 - self.v0


@dataclass
class Tee:
    """Another wall ending against this one along its length: at u, its framing running toward +u (side 1)
    or -u (side -1) from there."""
    wall: str
    u: float
    side: int


@dataclass
class Bearer:
    """A wall under a floor (its top meets the floor) or on it (its base stands on the floor), in the floor's
    coordinates: its surface line from a to b, and side, the direction its framing lies from that line."""
    wall: str
    role: str
    a: tuple[float, float]
    b: tuple[float, float]
    side: tuple[float, float]

    @property
    def along_u(self) -> bool:
        return abs(self.a[1] - self.b[1]) < EPS


class Surface:
    """What every surface shares: local axes eu, ev, ew from an origin, a size along u and v, and an outline in
    u, v. w runs into the framing from the surface. faces: the faces that get boards, "outer" on the surface
    itself and "inner" on the far side of the framing."""
    faces = ("outer", "inner")

    def world(self, u: float, v: float, w: float) -> Vec:
        return add(self.origin, add(mul(self.eu, u), add(mul(self.ev, v), mul(self.ew, w))))

    def local(self, p: Vec) -> Vec:
        q = sub(p, self.origin)
        return (dot(q, self.eu), dot(q, self.ev), dot(q, self.ew))

    def world_dir(self, d: Vec) -> Vec:
        return add(mul(self.eu, d[0]), add(mul(self.ev, d[1]), mul(self.ew, d[2])))

    def local_dir(self, d: Vec) -> Vec:
        return (dot(d, self.eu), dot(d, self.ev), dot(d, self.ew))

    def local_box(self, x) -> Box:
        """A member's (or a world box's) bounding box in this surface's coordinates: lo = (u0, v0, w0),
        hi = (u1, v1, w1). Exact for a member square to the surface."""
        if isinstance(x, Box):
            return Box.around([self.local((a, b, c)) for a in (x.lo[0], x.hi[0])
                               for b in (x.lo[1], x.hi[1]) for c in (x.lo[2], x.hi[2])])
        return Box.around([self.local(p) for p in x.points])

    def square(self, m: "Member") -> bool:
        """True if a plain member's axes run along this surface's axes, so its local box is exact."""
        return m.plain and all(sum(abs(c) > 1e-9 for c in self.local_dir(v)) == 1 for v in (sub(m.end, m.start), m.up))


@dataclass
class Wall(Surface):
    """A wall surface: a vertical plane from start to end in plan. Its framing lies to the left of start to end
    (inward, for a counter-clockwise exterior wall), so the surface is the face of the framing: the outer face
    of an exterior wall, one face of a partition. A wall under a floor reaches up to the floor's top.

    Local coordinates: u along the wall from its start, v up from its base, w into the framing from the surface.
    Junctions (start_meets, end_meets, tees, above, below) are worked out from the geometry when the house is made.
    """
    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    height: float
    base: float = 0.0
    role: str = "exterior"
    openings: list[Opening] = field(default_factory=list)
    start_meets: str | None = None   # the wall this one meets at its start (a corner or a T)
    end_meets: str | None = None     # the wall this one meets at its end
    tees: list[Tee] = field(default_factory=list)   # walls whose end meets this one along its length
    above: str | None = None         # the floor or ceiling resting on this wall's top
    below: str | None = None         # the floor this wall stands on
    outline: list[tuple[float, float]] | None = None   # in u, v, where not a rectangle: a gable wall up to its roof

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def size(self) -> tuple[float, float]:
        return (self.length, max(v for _, v in self.outline) if self.outline else self.height)

    @property
    def outline_uv(self) -> list[tuple[float, float]]:
        if self.outline:
            return [tuple(p) for p in self.outline]
        L, H = self.length, self.height
        return [(0.0, 0.0), (L, 0.0), (L, H), (0.0, H)]

    @property
    def dir(self) -> Vec:
        return unit((self.end[0] - self.start[0], self.end[1] - self.start[1], 0.0))

    @property
    def normal(self) -> Vec:
        """Inward: to the left of start to end, so a counter-clockwise footprint frames inside."""
        d = self.dir
        return (-d[1], d[0], 0.0)

    @property
    def origin(self) -> Vec:
        return (self.start[0], self.start[1], self.base)

    eu = dir
    ev = property(lambda self: (0.0, 0.0, 1.0))
    ew = normal


@dataclass
class Floor(Surface):
    """A floor surface: a horizontal polygon at height z, the top of its framing (the subfloor sits on it). Or,
    with role "ceiling", the ceiling under a roof: z is the underside of its framing (the drywall), on the walls'
    top, and w runs up into the attic framing; only its underside gets boards.

    outline: its plan shape, counter-clockwise. Local coordinates: u along `axis` (x unless turned) and v square
    to it, from the corner of its bounding box in u, v; w into the framing (down for a floor). bearers are the
    walls under it, loads the walls standing on it; both are worked out from the geometry. Openings (stairs)
    are rectangles in u, v.
    """
    id: str
    outline: list[tuple[float, float]]
    z: float
    role: str = "floor"
    openings: list[Opening] = field(default_factory=list)
    bearers: list[Bearer] = field(default_factory=list)
    loads: list[Bearer] = field(default_factory=list)
    axis: tuple[float, float] = (1.0, 0.0)

    def _plan(self, x: float, y: float) -> tuple[float, float]:
        a, b = self.axis
        return (x * a + y * b, -x * b + y * a)

    @property
    def _box(self) -> tuple[float, float, float, float]:
        us, vs = zip(*(self._plan(*p) for p in self.outline))
        return min(us), min(vs), max(us), max(vs)

    @property
    def length(self) -> float:
        """Bounding box extent along u."""
        u0, _, u1, _ = self._box
        return u1 - u0

    @property
    def width(self) -> float:
        """Bounding box extent along v."""
        _, v0, _, v1 = self._box
        return v1 - v0

    @property
    def size(self) -> tuple[float, float]:
        return (self.length, self.width)

    @property
    def outline_uv(self) -> list[tuple[float, float]]:
        u0, v0, _, _ = self._box
        return [(u - u0, v - v0) for u, v in (self._plan(*p) for p in self.outline)]

    @property
    def origin(self) -> Vec:
        u0, v0, _, _ = self._box
        a, b = self.axis
        return (u0 * a - v0 * b, u0 * b + v0 * a, self.z)

    eu = property(lambda self: (self.axis[0], self.axis[1], 0.0))
    ev = property(lambda self: (-self.axis[1], self.axis[0], 0.0))
    ew = property(lambda self: (0.0, 0.0, 1.0 if self.role == "ceiling" else -1.0))
    faces = property(lambda self: ("outer",) if self.role == "ceiling" else ("outer", "inner"))

    def contains(self, p: tuple[float, float]) -> bool:
        return inside(p, self.outline)


@dataclass
class Seam:
    """Where this roof plane meets another along an edge of its outline: a ridge (level, at the top of both),
    or a hip or valley (sloped). a, b: the edge in this plane's u, v."""
    other: str
    a: tuple[float, float]
    b: tuple[float, float]
    kind: str


@dataclass
class Roof(Surface):
    """A roof plane: the top of its rafters, where the sheathing sits. Its eave line runs level from start to end
    in plan at height z (the outer edge of the overhang); the plane rises to the left of that line at pitch
    inches per 12.

    Local coordinates: u along the eave from its start, v up the slope from the eave line (in the plane), w into
    the framing, square to the plane. outline: the plane's shape in u, v. seams: the edges it shares with other
    roof planes, worked out from the geometry; each seam is listed on the plane with the lower id.
    """
    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    z: float
    pitch: float
    outline: list[tuple[float, float]]
    role: str = "roof"
    openings: list[Opening] = field(default_factory=list)
    seams: list[Seam] = field(default_factory=list)
    faces = ("outer",)

    @property
    def slope(self) -> float:
        return self.pitch / 12

    @property
    def outline_uv(self) -> list[tuple[float, float]]:
        return [tuple(p) for p in self.outline]

    @property
    def size(self) -> tuple[float, float]:
        return (max(u for u, _ in self.outline), max(v for _, v in self.outline))

    @property
    def origin(self) -> Vec:
        return (self.start[0], self.start[1], self.z)

    @property
    def eu(self) -> Vec:
        return unit((self.end[0] - self.start[0], self.end[1] - self.start[1], 0.0))

    @property
    def ev(self) -> Vec:
        e = self.eu
        return unit((-e[1], e[0], self.slope))

    @property
    def ew(self) -> Vec:
        return cross(self.ev, self.eu)

    def height(self, x: float, y: float) -> float:
        """The plane's height over a point in plan."""
        e = self.eu
        run = (x - self.start[0]) * -e[1] + (y - self.start[1]) * e[0]
        return self.z + run * self.slope


def _shared(r: "Roof", a, b, q: "Roof", c, d) -> "Seam | None":
    """The stretch where edge a-b of roof plane r lies along edge c-d of roof plane q, as a seam on r: a ridge if
    level, a hip where the planes fall away from it, a valley where they rise from it."""
    pa, pb = r.world(*a, 0), r.world(*b, 0)
    if math.dist(pa, pb) < EPS:
        return None
    e = unit(sub(pb, pa))
    off = lambda p: math.dist(p, add(pa, mul(e, dot(sub(p, pa), e))))
    pc, pd = q.world(*c, 0), q.world(*d, 0)
    if off(pc) > EPS or off(pd) > EPS:
        return None
    L = math.dist(pa, pb)
    t0, t1 = sorted((dot(sub(pc, pa), e), dot(sub(pd, pa), e)))
    t0, t1 = max(t0, 0.0), min(t1, L)
    if t1 - t0 <= EPS:
        return None
    ends = [tuple(a[k] + (b[k] - a[k]) * t / L for k in range(2)) for t in (t0, t1)]
    if abs(e[2]) < 1e-6:
        kind = "ridge"
    else:                     # a step into r, square to the edge: is q's plane above r there?
        mid = tuple((ends[0][k] + ends[1][k]) / 2 for k in range(2))
        n = (-(b[1] - a[1]), b[0] - a[0])
        n = tuple(x / math.hypot(*n) for x in n)
        step = [(mid[0] + s * n[0], mid[1] + s * n[1]) for s in (1.0, -1.0)]
        inner = next(p for p in step if inside(p, r.outline_uv))
        x, y, z = r.world(*inner, 0)
        kind = "hip" if q.height(x, y) > z else "valley"
    return Seam(q.id, ends[0], ends[1], kind)


WALL_DERIVED = ("start_meets", "end_meets", "tees", "above", "below")
FLOOR_DERIVED = ("bearers", "loads")
ROOF_DERIVED = ("seams",)


@dataclass
class House:
    """Labelled surfaces: walls with their openings, floors and ceilings, roof planes. Junctions are derived,
    never stored."""
    id: str
    walls: list[Wall]
    floors: list[Floor] = field(default_factory=list)
    kind: str = ""                   # what sort of house: box, L, T, ell, U
    roofs: list[Roof] = field(default_factory=list)

    def __post_init__(self):
        self.link()

    @property
    def surfaces(self) -> list[Surface]:
        return [*self.walls, *self.floors, *self.roofs]

    def surface(self, id: str) -> Surface:
        return next(x for x in self.surfaces if x.id == id)

    def wall(self, id: str) -> Wall:
        return next(w for w in self.walls if w.id == id)

    def link(self) -> None:
        """Find where walls meet each other (corners and Ts) and where they meet floors (under or on them)."""
        for w in self.walls:
            w.start_meets, w.end_meets, w.tees, w.above, w.below = None, None, [], None, None
        for w in self.walls:
            for end, p in (("start", w.start), ("end", w.end)):
                for x in self.walls:
                    parallel = abs(w.dir[0] * x.normal[0] + w.dir[1] * x.normal[1]) < 1e-9
                    if x is w or parallel or abs(x.base - w.base) > EPS:
                        continue          # a wall carrying on in the same line is not one this wall meets
                    q = (p[0] - x.start[0], p[1] - x.start[1])
                    t = q[0] * x.dir[0] + q[1] * x.dir[1]
                    off = abs(q[0] * x.normal[0] + q[1] * x.normal[1])
                    if off > EPS or t < -EPS or t > x.length + EPS:
                        continue
                    setattr(w, f"{end}_meets", x.id)
                    if EPS < t < x.length - EPS:
                        side = 1 if w.normal[0] * x.dir[0] + w.normal[1] * x.dir[1] > 0 else -1
                        x.tees.append(Tee(w.id, round(t, 4), side))
                    break
        for f in self.floors:
            f.bearers, f.loads = [], []
            for w in self.walls:
                if not (f.contains(w.start) and f.contains(w.end)):
                    continue
                line = Bearer(w.id, w.role, f.local((*w.start, f.z))[:2], f.local((*w.end, f.z))[:2],
                              f.local_dir(w.normal)[:2])
                if abs(w.base + w.height - f.z) <= EPS:
                    w.above = f.id
                    f.bearers.append(line)
                elif abs(w.base - f.z) <= EPS:
                    w.below = f.id
                    f.loads.append(line)
        for w in self.walls:
            w.tees.sort(key=lambda t: t.u)
        for r in self.roofs:
            r.seams = []
        for r, q in ((r, q) for r in self.roofs for q in self.roofs if r.id < q.id):
            for a, b in zip(r.outline_uv, r.outline_uv[1:] + r.outline_uv[:1]):
                for c, d in zip(q.outline_uv, q.outline_uv[1:] + q.outline_uv[:1]):
                    seam = _shared(r, a, b, q, c, d)
                    if seam:
                        r.seams.append(seam)
    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind,
                "walls": [{k: v for k, v in asdict(w).items() if k not in WALL_DERIVED} for w in self.walls],
                "floors": [{k: v for k, v in asdict(f).items() if k not in FLOOR_DERIVED} for f in self.floors],
                "roofs": [{k: v for k, v in asdict(r).items() if k not in ROOF_DERIVED} for r in self.roofs]}

    @staticmethod
    def from_dict(d: dict) -> "House":
        def openings(x):
            return [Opening(**o) for o in x.get("openings", [])]
        walls = [Wall(**{**{k: v for k, v in w.items() if k not in WALL_DERIVED}, "start": tuple(w["start"]),
                         "end": tuple(w["end"]), "openings": openings(w),
                         "outline": [tuple(p) for p in w["outline"]] if w.get("outline") else None}) for w in d["walls"]]
        floors = [Floor(**{**{k: v for k, v in f.items() if k not in FLOOR_DERIVED},
                           "outline": [tuple(p) for p in f["outline"]], "openings": openings(f),
                           "axis": tuple(f.get("axis", (1.0, 0.0)))})
                  for f in d.get("floors", [])]
        roofs = [Roof(**{**{k: v for k, v in r.items() if k not in ROOF_DERIVED}, "start": tuple(r["start"]),
                         "end": tuple(r["end"]), "outline": [tuple(p) for p in r["outline"]], "openings": openings(r)})
                 for r in d.get("roofs", [])]
        return House(d["id"], walls, floors, d.get("kind", ""), roofs)

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1))

    @staticmethod
    def load(path) -> "House":
        return House.from_dict(json.loads(Path(path).read_text()))


@dataclass(eq=False)
class Member:
    """One piece of timber: an oriented box around the centreline start to end, its depth along up, trimmed by
    cut planes and less any notches. A cut (n, d) keeps n.x <= d; a notch is a convex region (a list of such
    planes) taken out. `role` is a label for reading; the verifier never trusts it."""
    id: str
    section: str
    start: Vec
    end: Vec
    up: Vec
    rule: str
    surface: str = ""
    role: str = ""
    cuts: list = field(default_factory=list)
    notches: list = field(default_factory=list)

    @property
    def width(self) -> float:
        return SECTIONS[self.section][0]

    @property
    def depth(self) -> float:
        return SECTIONS[self.section][1]

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @cached_property
    def box(self) -> Box:
        """The world bounding box of what is left of the member."""
        return Box.around(self.points)

    @cached_property
    def points(self) -> list[Vec]:
        if self.plain:
            return corners(self.start, self.end, self.up, self.width, self.depth)
        return [p for piece in self.pieces for p in solid.points(piece)]

    @cached_property
    def pieces(self) -> list:
        """The solid as convex pieces (see solid.py)."""
        return solid.solid(self.start, self.end, self.up, self.width, self.depth, self.cuts, self.notches)

    @property
    def aligned(self) -> bool:
        """Its axes run along the world's axes."""
        return axis_aligned(sub(self.end, self.start)) and axis_aligned(self.up)

    @property
    def plain(self) -> bool:
        """An axis-aligned box, uncut: its bounding box is the member."""
        return self.aligned and not self.cuts and not self.notches

    def reshape(self, cut=None, notch=None) -> None:
        """Add a cut plane or a notch region, and forget the shape worked out before."""
        if cut is not None:
            self.cuts.append(cut)
        if notch is not None:
            self.notches.append(notch)
        for k in ("box", "points", "pieces"):
            self.__dict__.pop(k, None)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in ("id", "section", "start", "end", "up", "rule", "surface", "role")}
        if self.cuts or self.notches:
            d.update(cuts=self.cuts, notches=self.notches)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Member":
        t = lambda planes: [(tuple(n), d_) for n, d_ in planes]
        return Member(**{**d, "start": tuple(d["start"]), "end": tuple(d["end"]), "up": tuple(d["up"]),
                         "cuts": t(d.get("cuts", [])), "notches": [t(r) for r in d.get("notches", [])]})


@dataclass
class Frame:
    """The members a grammar built for a house, and how it got there.

    steps: every rule firing that changed something, in order: {pass, rule, wall, placed, removed}.
    removed: members placed and later removed, so the build can be replayed.
    """
    house: str
    grammar: str
    members: list[Member]
    errors: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    removed: list[Member] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"house": self.house, "grammar": self.grammar, "members": [m.to_dict() for m in self.members],
                "errors": self.errors, "steps": self.steps,
                "removed": [m.to_dict() for m in self.removed]}

    @staticmethod
    def from_dict(d: dict) -> "Frame":
        return Frame(d["house"], d["grammar"], [Member.from_dict(m) for m in d["members"]], d["errors"],
                     d.get("steps", []), [Member.from_dict(m) for m in d.get("removed", [])])

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1))

    @staticmethod
    def load(path) -> "Frame":
        return Frame.from_dict(json.loads(Path(path).read_text()))
