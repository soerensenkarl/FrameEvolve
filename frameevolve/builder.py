"""The builder applies a grammar to a house and returns a frame.

A grammar is a Python file of rules. A rule is a function marked with @rule(priority) that takes the
state `s` for one wall at a time, looks at the design state (the house plus every member placed so far)
and places or removes members. The builder calls each rule, in priority order, on every wall, pass after
pass, until a whole pass changes nothing. `s.once(key)` lets a rule act once per key, so rules read as
"for every X not yet handled". Every member records the rule that placed it.

Coordinates in rules are the current wall's: u along the wall from its start, v up from its base,
w inward from its outer face. Inches.
"""
from __future__ import annotations

import importlib.util
import itertools
import traceback
from pathlib import Path

from frameevolve import surface
from frameevolve.geometry import EPS, Box
from frameevolve.graph import GROUND, Graph, build_graph
from frameevolve.model import SECTIONS, STOCK, THICK, Frame, House, Member, Wall


def rule(priority: int):
    """Mark a function as a rule. Lower priority runs first in every pass."""
    def mark(fn):
        fn.priority = priority
        return fn
    return mark


def load_rules(path) -> list:
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"grammar_{path.stem}_{abs(hash(str(path.resolve())))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rules = [f for f in vars(mod).values()
             if callable(f) and hasattr(f, "priority") and getattr(f, "__module__", None) == mod.__name__]
    return sorted(rules, key=lambda f: (f.priority, f.__name__))


class State:
    """The design state as rules see it, for the current wall `s.wall`."""
    SECTIONS = SECTIONS
    THICK = THICK
    STOCK = STOCK

    def __init__(self, house: House):
        self.house = house
        self.wall: Wall = house.walls[0]
        self.changes = 0
        self._members: dict[str, Member] = {}
        self._ids = itertools.count(1)
        self._done: set = set()
        self._rule = ""
        self._graph: Graph | None = None
        self._removed: dict[str, Member] = {}
        self._placed_now: list[str] = []
        self._removed_now: list[str] = []

    # reading ---------------------------------------------------------------------------------------

    def members(self, wall: str | None = None, role: str | None = None, rule: str | None = None) -> list[Member]:
        """Members on a wall (default this one, '*' for all), optionally of one role or one rule."""
        w = self.wall.id if wall is None else wall
        return [m for m in self._members.values() if (w == "*" or m.surface == w)
                and (role is None or m.role == role) and (rule is None or m.rule == rule)]

    def local(self, m: Member) -> Box:
        """A member's box in this wall's coordinates: lo = (u0, v0, w0), hi = (u1, v1, w1)."""
        return self.wall.local_box(m.box)

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

    def gaps(self, max_clear: float = surface.MAX_CLEAR, face: str = "outer") -> list[surface.Gap]:
        """Where a face of this wall ('outer' or 'inner') has no backing for its boards: edges with nothing
        behind, or spans over max_clear. Edges include where another wall's framing meets the face."""
        return surface.gaps(self.wall, list(self._members.values()), max_clear, face,
                            {w.id: w for w in self.house.walls})

    def below(self, u0: float, u1: float, v: float) -> float:
        """Height of the nearest thing under v across u0..u1 on this wall: a member, an opening, or the base."""
        best = 0.0
        for m in self.members():
            b = self.local(m)
            if b.lo[0] < u1 - EPS and b.hi[0] > u0 + EPS and b.hi[1] <= v + EPS:
                best = max(best, b.hi[1])
        for o in self.wall.openings:
            if o.u0 < u1 - EPS and o.u1 > u0 + EPS and o.v1 <= v + EPS:
                best = max(best, o.v1)
        return best

    def above(self, u0: float, u1: float, v: float) -> float:
        """Height of the nearest thing over v across u0..u1 on this wall: a member, an opening, or the top."""
        best = self.wall.height
        for m in self.members():
            b = self.local(m)
            if b.lo[0] < u1 - EPS and b.hi[0] > u0 + EPS and b.lo[1] >= v - EPS:
                best = min(best, b.lo[1])
        for o in self.wall.openings:
            if o.u0 < u1 - EPS and o.u1 > u0 + EPS and o.v0 >= v - EPS:
                best = min(best, o.v0)
        return best

    def free(self, u0: float, u1: float, v0: float, v1: float, w0: float = 0.0, w1: float = 3.5) -> bool:
        """True if no member of any wall and no opening of this wall occupies this box."""
        for o in self.wall.openings:
            if min(u1, o.u1) - max(u0, o.u0) > EPS and min(v1, o.v1) - max(v0, o.v0) > EPS:
                return False
        q = Box((u0, v0, w0), (u1, v1, w1))
        for m in self._members.values():
            b = self.local(m)
            if all(min(q.hi[k], b.hi[k]) - max(q.lo[k], b.lo[k]) > EPS for k in range(3)):
                return False
        return True

    def once(self, *key) -> bool:
        """True the first time this rule asks with this key on this wall, False after."""
        k = (self._rule, self.wall.id) + key
        if k in self._done:
            return False
        self._done.add(k)
        return True

    # writing ---------------------------------------------------------------------------------------

    def place(self, section: str, u0: float, u1: float, v0: float, v1: float, w0: float = 0.0,
              role: str = "") -> Member:
        """Place a member by its rectangle in this wall's elevation, from w0 inward.

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
        w = self.wall
        if abs(short - width) <= EPS:
            through, up = depth, w.normal
        elif abs(short - depth) <= EPS:
            through, up = width, ((0.0, 0.0, 1.0) if along_u else w.dir)
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


def build(grammar, house: House, max_passes: int = 10, max_members: int = 20000) -> Frame:
    path = Path(grammar).resolve()
    try:
        rules = load_rules(path)
    except Exception as e:
        return Frame(house.id, str(grammar), [], [], [f"grammar does not load: {type(e).__name__}: {e}"])
    s = State(house)
    log: list[str] = []
    errors: list[str] = []
    steps: list[dict] = []

    def frame() -> Frame:
        removed = [m for k, m in s._removed.items() if k not in s._members]
        return Frame(house.id, str(grammar), list(s._members.values()), log, errors, steps, removed)

    for p in range(1, max_passes + 1):
        before = s.changes
        for r in rules:
            for wall in house.walls:
                s.wall, s._rule = wall, r.__name__
                s._placed_now, s._removed_now = [], []
                n = s.changes
                try:
                    r(s)
                except Exception as e:
                    msg = f"{r.__name__} on {wall.id}: {type(e).__name__}: {e}{_where(e, path)}"
                    if msg not in errors:
                        errors.append(msg)
                if s.changes != n:
                    log.append(f"pass {p}: {r.__name__} on {wall.id}, {s.changes - n} changes")
                    steps.append({"pass": p, "rule": r.__name__, "wall": wall.id,
                                  "placed": s._placed_now, "removed": s._removed_now})
                if len(s._members) > max_members:
                    errors.append(f"stopped: more than {max_members} members")
                    return frame()
        if s.changes == before:
            break
    else:
        errors.append(f"did not settle after {max_passes} passes")
    return frame()
