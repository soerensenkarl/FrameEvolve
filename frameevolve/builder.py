"""The builder applies a grammar to a house and returns a frame.

A grammar is a Python file of rules. A rule declares what it matches, and when:

    @rule(40, match="opening", when=lambda s, o: o.kind == "window")
    def sills(s, o):
        s.place(...)

The builder goes rule by rule, in priority order. For each rule it lists every match of its kind in the
design state (the house plus every member placed so far), and calls the rule once for each match whose
`when` holds and that it has not fired on before. Passes repeat until a whole pass changes nothing, so a
rule whose condition only becomes true after other rules have acted still fires. A rule never fires twice
on the same match. Every member records the rule that placed it; every step records the match.

Forces are known throughout, from a load takedown on the house's surfaces (loads.py): s.load is what lands on
a wall, s.pressure the area load of a floor or roof, and the "point" match every concentrated load. A rule
changes the load path with a structural guide: a "beam" on a floor, ceiling or roof plane is a bearing line
(a girder, a ridge beam) that takes its load to the walls it crosses; a "span" on a floor or ceiling sets
which way it spans. The takedown is redone when one is laid, so a rule that reads a force sees the load path
as laid out so far: the order of rules is the grammar's to get right. (An engineer lays out the load path
first, then a detailer frames to it, from the roof down.)

Match kinds (what the rule receives as its second argument; `s.surface` is set to the surface it is on,
a wall, a floor or a roof plane):
  house    the house, once (s.surface is None): for laying out guides over the whole plan
  guide    every guide laid out so far: .kind, .surface ("" for a line in plan), .a, .b
  wall     every wall
  floor    every floor, and the ceiling under a roof (role "ceiling")
  roof     every roof plane
  seam     every line where two roof planes meet, on the plane with the lower id: .other (the other plane's
           id), .a, .b (the line in this plane's u, v), .kind ('ridge', 'hip' or 'valley')
  opening  every door, window and stair opening
  corner   every wall end that meets another wall's end: .end ('start' or 'end'), .other (wall id)
  tee      every partition end meeting a wall along its length (s.surface is the wall met): .wall, .u, .side
  bearer   every wall under a floor (s.surface is the floor): .wall, .role, .a, .b (its line in the floor's
           u, v), .side (the direction its framing lies), .along_u
  load     every wall standing on a floor (s.surface is the floor), with the same fields
  point    every concentrated load landing on a wall's top or on a floor, gathered there by a beam or by an
           opening in the wall above: .u, .v (on a wall, its top), .load (dead, live, snow in lb; .sum), .source
  gap      every stretch of a face with no backing: .face ('outer' or 'inner'), .kind, .u0, .u1, .v0, .v1
  member   every member placed so far

Guides are lines to frame by, not timber: a grid over the plan, the joints between prefab panels. A rule lays
them out with s.guide and others read them with s.guides and s.crossings. Members are built into prefab panels
with s.assign (a panel is a name; members without one are built on site).

Coordinates in rules are the current surface's. On a wall: u along it from its start, v up from its base,
w into the framing from the surface. On a floor: u along x, v along y, w down from the floor's top (up from a
ceiling's underside). On a roof plane: u along the eave, v up the slope, w into the rafters, square to the
plane. Inches.
"""
from __future__ import annotations

import importlib.util
import itertools
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from frameevolve import solid, surface
from frameevolve.geometry import EPS, Box, dot, mul, overlaps, unit
from frameevolve.graph import Graph, build_graph
from frameevolve.loads import STRUCTURAL, Takedown
from frameevolve.model import SECTIONS, STOCK, THICK, Floor, Frame, Guide, House, Member, Wall
from frameevolve.verifier.analysis import Load


MATCHES = ("house", "guide", "wall", "floor", "roof", "seam", "opening", "corner", "tee", "bearer", "load", "point",
           "gap", "member")


def rule(priority: int, match: str, when=None):
    """Mark a function as a rule: fn(s, x) for each x of kind `match` where when(s, x) holds.
    Lower priority runs first in every pass."""
    if match not in MATCHES:
        raise ValueError(f"match is one of {', '.join(MATCHES)}, not {match!r}")

    def mark(fn):
        fn.priority, fn.match, fn.when = priority, match, when
        return fn
    return mark


@dataclass(frozen=True)
class Corner:
    end: str     # which end of s.surface: "start" or "end"
    other: str   # the wall it meets there


