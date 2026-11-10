"""The load takedown on the house's surfaces, before any member exists: what an engineer does on the plans.

Loads come from the house, not the frame, and gravity only goes down, so the takedown needs no framing:

  roofs      each plane's area load (on its plan area) goes down the slope, in strips, to the walls under it
             and to any beam laid out on it
  floors     each floor's and ceiling's area load, and what the walls standing on it bring, goes along its
             span, in strips, to the walls under it and to any beam laid out on it, as the reactions of
             simply supported spans; a load right over a bearing line goes straight into it
  walls      what lands on a wall's top, and the wall's own weight, goes down to the floor it stands on, or
             out of the house at the ground; what lands over an opening goes to the opening's two sides

Surfaces are taken from the top down, each after everything that lands on it. A grammar's rules change
the load path with structural guides (s.guide): a "beam" on a floor, ceiling or roof plane is a bearing line
that takes its load to the walls it crosses or ends on; a "span" on a floor or ceiling sets which way it spans
(by default the way that gives the shortest spans). The takedown is the same code whether or not there are
guides, and cheap, so it is redone whenever a structural guide is laid.

Loads are (dead, live, snow) in pounds. A load that finds nothing to carry it is listed in `lost`; everything
else reaches the ground: applied = ground + lost. Estimates for framing by, not the verifier's analysis:
that one follows the loads through the members as built (verifier/analysis.py).
"""
from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from typing import NamedTuple

from frameevolve.geometry import EPS, scan
from frameevolve.model import Floor, Guide, House, Roof, Wall
from frameevolve.verifier.analysis import CEILING_LOAD, FLOOR_LOAD, NONE, PSF, ROOF_LOAD, Load, total

STEP = 6.0                 # the width of a strip, inches
NEAR = 3.0                 # a load this close to a bearing line in plan goes straight into it
REACH = 24.0               # a wall holds a roof plane up where the plane passes no more than this over its top
WALL_DEAD = 8.0            # a framed wall with its boards, psf of wall (ASCE 7 Table C3.1-1: 2x6 at 16", finished)
STRUCTURAL = ("beam", "span")   # the guide kinds that change the load path

Pt = tuple[float, float]


class Item(NamedTuple):
    """A load at a place: (u,) along a wall or a beam, (u, v) on a floor. source: "area" for a surface's own
    load and a wall's weight, or what gathered it into a point ("beam g3", "opening 1w0.d1")."""
    at: tuple
    load: Load
    source: str = "area"


@dataclass(frozen=True)
class Point:
    """A concentrated load landing on a surface: on a wall at u along its top, on a floor at u, v."""
    u: float
    v: float
    load: Load
    source: str


@dataclass(frozen=True)
class Line:
    """A bearing line under a surface, in plan: a wall, or a beam laid out as a guide."""
    id: str
    beam: bool
    a: Pt
    b: Pt

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)

    def along(self, p: Pt) -> float:
        """How far along the line the point nearest p is."""
        L = self.length
        t = ((p[0] - self.a[0]) * (self.b[0] - self.a[0]) + (p[1] - self.a[1]) * (self.b[1] - self.a[1])) / L
        return min(max(t, 0.0), L)

    def off(self, p: Pt) -> float:
        """The distance from p to the line."""
        t = self.along(p) / self.length
        return math.dist(p, (self.a[0] + (self.b[0] - self.a[0]) * t, self.a[1] + (self.b[1] - self.a[1]) * t))


def crossing(p: Pt, q: Pt, line: Line, slack: float = NEAR) -> float | None:
    """Where the stretch from p to q crosses a bearing line: the distance from p, or None. Both may miss by
    `slack` at their ends (a joist reaches the far face of its wall)."""
    d = (q[0] - p[0], q[1] - p[1])
    e = (line.b[0] - line.a[0], line.b[1] - line.a[1])
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        return None
    w = (line.a[0] - p[0], line.a[1] - p[1])
    t = (w[0] * e[1] - w[1] * e[0]) / den          # along p-q, 0 to 1
    k = (w[0] * d[1] - w[1] * d[0]) / den          # along the line, 0 to 1
    L, M = math.hypot(*d), math.hypot(*e)
    if -slack <= t * L <= L + slack and -slack <= k * M <= M + slack:
        return t * L
    return None


