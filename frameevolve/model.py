"""The shared data model: houses as labelled surfaces (walls and floors), frames as lists of members. Inches, z up."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path

from frameevolve.geometry import EPS, Box, Vec, add, axis_aligned, corners, dot, mul, sub, unit

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
    """What walls and floors share: local axes eu, ev, ew from an origin, and a size along u and v."""

    def world(self, u: float, v: float, w: float) -> Vec:
        return add(self.origin, add(mul(self.eu, u), add(mul(self.ev, v), mul(self.ew, w))))

    def local(self, p: Vec) -> Vec:
        q = sub(p, self.origin)
        return (dot(q, self.eu), dot(q, self.ev), dot(q, self.ew))

    def local_box(self, box: Box) -> Box:
        """A world box in this surface's coordinates: lo = (u0, v0, w0), hi = (u1, v1, w1)."""
        return Box.around([self.local((x, y, z)) for x in (box.lo[0], box.hi[0])
                           for y in (box.lo[1], box.hi[1]) for z in (box.lo[2], box.hi[2])])


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
    above: str | None = None         # the floor resting on this wall's top
    below: str | None = None         # the floor this wall stands on

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def size(self) -> tuple[float, float]:
        return (self.length, self.height)

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
    """A floor surface: a horizontal rectangle at height z, the top of its framing (the subfloor sits on it).

    Local coordinates: u along x from its corner, v along y, w down into the framing. bearers are the walls
    under it, loads the walls standing on it; both are worked out from the geometry.
    """
    id: str
    corner: tuple[float, float]
    length: float                    # along x
    width: float                     # along y
    z: float
    role: str = "floor"
    openings: list[Opening] = field(default_factory=list)
    bearers: list[Bearer] = field(default_factory=list)
    loads: list[Bearer] = field(default_factory=list)

    @property
    def size(self) -> tuple[float, float]:
        return (self.length, self.width)

    @property
    def origin(self) -> Vec:
        return (self.corner[0], self.corner[1], self.z)

    eu = property(lambda self: (1.0, 0.0, 0.0))
    ev = property(lambda self: (0.0, 1.0, 0.0))
    ew = property(lambda self: (0.0, 0.0, -1.0))

    def contains(self, p: tuple[float, float]) -> bool:
        return (self.corner[0] - EPS <= p[0] <= self.corner[0] + self.length + EPS
                and self.corner[1] - EPS <= p[1] <= self.corner[1] + self.width + EPS)


WALL_DERIVED = ("start_meets", "end_meets", "tees", "above", "below")
FLOOR_DERIVED = ("bearers", "loads")


@dataclass
class House:
    """Labelled surfaces: walls with their openings, and floors. Junctions are derived, never stored."""
    id: str
    walls: list[Wall]
    floors: list[Floor] = field(default_factory=list)

    def __post_init__(self):
        self.link()

    @property
    def surfaces(self) -> list[Surface]:
        return [*self.walls, *self.floors]

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
                    if x is w or abs(x.base - w.base) > EPS:
                        continue
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
                line = Bearer(w.id, w.role, (w.start[0] - f.corner[0], w.start[1] - f.corner[1]),
                              (w.end[0] - f.corner[0], w.end[1] - f.corner[1]), (w.normal[0], w.normal[1]))
                if abs(w.base + w.height - f.z) <= EPS:
                    w.above = f.id
                    f.bearers.append(line)
                elif abs(w.base - f.z) <= EPS:
                    w.below = f.id
                    f.loads.append(line)
        for w in self.walls:
            w.tees.sort(key=lambda t: t.u)

    def to_dict(self) -> dict:
        return {"id": self.id,
                "walls": [{k: v for k, v in asdict(w).items() if k not in WALL_DERIVED} for w in self.walls],
                "floors": [{k: v for k, v in asdict(f).items() if k not in FLOOR_DERIVED} for f in self.floors]}

    @staticmethod
    def from_dict(d: dict) -> "House":
        def openings(x):
            return [Opening(**o) for o in x.get("openings", [])]
        walls = [Wall(**{**{k: v for k, v in w.items() if k not in WALL_DERIVED}, "start": tuple(w["start"]),
                         "end": tuple(w["end"]), "openings": openings(w)}) for w in d["walls"]]
        floors = [Floor(**{**{k: v for k, v in f.items() if k not in FLOOR_DERIVED}, "corner": tuple(f["corner"]),
                           "openings": openings(f)}) for f in d.get("floors", [])]
        return House(d["id"], walls, floors)

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1))

    @staticmethod
    def load(path) -> "House":
        return House.from_dict(json.loads(Path(path).read_text()))


@dataclass(eq=False)
class Member:
    """One piece of timber, an oriented box. `role` is a label for reading; the verifier never trusts it."""
    id: str
    section: str
    start: Vec
    end: Vec
    up: Vec
    rule: str
    surface: str = ""
    role: str = ""

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
        return Box.around(corners(self.start, self.end, self.up, self.width, self.depth))

    @property
    def aligned(self) -> bool:
        return axis_aligned(sub(self.end, self.start)) and axis_aligned(self.up)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "section", "start", "end", "up", "rule", "surface", "role")}

    @staticmethod
    def from_dict(d: dict) -> "Member":
        return Member(**{**d, "start": tuple(d["start"]), "end": tuple(d["end"]), "up": tuple(d["up"])})


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