def target(kind: str, surf, x) -> dict:
    """Where a match is, for drawing what triggered a rule: a rectangle on the surface (u0, u1, v0, v1, and the
    face for a gap) or, for a member, its id. A tee is a line at its u (u0 == u1); a bearer or load is its line
    on the floor. "surface" names the surface it is on; "other" another surface involved."""
    if surf is None:            # the house, or a guide in plan
        return {"kind": kind, "surface": ""}
    full = {"surface": surf.id, "u0": 0.0, "u1": surf.size[0], "v0": 0.0, "v1": surf.size[1]}
    if kind in ("wall", "floor", "roof"):
        return {"kind": kind, **full}
    if kind == "seam":
        return {"kind": kind, "surface": surf.id, "u0": x.a[0], "u1": x.b[0], "v0": x.a[1], "v1": x.b[1], "other": x.other}
    if kind in ("bearer", "load"):
        return {"kind": kind, "surface": surf.id, "u0": x.a[0], "u1": x.b[0], "v0": x.a[1], "v1": x.b[1], "other": x.wall}
    if kind == "point":
        return {"kind": kind, "surface": surf.id, "u0": x.u, "u1": x.u, "v0": 0.0 if isinstance(surf, Wall) else x.v, "v1": x.v}
    if kind == "opening":
        return {"kind": kind, "surface": surf.id, "u0": x.u0, "u1": x.u1, "v0": x.v0, "v1": x.v1}
    if kind == "corner":
        u = 0.0 if x.end == "start" else surf.size[0]
        return {"kind": kind, **full, "u0": u, "u1": u, "other": x.other}
    if kind == "tee":
        return {"kind": kind, **full, "u0": x.u, "u1": x.u, "other": x.wall}
    if kind == "gap":
        return {"kind": kind, "surface": surf.id, "u0": x.u0, "u1": x.u1, "v0": x.v0, "v1": x.v1, "face": x.face}
    if kind == "guide":
        return {"kind": kind, "surface": surf.id, "u0": x.a[0], "u1": x.b[0], "v0": x.a[1], "v1": x.b[1]}
    return {"kind": kind, "surface": surf.id, "member": x.id}


def matches(s: "State", kind: str) -> list[tuple[object, object, tuple]]:
    """Every match of a kind in the design state now: (the surface it is on, the thing, a key that names it)."""
    walls, surfaces = s.house.walls, s.house.surfaces
    if kind == "house":
        return [(None, s.house, ("house",))]
    if kind == "guide":
        by_id = {x.id: x for x in surfaces}
        return [(by_id.get(g.surface), g, (g.id,)) for g in list(s._guides.values())]
    if kind == "wall":
        return [(w, w, (w.id,)) for w in walls]
    if kind == "floor":
        return [(f, f, (f.id,)) for f in s.house.floors]
    if kind == "roof":
        return [(r, r, (r.id,)) for r in s.house.roofs]
    if kind == "seam":
        return [(r, x, (r.id, x.other)) for r in s.house.roofs for x in r.seams]
    if kind in ("bearer", "load"):
        return [(f, b, (f.id, b.wall)) for f in s.house.floors for b in (f.bearers if kind == "bearer" else f.loads)]
    if kind == "point":
        return [(x, p, (x.id, p.u, p.v, p.source)) for x in (*walls, *s.house.floors) for p in s.loads.points(x.id)]
    if kind == "opening":
        return [(w, o, (o.id,)) for w in surfaces for o in w.openings]
    if kind == "corner":
        by_id = {w.id: w for w in walls}
        return [(w, Corner(end, other), (w.id, end)) for w in walls for end in ("start", "end")
                if (other := getattr(w, f"{end}_meets")) and not any(t.wall == w.id for t in by_id[other].tees)]
    if kind == "tee":
        return [(w, t, (w.id, t.wall)) for w in walls for t in w.tees]
    if kind == "gap":
        ms = list(s._members.values())
        by_id = {w.id: w for w in walls}
        return [(w, g, (w.id, face, round(g.u0, 3), round(g.v0, 3), g.kind)) for w in surfaces
                for face in w.faces for g in surface.gaps(w, ms, face=face, walls=by_id)]
    if kind == "member":
        by_id = {w.id: w for w in surfaces}
        return [(by_id.get(m.surface, walls[0]), m, (m.id,)) for m in s._members.values()]
    raise ValueError(kind)


def load_rules(path) -> list:
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"grammar_{path.stem}_{abs(hash(str(path.resolve())))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rules = [f for f in vars(mod).values()
             if callable(f) and hasattr(f, "match") and getattr(f, "__module__", None) == mod.__name__]
    return sorted(rules, key=lambda f: (f.priority, f.__name__))