def spread(a: float, b: float, w: Load, points: list[tuple[float, Load, str]], supports: list[tuple[float, Line]]):
    """A strip from a to b on its supports (position, line), in order: its uniform load w (per inch) and its
    point loads (position, load, source), as the reactions of simply supported spans. An overhang goes to the
    support at its end. Returns (line, position, load, source) for each reaction."""
    pos = [p for p, _ in supports]
    cl = [min(max(p, a), b) for p in pos]          # a support may sit just past the strip's end
    share = [0.0] * len(pos)
    share[0] += cl[0] - a
    share[-1] += b - cl[-1]
    for i in range(len(pos) - 1):
        share[i] += (cl[i + 1] - cl[i]) / 2
        share[i + 1] += (cl[i + 1] - cl[i]) / 2
    out = [(supports[i][1], pos[i], w * share[i], "area") for i in range(len(pos)) if share[i] > 0]
    for p, load, source in points:
        i = bisect_right(pos, p) - 1
        if i < 0 or len(pos) == 1 or p - pos[max(i, 0)] <= NEAR:
            out.append((supports[max(i, 0)][1], pos[max(i, 0)], load, source))
        elif i >= len(pos) - 1 or pos[i + 1] - p <= NEAR:
            j = min(i + 1, len(pos) - 1)
            out.append((supports[j][1], pos[j], load, source))
        else:
            k = (p - pos[i]) / (pos[i + 1] - pos[i])
            out.append((supports[i][1], pos[i], load * (1 - k), source))
            out.append((supports[i + 1][1], pos[i + 1], load * k, source))
    return out


def wall_top(w: Wall, u: float) -> float:
    """The height of a wall's top at u along it: under its gable's slope where it has one."""
    if not w.outline:
        return w.base + w.height
    vs = [v for a, b in scan([(v, x) for x, v in w.outline], min(max(u, EPS), w.length - EPS)) for v in (a, b)]
    return w.base + (max(vs) if vs else w.height)


class Takedown:
    """The loads on a house's surfaces, with the structural guides laid out so far.

    area[surface id]   the area load on a floor, ceiling or roof plane, psf
    span[floor id]     which way a floor or ceiling spans: "u" or "v"
    top[wall id]       what lands on a wall's top: items at (u,)
    base[wall id]      what the wall passes down: the same gathered to the sides of its openings, and its weight
    onto[floor id]     what the walls standing on a floor bring: items at (u, v)
    beams[guide id]    what a beam carries: items at (distance along it,)
    applied, ground    all the load on the house, and what reaches the ground
    lost               loads nothing carries: (surface id, load, why)
    """

    def __init__(self, house: House, guides: list[Guide] = ()):
        self.house = house
        self.guides = [g for g in guides if g.kind in STRUCTURAL and g.surface]
        self.area: dict[str, Load] = {}
        self.span: dict[str, str] = {}
        self.top: dict[str, list[Item]] = defaultdict(list)
        self.base: dict[str, list[Item]] = defaultdict(list)
        self.onto: dict[str, list[Item]] = defaultdict(list)
        self.beams: dict[str, list[Item]] = defaultdict(list)
        self.applied, self.ground = NONE, NONE
        self.lost: list[tuple[str, Load, str]] = []
        self._walls = {w.id: w for w in house.walls}
        for r in house.roofs:
            self._roof(r)
        for r in house.roofs:      # after every plane: a ridge beam gathers from the planes on both its sides
            self._beams(r, self._lines(r, house.walls, own=True))
        # floors and walls from the top down: a floor before the walls under it, a wall before the floor it stands on
        order = [(-f.z, 0, f) for f in house.floors] + [(-(w.base + w.height), 1, w) for w in house.walls]
        for _, kind, x in sorted(order, key=lambda t: t[:2]):
            self._wall(x) if kind else self._floor(x)

    # reading -----------------------------------------------------------------------------------------

    def on(self, wall: str, u0: float | None = None, u1: float | None = None) -> Load:
        """What lands on a wall's top between u0 and u1 along it (all of it by default), lb."""
        return total(i.load for i in self.top.get(wall, [])
                     if (u0 is None or i.at[0] >= u0 - EPS) and (u1 is None or i.at[0] <= u1 + EPS))

    def points(self, surface: str) -> list[Point]:
        """The concentrated loads landing on a wall's top or on a floor: gathered by a beam or an opening above."""
        x = next((y for y in self.house.surfaces if y.id == surface), None)
        items = self.top.get(surface, []) if isinstance(x, Wall) else self.onto.get(surface, [])
        by: dict[tuple, Load] = defaultdict(lambda: NONE)
        for i in items:
            if i.source != "area":
                by[(*(round(c) for c in i.at), i.source)] += i.load
        if isinstance(x, Wall):
            return [Point(float(u), x.height, load, src) for (u, src), load in sorted(by.items())]
        return [Point(float(u), float(v), load, src) for (u, v, src), load in sorted(by.items())]

    # the takedown ------------------------------------------------------------------------------------

    def _lines(self, x, walls: list[Wall], own: bool = False) -> list[Line]:
        """The bearing lines under a surface: these walls, and the beams laid out on it (for a roof plane, on
        any roof plane, unless `own`: a beam along a ridge or a valley holds both planes that meet there)."""
        lines = [Line(w.id, False, w.start, w.end) for w in walls]
        roofs = {} if own or not isinstance(x, Roof) else {r.id: r for r in self.house.roofs}
        for g in self.guides:
            on = x if g.surface == x.id else roofs.get(g.surface)
            if g.kind == "beam" and on is not None:
                lines.append(Line(g.id, True, on.world(*g.a, 0)[:2], on.world(*g.b, 0)[:2]))
        return lines

    def _deliver(self, line: Line, p: Pt, load: Load, source: str) -> None:
        """A reaction at p in plan goes onto the wall or the beam whose line it is."""
        (self.beams if line.beam else self.top)[line.id].append(Item((line.along(p),), load, source))

    def _strips(self, x, k: int, lines: list[Line], holds=lambda line, p: True):
        """A surface cut in strips along its u (k = 0) or v (k = 1): for each, (its place across, its start and
        end along, where it is in plan, its supports in order)."""
        poly = x.outline_uv if k == 0 else [(v, u) for u, v in x.outline_uv]
        n = int(max(p[1] for p in poly) // STEP) + 1
        for i in range(n):
            c = (i + 0.5) * STEP
            for a, b in scan(poly, c):
                at = (lambda t, c=c: x.world(t, c, 0)[:2]) if k == 0 else (lambda t, c=c: x.world(c, t, 0)[:2])
                sup = []
                for line in lines:
                    t = crossing(at(a), at(b), line)
                    if t is not None and holds(line, at(a + t)):
                        sup.append((a + t, line))
                yield c, a, b, at, sorted(sup, key=lambda s: s[0])

    def _roof(self, r: Roof) -> None:
        """A roof plane's load down the slope to the walls under it and the beams on it."""
        cos = 1 / math.sqrt(1 + r.slope ** 2)
        self.area[r.id] = Load(*ROOF_LOAD)
        w = Load(*ROOF_LOAD) * (PSF * STEP * cos)      # per inch up the slope: the load is on the plan area
        under = lambda line, p: line.beam or -6.0 <= r.height(*p) - wall_top(
            self._walls[line.id], line.along(p)) <= REACH
        lines = self._lines(r, self.house.walls)
        adrift = []
        for _, a, b, at, sup in self._strips(r, 1, lines, under):
            self.applied += w * (b - a)
            if sup:
                for line, t, load, source in spread(a, b, w, [], sup):
                    self._deliver(line, at(t), load, source)
            else:
                adrift.append((at(a), w * (b - a)))
        # a strip over no wall (past a valley, over another roof) leans on the framing at its foot: taken to the
        # nearest wall that holds this plane up
        holders = [l for l in lines if any(i for i in (self.beams if l.beam else self.top).get(l.id, []))]
        for p, load in adrift:
            if holders:
                self._deliver(min(holders, key=lambda l: l.off(p)), p, load, "area")
            else:
                self.lost.append((r.id, load, "no wall under this roof plane"))

    def _floor(self, f: Floor) -> None:
        """A floor's or ceiling's load, and what stands on it, along its span to the walls and beams under it."""
        psf = Load(*(CEILING_LOAD if f.role == "ceiling" else FLOOR_LOAD))
        self.area[f.id] = psf
        lines = self._lines(f, [self._walls[b.wall] for b in f.bearers])
        k = self._direction(f, lines)
        self.span[f.id] = "uv"[k]
        strips = defaultdict(list)
        for c, a, b, at, sup in self._strips(f, k, lines):
            strips[int(c // STEP)].append((a, b, at, sup, []))
        w = psf * (PSF * STEP)
        for item in self.onto.get(f.id, []):
            p = f.world(*item.at, 0)[:2]
            direct = min(lines, key=lambda l: l.off(p), default=None)
            if direct is not None and direct.off(p) <= NEAR:
                self._deliver(direct, p, item.load, item.source)
                continue
            across, along = item.at[1 - k], item.at[k]
            run = next((s for s in strips.get(int(across // STEP), []) if s[0] - NEAR <= along <= s[1] + NEAR), None)
            if run is None or not run[3]:
                self.lost.append((f.id, item.load, "a load on this floor with nothing under it"))
            else:
                run[4].append((along, item.load, item.source))
        for runs in strips.values():
            for a, b, at, sup, points in runs:
                self.applied += w * (b - a)
                if not sup:
                    self.lost.append((f.id, w * (b - a), "a strip of this floor with no wall or beam under it"))
                    continue
                for line, t, load, source in spread(a, b, w, points, sup):
                    self._deliver(line, at(t), load, source)
        self._beams(f, lines)

    def _direction(self, f: Floor, lines: list[Line]) -> int:
        """Which way a floor spans (0 along u, 1 along v): as its "span" guide says, else the way with the
        shorter longest span."""
        for g in self.guides:
            if g.kind == "span" and g.surface == f.id:
                return 0 if abs(g.b[0] - g.a[0]) >= abs(g.b[1] - g.a[1]) else 1

        def longest(k: int) -> float:
            worst = 0.0
            for _, a, b, _, sup in self._strips(f, k, lines):
                pos = [a, *[p for p, _ in sup], b]
                worst = max(worst, math.inf if not sup else max(q - p for p, q in zip(pos, pos[1:])))
            return worst
        return 0 if longest(0) < longest(1) else 1

    def _beams(self, x, lines: list[Line]) -> None:
        """Each beam on a surface takes what it gathered to the walls it crosses or ends on."""
        walls = [l for l in lines if not l.beam]
        for beam in (l for l in lines if l.beam):
            items = self.beams.get(beam.id, [])
            if isinstance(x, Roof):
                held = lambda l, p: -6.0 <= x.height(*p) - wall_top(self._walls[l.id], l.along(p)) <= REACH
            else:
                held = lambda l, p: True
            at = lambda t: (beam.a[0] + (beam.b[0] - beam.a[0]) * t / beam.length,
                            beam.a[1] + (beam.b[1] - beam.a[1]) * t / beam.length)
            sup = sorted(((t, l) for l in walls if (t := crossing(beam.a, beam.b, l)) is not None and held(l, at(t))),
                         key=lambda s: s[0])
            if not sup:
                if items:
                    self.lost.append((x.id, total(i.load for i in items), f"beam {beam.id} rests on no wall"))
                continue
            for line, t, load, _ in spread(0.0, beam.length, NONE, [(i.at[0], i.load, "") for i in items], sup):
                self._deliver(line, at(t), load, f"beam {beam.id}")

    def _wall(self, w: Wall) -> None:
        """What is on a wall's top goes down it, round its openings, with its own weight, to what it stands on."""
        base = []
        for item in self.top.get(w.id, []):
            o = next((o for o in w.openings if o.u0 + EPS < item.at[0] < o.u1 - EPS), None)
            if o is None:
                base.append(item)
            else:           # over an opening: to its two sides, as the ends of a header
                k = (item.at[0] - o.u0) / (o.u1 - o.u0)
                base.append(Item((o.u0,), item.load * (1 - k), f"opening {o.id}"))
                base.append(Item((o.u1,), item.load * k, f"opening {o.id}"))
        n = max(1, round(w.length / STEP))
        own = Load(WALL_DEAD * PSF * w.height * w.length / n)
        for i in range(n):
            base.append(Item(((i + 0.5) * w.length / n,), own))
            self.applied += own
        self.base[w.id] = base
        if w.below is None:
            if abs(w.base) <= EPS:
                self.ground += total(i.load for i in base)
            else:
                self.lost.append((w.id, total(i.load for i in base), "this wall stands on nothing"))
            return
        f = self.house.surface(w.below)
        for item in base:
            x, y = w.start[0] + w.dir[0] * item.at[0], w.start[1] + w.dir[1] * item.at[0]
            self.onto[f.id].append(Item(f.local((x, y, f.z))[:2], item.load, item.source))