class State:
    """The design state as rules see it, for the current surface `s.surface` (a wall, a floor or a roof plane)."""
    SECTIONS = SECTIONS
    THICK = THICK
    STOCK = STOCK

    def __init__(self, house: House):
        self.house = house
        self.surface = house.walls[0]
        self.changes = 0
        self._members: dict[str, Member] = {}
        self._ids = itertools.count(1)
        self._rule = ""
        self._graph: Graph | None = None
        self._removed: dict[str, Member] = {}
        self._placed_now: list[str] = []
        self._removed_now: list[str] = []
        self._shaped_now: list[str] = []
        self._guides: dict[str, Guide] = {}
        self._guided_now: list[str] = []
        self._assigned_now: list[str] = []
        self._loads: Takedown | None = None

    # reading ---------------------------------------------------------------------------------------

    def members(self, surface: str | None = None, role: str | None = None, rule: str | None = None,
                panel: str | None = None) -> list[Member]:
        """Members on a surface (default this one, '*' for all), optionally of one role, rule or panel."""
        w = self.surface.id if surface is None else surface
        return [m for m in self._members.values() if (w == "*" or m.surface == w)
                and (role is None or m.role == role) and (rule is None or m.rule == rule)
                and (panel is None or m.panel == panel)]

    def guides(self, kind: str | None = None, surface: str | None = None) -> list[Guide]:
        """Guides of a kind (default any): those on a surface (default this one), and those in plan."""
        sid = surface if surface is not None else (self.surface.id if self.surface is not None else "")
        return [g for g in self._guides.values() if (kind is None or g.kind == kind) and g.surface in (sid, "")]

    def crossings(self, kind: str) -> list[float]:
        """Where guides of a kind cross this surface's u axis (its bottom edge, v = 0): u values, in order. A
        guide in plan counts where its line crosses the surface's line in plan."""
        x, out = self.surface, []
        for g in self.guides(kind):
            if g.surface:
                (u0, v0), (u1, v1) = g.a, g.b
                if abs(v1 - v0) > 1e-9:
                    out.append(u0 + (u1 - u0) * (0 - v0) / (v1 - v0))
            else:
                o, e = x.origin, x.eu
                d = (g.b[0] - g.a[0], g.b[1] - g.a[1])
                den = e[0] * d[1] - e[1] * d[0]
                if abs(den) > 1e-9:
                    out.append(((g.a[0] - o[0]) * d[1] - (g.a[1] - o[1]) * d[0]) / den)
        return sorted(round(u, 6) for u in out if -EPS <= u <= x.size[0] + EPS)

    @property
    def loads(self) -> Takedown:
        """The load takedown on the house's surfaces, with the beams and spans laid out so far (loads.py)."""
        if self._loads is None:
            self._loads = Takedown(self.house, list(self._guides.values()))
        return self._loads

    def load(self, u0: float | None = None, u1: float | None = None) -> Load:
        """What lands on this wall's top between u0 and u1 along it (all of it by default), from the roofs,
        floors and walls above: a Load of .dead, .live and .snow in lb, .sum for all three. Over an opening, half
        goes to each side. An estimate from the house's surfaces, known before anything is framed."""
        return self.loads.on(self.surface.id, u0, u1)

    def pressure(self) -> Load:
        """The area load on this floor, ceiling or roof plane, psf: a Load of .dead, .live and .snow."""
        return self.loads.area.get(self.surface.id, Load())

    def local(self, m: Member) -> Box:
        """A member's bounding box in this surface's coordinates: lo = (u0, v0, w0), hi = (u1, v1, w1)."""
        return self.surface.local_box(m)

    @property
    def graph(self) -> Graph:
        if self._graph is None:
            self._graph = build_graph(list(self._members.values()))
        return self._graph

    def bears_on(self, m: Member) -> list:
        """What m rests on: members, or the string 'ground'."""
        return [self._members.get(k, k) for k in self.graph.bears.get(m.id, {})]

    def carries(self, m: Member) -> list[Member]:
        """What rests on m."""
        return [self._members[k] for k in self.graph.carries.get(m.id, {})]

    def beside(self, m: Member) -> list[Member]:
        """What touches m face to face from the side."""
        return [self._members[k] for k in self.graph.side.get(m.id, {})]

    def overlapping(self, m: Member) -> list[Member]:
        """Members whose solid overlaps m's: what m clashes with now."""
        out = []
        for n in self._members.values():
            if n is m or min(overlaps(m.box, n.box)) <= EPS:
                continue
            if (m.plain and n.plain) or solid.meet(m.pieces, n.pieces)[0] > 1e-6:
                out.append(n)
        return out

    def gaps(self, max_clear: float = surface.MAX_CLEAR, face: str = "outer") -> list[surface.Gap]:
        """Where a face of this surface ('outer' or 'inner') has no backing for its boards: edges with nothing
        behind, or spans over max_clear. Edges include where another wall's framing meets the face."""
        return surface.gaps(self.surface, list(self._members.values()), max_clear, face,
                            {w.id: w for w in self.house.walls})

    def below(self, u0: float, u1: float, v: float) -> float:
        """Height of the nearest thing under v across u0..u1 on this surface: a member, an opening, or the bottom."""
        best = 0.0
        for m in self.members():
            b = self.local(m)
            if b.lo[0] < u1 - EPS and b.hi[0] > u0 + EPS and b.hi[1] <= v + EPS:
                best = max(best, b.hi[1])
        for o in self.surface.openings:
            if o.u0 < u1 - EPS and o.u1 > u0 + EPS and o.v1 <= v + EPS:
                best = max(best, o.v1)
        return best

    def above(self, u0: float, u1: float, v: float) -> float:
        """Height of the nearest thing over v across u0..u1 on this surface: a member, an opening, or the top."""
        best = self.surface.size[1]
        for m in self.members():
            b = self.local(m)
            if b.lo[0] < u1 - EPS and b.hi[0] > u0 + EPS and b.lo[1] >= v - EPS:
                best = min(best, b.lo[1])
        for o in self.surface.openings:
            if o.u0 < u1 - EPS and o.u1 > u0 + EPS and o.v0 >= v - EPS:
                best = min(best, o.v0)
        return best

    def free(self, u0: float, u1: float, v0: float, v1: float, w0: float = 0.0, w1: float = 3.5) -> bool:
        """True if no member of any surface and no opening of this one occupies this box."""
        for o in self.surface.openings:
            if min(u1, o.u1) - max(u0, o.u0) > EPS and min(v1, o.v1) - max(v0, o.v0) > EPS:
                return False
        q = Box((u0, v0, w0), (u1, v1, w1))
        for m in self._members.values():
            b = self.local(m)
            if all(min(q.hi[k], b.hi[k]) - max(q.lo[k], b.lo[k]) > EPS for k in range(3)):
                return False
        return True

    # writing ---------------------------------------------------------------------------------------

    def place(self, section: str, u0: float, u1: float, v0: float, v1: float, w0: float = 0.0,
              role: str = "") -> Member:
        """Place a member by its rectangle in this surface's u, v plane, from w0 into the framing.

        The rectangle's short side says how the section is turned: equal to the width (1 1/2") means flat or
        upright, with the depth running through the wall; equal to the depth means on edge, 1 1/2" through.
        """
        if section not in SECTIONS:
            raise ValueError(f"unknown section {section!r}; use one of {', '.join(SECTIONS)}")
        width, depth = SECTIONS[section]
        u0, u1 = sorted((u0, u1))
        v0, v1 = sorted((v0, v1))
        along_u = (u1 - u0) >= (v1 - v0)
        short = (v1 - v0) if along_u else (u1 - u0)
        w = self.surface
        if abs(short - width) <= EPS:
            through, up = depth, w.ew
        elif abs(short - depth) <= EPS:
            through, up = width, (w.ev if along_u else w.eu)
        else:
            raise ValueError(f"a {section} shows {width:g} or {depth:g} in. in elevation, not {short:g}")
        wc = w0 + through / 2
        if along_u:
            a, b = w.world(u0, (v0 + v1) / 2, wc), w.world(u1, (v0 + v1) / 2, wc)
        else:
            a, b = w.world((u0 + u1) / 2, v0, wc), w.world((u0 + u1) / 2, v1, wc)
        m = Member(f"m{next(self._ids)}", section, a, b, up, self._rule, w.id, role)
        self._members[m.id] = m
        self._placed_now.append(m.id)
        self.changes += 1
        self._graph = None
        return m

    def put(self, section: str, a, b, up, role: str = "") -> Member:
        """Place a member at any angle: its centreline from point a to point b, its depth facing `up` (square to
        the centreline), all in this surface's u, v, w."""
        if section not in SECTIONS:
            raise ValueError(f"unknown section {section!r}; use one of {', '.join(SECTIONS)}")
        w = self.surface
        m = Member(f"m{next(self._ids)}", section, w.world(*a), w.world(*b), unit(w.world_dir(up)), self._rule, w.id, role)
        m.points   # raises if up is not square to the centreline
        self._members[m.id] = m
        self._placed_now.append(m.id)
        self.changes += 1
        self._graph = None
        return m

    def cut(self, m: Member, point, normal, surface=None) -> None:
        """Saw m along the plane through `point` square to `normal`, taking off the side the normal points to.
        Both in this surface's coordinates, or in another surface's if given (e.g. s.house.roofs[1])."""
        x = surface or self.surface
        n = unit(x.world_dir(normal))
        self._reshape(m, cut=(n, dot(n, x.world(*point))))

    def trim(self, m: Member, other: Member) -> None:
        """Cut m back to the face of `other` it runs into: whatever of m lies in or past that face comes off.
        The face is where m's centreline, from its end further from other's centreline, enters other; if the
        centreline misses other, the face m's middle lies furthest outside of."""
        planes = solid.box_planes(other.start, other.end, other.up, other.width, other.depth)
        ax = unit(tuple(other.end[k] - other.start[k] for k in range(3)))

        def far(p):   # squared distance from other's centreline
            q = tuple(p[k] - other.start[k] for k in range(3))
            t = dot(q, ax)
            return sum((q[k] - t * ax[k]) ** 2 for k in range(3))
        p0, p1 = (m.start, m.end) if far(m.start) >= far(m.end) else (m.end, m.start)
        d = tuple(p1[k] - p0[k] for k in range(3))
        enter, leave, face = 0.0, 1.0, None
        for n, h in planes:
            nd, gap = dot(n, d), h - dot(n, p0)
            if abs(nd) < 1e-12:
                if gap < 0:
                    enter, leave = 1.0, 0.0
            elif nd < 0 and gap / nd > enter:
                enter, face = gap / nd, (n, h)
            elif nd > 0:
                leave = min(leave, gap / nd)
        if face is None or enter > leave:
            pts = m.points
            c = tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))
            face = max(planes, key=lambda pl: dot(pl[0], c) - pl[1])
        n, h = face
        self._reshape(m, cut=(mul(n, -1), -h))

    def under(self, m: Member, other: Member) -> None:
        """Cut m along the underside of `other` (its face that looks most downward): what of m is above comes off."""
        n, d = min(solid.box_planes(other.start, other.end, other.up, other.width, other.depth), key=lambda pl: pl[0][2])
        self._reshape(m, cut=(mul(n, -1), -d))

    def fit(self, m: Member, *surfaces) -> None:
        """Take off what of m lies above all of these surfaces at once: one surface is a cut flush with its
        plane; two roof planes meeting in a valley groove a valley rafter's top to both."""
        self._reshape(m, notch=[(x.ew, dot(x.ew, x.origin)) for x in surfaces])

    def notch(self, m: Member, other: Member, below: bool = False) -> None:
        """Cut a notch in m where `other`'s box is, so the two fit together. below=True also takes off everything
        of m under other (a seat cut: a rafter's birdsmouth over a plate)."""
        planes = solid.box_planes(other.start, other.end, other.up, other.width, other.depth)
        if below:
            planes.remove(min(planes, key=lambda pl: pl[0][2]))
        self._reshape(m, notch=planes)

    def _reshape(self, m: Member, cut=None, notch=None) -> None:
        if m.id not in self._members:
            raise ValueError(f"{m.id} is not in the frame")
        m.reshape(cut, notch)
        if not m.pieces:
            (m.cuts if cut is not None else m.notches).pop()
            m.reshape()
            raise ValueError(f"that would cut away all of {m.id}")
        self._shaped_now.append(m.id)
        self.changes += 1
        self._graph = None

    def guide(self, kind: str, a, b, plan: bool = False) -> Guide:
        """Lay out a guide line of a kind ("grid", "panel joint", ...) from a to b in this surface's u, v; with
        plan=True (or in a house rule), a line in plan from (x, y) a to b. Guides are not timber. Two kinds are
        structural, and change the loads rules read from then on: "beam", a bearing line on this floor, ceiling
        or roof plane that carries what spans onto it to the walls it crosses or ends on, and "span", a line on
        this floor or ceiling along the way it is to span."""
        on = "" if plan or self.surface is None else self.surface.id
        if kind in STRUCTURAL:
            if not on or isinstance(self.surface, Wall) or (kind == "span" and not isinstance(self.surface, Floor)):
                raise ValueError(f"a {kind} guide lies on a floor or ceiling" + (" or a roof plane" if kind == "beam" else ""))
            self._loads = None
        g = Guide(f"g{len(self._guides) + 1}", kind, on, tuple(map(float, a)), tuple(map(float, b)), self._rule)
        self._guides[g.id] = g
        self._guided_now.append(g.id)
        self.changes += 1
        return g

    def assign(self, m: Member, panel: str) -> None:
        """Build m into the prefab panel of this name in the shop ("" to build it on site)."""
        if m.panel != panel:
            m.panel = panel
            self._assigned_now.append(m.id)
            self.changes += 1

    def remove(self, m: Member) -> None:
        """Take a member out of the frame. The build history keeps it."""
        if self._members.pop(m.id, None) is not None:
            self._removed[m.id] = m
            self._removed_now.append(m.id)
            self.changes += 1
            self._graph = None


def _where(e: Exception, path: Path) -> str:
    lines = [f.lineno for f in traceback.extract_tb(e.__traceback__) if Path(f.filename) == path]
    return f" (line {lines[-1]})" if lines else ""


def build(grammar, house: House, max_passes: int = 10, max_members: int = 20000, on_step=None) -> Frame:
    """on_step(step, members): called as each step happens, with the members placed so far by id."""
    path = Path(grammar).resolve()
    try:
        rules = load_rules(path)
    except Exception as e:
        return Frame(house.id, str(grammar), [], [f"grammar does not load: {type(e).__name__}: {e}"])
    s = State(house)
    errors: list[str] = []
    steps: list[dict] = []
    fired: set = set()
    t0 = time.perf_counter()

    def frame() -> Frame:
        removed = [m for k, m in s._removed.items() if k not in s._members]
        return Frame(house.id, str(grammar), list(s._members.values()), errors, steps, removed,
                     list(s._guides.values()))

    def error(r, key, e) -> None:
        msg = f"{r.__name__} on {' '.join(map(str, key))}: {type(e).__name__}: {e}{_where(e, path)}"
        if msg not in errors:
            errors.append(msg)

    for p in range(1, max_passes + 1):
        before = s.changes
        for r in rules:
            s._rule = r.__name__
            for surf, x, key in matches(s, r.match):
                if (r.__name__, key) in fired:
                    continue
                s.surface = surf
                try:
                    if r.when is not None and not r.when(s, x):
                        continue      # not yet: a later pass may make it true
                except Exception as e:
                    error(r, key, e)
                    continue
                fired.add((r.__name__, key))
                s._placed_now, s._removed_now, s._shaped_now = [], [], []
                s._guided_now, s._assigned_now = [], []
                try:
                    r(s, x)
                except Exception as e:
                    error(r, key, e)
                if s._placed_now or s._removed_now or s._shaped_now or s._guided_now or s._assigned_now:
                    steps.append({"pass": p, "rule": r.__name__, "surface": surf.id if surf else "",
                                  "match": f"{r.match} {' '.join(map(str, key))}", "target": target(r.match, surf, x),
                                  "placed": s._placed_now, "removed": s._removed_now,
                                  "shaped": sorted(set(s._shaped_now)), "assigned": sorted(set(s._assigned_now)),
                                  "guides": s._guided_now, "t": round(time.perf_counter() - t0, 4)})
                    if on_step:
                        on_step(steps[-1], s._members)
                if len(s._members) > max_members:
                    errors.append(f"stopped: more than {max_members} members")
                    return frame()
        if s.changes == before:
            break
    else:
        errors.append(f"did not settle after {max_passes} passes")
    return frame()


MAX_LINES = 12   # code lines per function in a grammar, by default


def sizes(source: str) -> dict[str, int]:
    """Code lines in each function of a grammar: no docstring, blank lines or comment lines."""
    import ast
    lines = source.splitlines()
    out = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            body = node.body[1:] if ast.get_docstring(node) else node.body
            if body:
                code = lines[body[0].lineno - 1:node.end_lineno]
                out[node.name] = sum(1 for l in code if l.strip() and not l.strip().startswith("#"))
    return out


def too_big(source: str, max_lines: int = MAX_LINES) -> list[str]:
    """What breaks the size limit, in words; empty when every function fits. Keeps rules small and readable."""
    try:
        return [f"{name} has {n} code lines; the limit is {max_lines}. Split it into smaller rules."
                for name, n in sizes(source).items() if n > max_lines]
    except SyntaxError as e:
        return [f"the grammar does not parse: line {e.lineno}: {e.msg}"]
