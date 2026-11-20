"""Detail an envelope into a House: everything a real building model does not record, made up to fit it.

The envelope gives masses with their roofs (envelope.py); the assessor's record gives the storeys and the year.
From those, with a seeded random choice wherever a real house could differ:

  levels     a storey height by the house's age, as many storeys as the record says, and what is left of the
             main mass's height over the ground taken off as foundation; each mass gets the storeys its own
             eave reaches
  roofs      every roof face a roof plane, its eave edges pushed out for an overhang
  walls      each storey's walls along the outline of every mass that reaches it: exterior where nothing or a
             lower roof is beyond, a junction wall where another mass's rooms are; none where the mass only
             stands on another's roof (a mansard's top) and is not yet clear of it. A top wall follows the
             roof, a raised heel under the plane at an eave
  floors     a floor at every level over the masses that reach it, a ceiling over masses that top out together
  inside     bearing walls so no floor spans too far, partitions between them clear of the windows, a stair
             through every floor
  openings   windows in columns that line up over the storeys, set between the bearing walls; a front and a
             back door; a window in a tall gable; doors inside until every room can be reached

So that a set of houses covers what houses ask of a framer, a house is also given, by seeded chance weighted
by its age, some of: a bearing line opened up into posts and a beam; a mass left to span further than joists
alone can; a wide window or a sliding door; a porch open between corner posts; a room of double height; a top
storey open to the roof, or with a loft over part of it. Each is noted in house.has (dataset.py counts them).

A brief says what is known of the real house, read from photos of its sides (photos.py), and the detailer follows
it where it speaks: {"floors_ft": [4, 14], "sides": {"south": {"1": [{"at": 0.2, "kind": "window", "w": 30,
"h": 60}, {"at": 0.5, "kind": "door"}], "2": [...]}, "east": null, ...}}. floors_ft are the floors' heights over
the ground; a side is seen from outside, "at" running from 0 at its left end to 1 at its right; a side, or a
storey of one, that is not given is made up as before.

Everything is a surface with its openings, as the generator's houses are. Inches.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

from frameevolve.envelope import FLAT, Envelope, Face, Mass, eave, foot, free, grounded
from frameevolve.houses import EAVE, HEAD, HEEL, SPAN, plane
from frameevolve.model import Floor, House, Opening, Wall

JOISTS = 10.875     # a floor's depth with its subfloor: a level less a wall's height
PLATES = (97.125, 109.125, 85.125)   # wall heights: 8 and 9 ft (precut studs), and the 7 ft of low old houses
KNEE = 24.0         # a wall lower than this is not built: the roof comes down to the floor
ROOM = 78.0         # a top wall this high has a flat ceiling on it; lower, the room is under the rafters
STAIR = (36.0, 120.0)
CARRIED = 0.25      # a mass with less of its outline on the ground than this stands on other masses' roofs
LONG = 264.0        # how far a floor spans where a house is left a long span: 22 ft, a beam's or an engineered joist's work
VOID = (144.0, 168.0)   # a double-height room's opening in the floor over it
PORCH = 260 * 144   # a one-storey mass smaller than this may be an open porch, square inches


@dataclass
class Run:
    """A straight stretch of a mass's outline, counter-clockwise: what lies beyond each part of it, and the
    places of the windows along it."""
    mass: Mass
    a: tuple
    b: tuple
    spans: list = field(default_factory=list)      # (t0, t1, the mass beyond or None)
    columns: list = field(default_factory=list)

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)

    @property
    def inward(self) -> tuple:
        L = self.length
        return (-(self.b[1] - self.a[1]) / L, (self.b[0] - self.a[0]) / L)

    def at(self, t: float, off: float = 0.0) -> tuple:
        """The point at t along the run, `off` inward of it."""
        L, n = self.length, self.inward
        return (self.a[0] + (self.b[0] - self.a[0]) * t / L + off * n[0], self.a[1] + (self.b[1] - self.a[1]) * t / L + off * n[1])


def detail(env: Envelope, record: dict, seed: int = 0, name: str = "", brief: dict | None = None) -> House:
    """A complete House on an envelope, by the assessor's record of it and, where there is one, a brief."""
    brief = brief or {}
    rng = random.Random(f"{name}/{seed}")
    year = int(record.get("condition_yearbuilt") or 1900)
    ms = sorted(env.masses, key=lambda m: -m.shape.area)
    eaves = {id(m): eave(m, ms) for m in ms}
    storeys = float(record.get("exterior_numstories") or 2)
    low = foot(ms[0])
    if brief.get("floors_ft"):
        # the floors as seen, in feet over the ground: the ground floor's height is the foundation, the mean
        # step between floors the level, and the top storey has what is left under the eave
        seen = [12.0 * z for z in brief["floors_ft"]]
        cut = seen[0]
        level = (seen[-1] - seen[0]) / (len(seen) - 1) if len(seen) > 1 else PLATES[0] + JOISTS
        plate = level - JOISTS
        top = eaves[id(ms[0])] - HEEL - cut - (len(seen) - 1) * level
        if low is not None and top > level:
            top = None
    elif low is not None and eaves[id(ms[0])] - low >= KNEE and storeys >= 2:
        # a mansard or gambrel: the storeys under its steep sides are set by where those start, their walls
        # reaching the floor the sides stand on; the storey behind the sides is as high as they are
        level, plate, cut, top = levels(rng, low - JOISTS, storeys - 1, year)
        top = None if top == plate else top
    else:
        level, plate, cut, top = levels(rng, eaves[id(ms[0])], storeys, year)
    ms = [m for m in ms if eaves[id(m)] - HEEL - cut >= ROOM - HEEL]
    for m in ms:                          # the foundation is taken off: z = 0 is the ground floor
        for f in m.faces:
            f.c -= cut
    E = {id(m): eaves[id(m)] - HEEL - cut for m in ms}                       # each mass's wall top
    n = {id(m): 1 + sum(E[id(m)] - k * level >= KNEE for k in range(1, 9)) for m in ms}
    if brief.get("floors_ft"):
        n[id(ms[0])] = len(brief["floors_ft"])                               # every floor seen is a storey, however low its walls
    if top is not None:
        E[id(ms[0])] = (n[id(ms[0])] - 1) * level + top                      # the main mass, exactly
    whole = pieces(unary_union([m.shape.buffer(0.5, join_style=2) for m in ms]).buffer(-0.5, join_style=2))[0] \
        if len(ms) > 1 else ms[0].shape
    carried = {id(m): len(ms) > 1 and grounded(m, whole) < CARRIED for m in ms}
    rooms = {}                            # where each mass's own rooms are: not where another mass has its own walls
    for m in ms:
        others = [o.area for o in ms if o is not m and not carried[id(o)]]
        left = m.shape.difference(unary_union(others).buffer(0.5)) if others else m.shape
        rooms[id(m)] = max(getattr(left, "geoms", [left]), key=lambda g: g.area) if not left.is_empty else m.shape
    style = Style(rng, year, plate)
    span = LONG if rng.random() < (0.3 if year >= 1950 else 0.15) else SPAN
    attic = rng.choices(["ceiling", "open", "loft"], [0.76, 0.12, 0.12])[0]
    house = House(name, [], kind=(record.get("exterior_style") or "").lower())
    house.foundation = cut            # how far the ground lies under the ground floor
    house.stair = None
    house.missed = []                 # openings a brief saw that found no place
    house.placed = 0                  # and how many of its openings did
    house.has = set()                 # the design situations this house was given
    house.porches = {id(m) for m in ms[1:] if n[id(m)] == 1 and m.shape.area <= PORCH and not carried[id(m)] and rng.random() < 0.6}
    if spines(rooms[id(ms[0])], span)[1] != spines(rooms[id(ms[0])], SPAN)[1]:
        house.has.add("long span")
    runs = {id(m): outline_runs(m, ms, style, rooms[id(m)], span) for m in ms}
    briefed(brief, [r for rs in runs.values() for r in rs])
    top_storey = max(n.values())
    for k in range(1, top_storey + 1):
        here = [m for m in ms if n[id(m)] >= k]
        storey_walls(house, k, here, runs, E, n, carried, level)
        if k > 1:
            for j, piece in enumerate(pieces(unary_union([m.shape.buffer(0.5, join_style=2) for m in here]).buffer(-0.5, join_style=2))):
                house.floors.append(Floor(f"f{k}" + "abcdefgh"[j - 1] * (j > 0), ring(piece), (k - 1) * level))
    ceilings(house, ms, E, n, level, attic, spines(rooms[id(ms[0])], span))
    for m in ms:
        for f in m.faces:
            clean = f.shape.buffer(-0.75, join_style=2).buffer(0.75, join_style=2)     # no spike or sliver thinner than 1 1/2 in.
            clean = max(getattr(clean, "geoms", [clean]), key=lambda g: g.area)
            if not clean.is_empty and clean.area > 144:
                f.shape = Polygon(clean.exterior).simplify(0.05)
                house.roofs.append(roof(f"r{len(house.roofs) + 1}", f, m, ms))
    core = rooms[id(ms[0])]               # the stair goes where every floor is
    for f in house.floors:
        if f.role == "floor" and len(f.id) == 2:
            core = core.intersection(Polygon(f.outline))
    stair = house.stair = hole_place(rng, rooms[id(ms[0])], core, span, STAIR) if n[id(ms[0])] > 1 else None
    void = None                           # a room of double height: an opening in the floor over the ground storey
    if stair is not None and rng.random() < (0.2 if year >= 1960 else 0.07):
        void = hole_place(rng, rooms[id(ms[0])], core.difference(stair.buffer(48)), span, VOID)
    for k in range(1, top_storey + 1):
        for j, m in enumerate(ms):
            if n[id(m)] < k or (carried[id(m)] and any(o is not m and n[id(o)] >= k and o.shape.contains(m.shape.centroid) for o in ms)):
                continue                  # a mass standing on another is part of that one's rooms
            h = level if k < n[id(m)] else E[id(m)] - (k - 1) * level
            inside(rng, house, k, j, rooms[id(m)], h, (k - 1) * level, [x for x in (stair, void if k == 2 else None) if x is not None], runs[id(m)], style, span)
    for w in house.walls:
        if w.id[1] in "sp":
            under_roof(w, ms, HEEL)
    house.walls = [w for w in house.walls if not w.outline or stand(w, 2 * KNEE if w.id[1] in "sp" else KNEE)]
    house.walls = [w for w in house.walls if w.height >= KNEE]
    house.link()
    if stair:
        for f in house.floors:
            if f.role == "floor" and Polygon(f.outline).contains(stair.buffer(6)):
                x0, y0, x1, y1 = stair.bounds
                (u0, v0, _), (u1, v1, _) = f.local((x0, y0, f.z)), f.local((x1, y1, f.z))
                f.openings.append(Opening(f"{f.id}o0", "stair", min(u0, u1), max(u0, u1), min(v0, v1), max(v0, v1)))
    if void is not None:
        f = next((f for f in house.floors if f.id == "f2" and Polygon(f.outline).contains(void.buffer(6))), None)
        if f is not None:
            x0, y0, x1, y1 = void.bounds
            (u0, v0, _), (u1, v1, _) = f.local((x0, y0, f.z)), f.local((x1, y1, f.z))
            f.openings.append(Opening(f"{f.id}o{len(f.openings)}", "void", min(u0, u1), max(u0, u1), min(v0, v1), max(v0, v1)))
            house.has.add("double height")
    openings(rng, house, style, level, brief.get("sides") or {})
    house.link()
    for k in range(1, top_storey + 1):
        connect(house, (k - 1) * level, stair if k > 1 else None)
    house.link()
    return house


class Style:
    """What a house's openings look like, by its age: old houses have tall narrow windows, later ones wider."""

    def __init__(self, rng, year: int, plate: float):
        old = year < 1940
        self.width = rng.choice([28, 30, 32, 36] if old else [30, 36, 48, 60])
        self.height = rng.choice([54, 60, 62] if old else [36, 48, 54])
        self.head = HEAD if plate < 105 or rng.random() < 0.4 else rng.choice([90.0, 96.0])
        self.pitch = rng.uniform(84, 126)       # about how far apart the windows stand
        self.late = not old


def levels(rng, eave_z: float, storeys: float, year: int) -> tuple[float, float, float, float]:
    """(level, wall height, foundation, top wall height) for a main mass whose eave stands eave_z over the
    ground: a wall height by the house's age; the record's count of full storeys (one more where it counts a
    half storey and the height has room) unless the height will not have it; the rest is foundation, or, where
    the eave is too low for a full top storey, a lower top wall."""
    want = PLATES[1] if rng.random() < (0.7 if year < 1940 else 0.2) else PLATES[0]
    wall_top = eave_z - HEEL
    full = max(1, math.floor(storeys))
    best = None
    for p in PLATES:
        lv = p + JOISTS
        for n in range(1, 5):
            cut = wall_top - (n - 1) * lv - p
            cost = abs(cut - 18) + max(0.0, cut - 60) if cut >= 0 else 3 * -cut
            cost += 0 if n == full else 40 if n == full + 1 and storeys - full >= 0.5 else 120 if n < full else 300
            cost += 0 if p == want else 30 if p == PLATES[2] else 12
            if best is None or cost < best[0]:
                best = (cost, lv, p, cut)
    _, lv, p, cut = best
    return (lv, p, cut, p) if cut >= 0 else (lv, p, 0.0, p + cut)


def pieces(shape) -> list[Polygon]:
    return [Polygon(g.exterior) for g in sorted(getattr(shape, "geoms", [shape]), key=lambda g: -g.area) if g.area > 20 * 144]


def ring(shape: Polygon) -> list[tuple]:
    """A shape's corners, counter-clockwise, without the points along its straight edges."""
    pts = list(orient(shape, 1.0).exterior.coords)[:-1]
    out = []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % len(pts)]
        cross = (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])
        if abs(cross) > 0.02 * math.dist(a, p) * math.dist(p, b) and math.dist(a, p) > 0.5:
            out.append((round(p[0], 3), round(p[1], 3)))
    return out


def outline_runs(m: Mass, ms: list[Mass], style: Style, region: Polygon, span: float) -> list[Run]:
    """A mass's outline as runs: each with what lies beyond it, part by part, and its window columns, set
    evenly in each stretch between the walls that will meet the run (bearing walls, other masses' walls)."""
    pts = ring(m.shape)
    along_x, at = spines(region, span)
    out = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        run = Run(m, a, b)
        L = run.length
        if L < 1:
            continue
        shared = []
        beyond = LineString([run.at(0.0, -3.0), run.at(L, -3.0)])       # just outside the run
        for o in ms:
            if o is m:
                continue
            part = beyond.intersection(o.area.buffer(1.5))
            for g in getattr(part, "geoms", [part]):
                if g.geom_type == "LineString" and g.length > 6:
                    ts = sorted(math.dist(run.at(0.0, -3.0), p) for p in g.coords)
                    shared.append((ts[0], ts[-1], o))
        t = 0.0
        for t0, t1, o in sorted(shared, key=lambda s: s[0]):
            if t0 - t > 6:
                run.spans.append((t, t0, None))
            if t1 - max(t0, t) > 6:
                run.spans.append((max(t0, t), t1, o))
            t = max(t, t1)
        if L - t > 6:
            run.spans.append((t, L, None))
        marks = {0.0, L} | {t for t0, t1, _ in run.spans for t in (t0, t1)}
        for s in at:                               # where a bearing wall meets this run
            d = (b[1] - a[1]) if along_x else (b[0] - a[0])
            if abs(d) > 1e-6:
                t = (s - (a[1] if along_x else a[0])) / d * L
                if 0 < t < L:
                    marks.add(t)
        marks = sorted(marks)
        for p, q in zip(marks, marks[1:]):
            count = max(1 if q - p >= style.width + 44 else 0, round((q - p) / style.pitch))
            run.columns += [p + (i + 0.5) * (q - p) / count for i in range(count)]
        out.append(run)
    return out


SIDES = {"south": (0, -1), "east": (1, 0), "north": (0, 1), "west": (-1, 0)}     # the way each side faces


def briefed(brief: dict, runs: list[Run]) -> None:
    """Give the runs facing a briefed side the brief's window places (of every storey), so that partitions keep
    clear of where the windows will be."""
    for side, storeys in (brief.get("sides") or {}).items():
        if not storeys:
            continue
        d = SIDES[side]
        along = lambda p: -d[1] * p[0] + d[0] * p[1]
        ends = [along(p) for r in runs for p in (r.a, r.b)]
        r0, r1 = min(ends), max(ends)
        for run in runs:
            if -(run.inward[0] * d[0] + run.inward[1] * d[1]) <= 0.5:
                continue
            a, b = along(run.a), along(run.b)
            run.columns = sorted({round(abs(r0 + float(i["at"]) * (r1 - r0) - a) / abs(b - a) * run.length, 1) for items in storeys.values()
                                  for i in items or [] if min(a, b) <= r0 + float(i["at"]) * (r1 - r0) <= max(a, b)}) if abs(b - a) > 1 else []


def top_at(run: Run, t: float, side: float = 0.0) -> float:
    """How high the mass's wall stands at t along a run: up to the roof face that ends over it there, less a
    raised heel where that edge is an eave (the roof rising square from it) or the roof is flat."""
    m = run.mass
    t = min(max(t + side, 0.01), run.length - 0.01)
    x, y = run.at(t)
    n = run.inward
    p = Point(run.at(t, 1.5))
    f = min(m.faces, key=lambda f: f.shape.distance(p))
    z = f.z(x, y)
    if f.slope < FLAT or (f.a * n[0] + f.b * n[1]) / f.slope > 0.3:      # the roof rises from this wall, square or askew (a hip's corner)
        return z - HEEL
    return z


def profile(run: Run, t0: float, t1: float) -> list[tuple]:
    """The wall top from t0 to t1 along a run as (t, z) points: straight between the points where the roof face
    over the wall changes, found by stepping along it."""
    faces = run.mass.faces

    def over(t: float) -> int:
        p = Point(run.at(min(max(t, 0.01), run.length - 0.01), 1.5))
        return min(range(len(faces)), key=lambda i: faces[i].shape.distance(p))
    ts = [t0 + (t1 - t0) * i / max(1, round((t1 - t0) / 6)) for i in range(max(1, round((t1 - t0) / 6)) + 1)]
    cuts = [t0]
    for a, b in zip(ts, ts[1:]):
        fa, fb = over(a), over(b)
        if fa != fb:
            for _ in range(6):
                mid = (a + b) / 2
                a, b = (mid, b) if over(mid) == fa else (a, mid)
            cuts.append((a + b) / 2)
    cuts.append(t1)
    out = []
    for a, b in zip(cuts, cuts[1:]):
        if b - a > 0.5:
            out += [(a, top_at(run, a, 0.3)), (b, top_at(run, b, -0.3))]
    return out or [(t0, top_at(run, t0, 0.3)), (t1, top_at(run, t1, -0.3))]


def storey_walls(house: House, k: int, here: list[Mass], runs, E, n, carried, level: float) -> None:
    """Storey k's walls along the outline of every mass that reaches it. Where another mass lies beyond, the
    one with the higher walls frames the wall: a junction wall if the other's roof is over its top, exterior
    if the other's roof is under it (marked `abutted` where the roof meets it part way up). A mass that stands
    on others' roofs has no wall where it is not clear of them: the room below runs through."""
    base = (k - 1) * level
    count = {"w": 0, "j": 0}
    for m in here:
        for run in runs[id(m)]:
            for t0, t1, o in run.spans:
                if o is not None and (E[id(o)], o.shape.area) > (E[id(m)], m.shape.area):
                    continue                      # the other mass frames this wall
                pts = [(t, z - base) for t, z in profile(run, t0, t1)]
                if k < n[id(m)]:
                    pts = [(t, min(z, level)) for t, z in pts]
                    if min(z for _, z in pts) > level - 3:
                        pts = [(t0, level), (t1, level)]
                elif all(abs(z - (E[id(m)] - base)) < 3 for _, z in pts):
                    pts = [(t0, E[id(m)] - base), (t1, E[id(m)] - base)]
                pts = [(t, max(z, 0.0)) for t, z in pts]
                high = max(z for _, z in pts)
                if high < KNEE:
                    continue
                role, abutted = "exterior", False
                if o is not None:
                    beyond = o.z(*run.at((t0 + t1) / 2, -6.0)) - base
                    if beyond >= high - 12:
                        if carried[id(m)]:
                            continue
                        role = "interior"
                    else:
                        abutted = beyond > 12
                kind = "j" if role == "interior" else "w"
                w = Wall(f"{k}{kind}{count[kind]}", run.at(t0), run.at(t1), min(z for _, z in pts), base, role=role)
                if high - w.height > 0.5:
                    line = [(0.0, 0.0), (round(t1 - t0, 3), 0.0)] + [(round(t - t0, 3), round(z, 3)) for t, z in reversed(pts)]
                    w.outline = [p for i, p in enumerate(line) if p != line[i - 1]]
                    w.height = max(min(pts[0][1], pts[-1][1]), w.height)
                w.run, w.t0, w.abutted = run, t0, abutted
                house.walls.append(w)
                count[kind] += 1


def ceilings(house: House, ms: list[Mass], E, n, level: float, attic: str, main_spines) -> None:
    """A ceiling on the top walls of every mass with a full top storey under a sloped roof; masses that top out
    together (a mansard's sides and its top) share one. The main mass's may be left out (`attic` "open": its
    top storey is open to the roof) or laid over one side of its first bearing wall only ("loft")."""
    todo = [m for m in ms if E[id(m)] - (n[id(m)] - 1) * level >= ROOM and max(m.faces, key=lambda f: f.shape.area).slope >= FLAT]
    groups: list[list[Mass]] = []
    for m in todo:
        for g in groups:
            if any(abs(E[id(m)] - E[id(o)]) < 9 and m.shape.distance(o.shape) < 2 for o in g):
                g.append(m)
                break
        else:
            groups.append([m])
    taken = Polygon()
    for j, g in enumerate(groups):
        shape = unary_union([m.shape.buffer(0.5, join_style=2) for m in g]).buffer(-0.5, join_style=2).difference(taken.buffer(0.5))
        for piece in pieces(shape)[:1]:
            z = E[id(g[0])]
            held = unary_union([LineString([w.start, w.end]) for w in house.walls if abs(w.base + w.height - z) < 1.5] or [Point(1e9, 1e9)])
            if piece.exterior.intersection(held.buffer(2)).length < 0.3 * piece.exterior.length:
                continue                  # no walls to rest on (a mansard's sides come down around it): open to the roof
            if ms[0] in g and attic == "open":
                house.has.add("open to the roof")
                continue
            if ms[0] in g and attic == "loft" and main_spines[1]:
                x0, y0, x1, y1 = piece.bounds
                at = main_spines[1][0]
                half = piece.intersection(box(x0, y0, x1, at) if main_spines[0] else box(x0, y0, at, y1))
                if half.geom_type == "Polygon" and half.area > 60 * 144:
                    piece = half
                    house.has.add("loft")
            f = max(g[0].faces, key=lambda f: f.shape.area)
            house.floors.append(Floor(f"c{j}" if j else "c", ring(piece), E[id(g[0])], role="ceiling",
                                      axis=(abs(f.b) / f.slope, abs(f.a) / f.slope)))
            taken = unary_union([taken, piece])


def roof(rid: str, f: Face, m: Mass, ms: list[Mass]):
    """A roof face as a roof plane, its eave edges pushed out by the overhang: the edges beside them run on to
    the new eave line."""
    pts = list(orient(f.shape, 1.0).exterior.coords)[:-1]
    if f.slope >= FLAT:
        gx, gy = f.a / f.slope, f.b / f.slope
        push = []
        for a, b in zip(pts, pts[1:] + pts[:1]):
            L = math.dist(a, b)
            out = ((b[1] - a[1]) / L, -(b[0] - a[0]) / L) if L > 1e-6 else (0, 0)
            is_eave = L > 12 and out[0] * gx + out[1] * gy < -0.98 and free(f, a, b, m)
            if is_eave:                    # not where the roof ends against a higher mass's wall
                p = Point((a[0] + b[0]) / 2 + 6 * out[0], (a[1] + b[1]) / 2 + 6 * out[1])
                is_eave = not any(o is not m and o.shape.contains(p) and o.z(p.x, p.y) > f.z(p.x, p.y) + 6 for o in ms)
            push.append(EAVE if is_eave else 0.0)
        pts = offset(pts, push)
    e = (f.b / f.slope, -f.a / f.slope) if f.slope > 1e-9 else (1.0, 0.0)      # along the eave, the roof rising to its left
    low = min(pts, key=lambda p: f.z(*p))
    return plane(rid, low, (low[0] + e[0], low[1] + e[1]), f.z(*low), f.slope * 12, pts)


def offset(pts: list, push: list) -> list:
    """A polygon with each edge moved out by its own distance: corners go to where the moved edges meet."""
    n = len(pts)
    lines = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.dist(a, b) or 1.0
        ox, oy = (b[1] - a[1]) / L * push[i], -(b[0] - a[0]) / L * push[i]
        lines.append(((a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)))
    out = []
    for i in range(n):
        (p, q), (r, s) = lines[i - 1], lines[i]
        d1, d2 = (q[0] - p[0], q[1] - p[1]), (s[0] - r[0], s[1] - r[1])
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 0.05 * math.hypot(*d1) * math.hypot(*d2):      # the two run on in one line
            out += [q, r] if math.dist(q, r) > 0.01 else [r]
            continue
        t = ((r[0] - p[0]) * d2[1] - (r[1] - p[1]) * d2[0]) / den
        out.append((p[0] + t * d1[0], p[1] + t * d1[1]))
    return out


def scan(shape: Polygon, c: float, along_x: bool) -> list[tuple]:
    """The stretches of the line y = c (or x = c) inside a shape."""
    x0, y0, x1, y1 = shape.bounds
    line = LineString([(x0 - 1, c), (x1 + 1, c)] if along_x else [(c, y0 - 1), (c, y1 + 1)])
    part = shape.intersection(line)
    out = []
    for g in getattr(part, "geoms", [part]):
        if g.geom_type == "LineString" and g.length > 1:
            vs = sorted(p[0 if along_x else 1] for p in g.coords)
            out.append((vs[0], vs[-1]))
    return out


def spines(shape: Polygon, span: float = SPAN) -> tuple[bool, list[float]]:
    """Where a mass's rooms need bearing walls so that no floor in it spans further than `span`: (they run along x,
    their places). They run the long way; each is put in the middle of the deepest stretches left."""
    x0, y0, x1, y1 = shape.bounds
    along_x = x1 - x0 >= y1 - y0
    lo, hi = (x0, x1) if along_x else (y0, y1)
    if min(x1 - x0, y1 - y0) <= span:
        return along_x, []
    at: list[float] = []
    for _ in range(3):
        deep = []
        for c in [lo + 12 * i for i in range(1, int((hi - lo) // 12))]:
            for a, b in scan(shape, c, not along_x):
                marks = [a] + sorted(s for s in at if a < s < b) + [b]
                deep += [(p + q) / 2 for p, q in zip(marks, marks[1:]) if q - p > span]
        if not deep:
            break
        deep.sort()
        at.append(2.0 * round(deep[len(deep) // 2] / 2))
    return along_x, sorted(at)


def hole_place(rng, shape: Polygon, core: Polygon, span: float, size: tuple):
    """An opening in the floors (a stair, a double-height room) in the main mass where every floor is (`core`),
    clear of the outline and the bearing walls; its long side across them if it fits."""
    along_x, at = spines(shape, span)
    room = core.buffer(-18)
    if room.is_empty:
        return None
    x0, y0, x1, y1 = room.bounds
    for i in range(800):
        w, d = size if along_x == (i < 400) else size[::-1]
        if x1 - x0 <= w or y1 - y0 <= d:
            continue
        x, y = 2.0 * round(rng.uniform(x0, x1 - w) / 2), 2.0 * round(rng.uniform(y0, y1 - d) / 2)
        r = box(x, y, x + w, y + d)
        lo, hi = (y, y + d) if along_x else (x, x + w)
        if room.contains(r) and all(not (lo - 12 < s < hi + 12) for s in at):
            return r
    return None


def inside(rng, house: House, k: int, j: int, shape: Polygon, height: float, base: float, holes: list, runs, style: Style, span: float) -> None:
    """A mass's walls inside on storey k: its bearing walls, and partitions from one bearing line to the next,
    clear of the openings in the floor (the stair, a double-height room) and of the windows in the walls they
    end on."""
    if height < KNEE:
        return
    along_x, at = spines(shape, span)
    tag = f"{j}" if j else ""
    for i, s in enumerate(at):
        for q, (a, b) in enumerate(scan(shape, s, along_x)):
            if b - a >= 48:
                p0, p1 = ((a, s), (b, s)) if along_x else ((s, a), (s, b))
                house.walls.append(Wall(f"{k}s{tag}{'abc'[i]}{q or ''}", p0, p1, height, base, role="interior"))
    x0, y0, x1, y1 = shape.bounds
    lo, hi = (x0, x1) if along_x else (y0, y1)
    windows = [r.at(t) for r in runs for t in r.columns]
    want = max(0, min(4, round(shape.area / 144 / 320) - 1 + rng.choice([-1, 0, 0, 1])))
    used: list[float] = []
    for i in range(want):
        for _ in range(60):
            if hi - lo < 150:
                break
            c = 2.0 * round(rng.uniform(lo + 72, hi - 72) / 2)
            if any(abs(c - u) < 72 for u in used):
                continue
            bays = []
            for a, b in scan(shape, c, not along_x):
                marks = [a] + [s for s in at if a < s < b] + [b]
                bays += [(p, q) for p, q in zip(marks, marks[1:]) if q - p >= 60]
            if not bays:
                continue
            a, b = rng.choice(bays)
            p0, p1 = ((c, a), (c, b)) if along_x else ((a, c), (b, c))
            line = LineString([p0, p1])
            if any(line.distance(x) < 30 for x in holes):
                continue
            if any(Point(p).distance(line) < style.width / 2 + 20 for p in windows):
                continue
            house.walls.append(Wall(f"{k}p{tag}{i}", p0, p1, height, base, role="interior"))
            used.append(c)
            break


def under_roof(w: Wall, ms: list[Mass], gap: float) -> None:
    """Keep a wall inside under the roof: where the roof over it comes lower than its top (a flat roof inside a
    parapet, rafters over a low top storey), its top follows the roof, `gap` under the plane."""
    L = w.length
    line = LineString([w.start, w.end])
    faces = [f for m in ms for f in m.faces if f.shape.distance(line) < 1]
    cuts = {0.0, L}
    for f in faces:
        part = line.intersection(f.shape.exterior)
        for g in getattr(part, "geoms", [part]):
            for p in getattr(g, "coords", []):
                cuts.add(min(max(math.dist(w.start, p), 0.0), L))
    ts = sorted(cuts)
    pts = []
    for a, b in zip(ts, ts[1:]):
        if b - a < 0.5:
            continue
        mid = Point(w.world((a + b) / 2, 0, 0)[:2])
        f = min(faces, key=lambda f: f.shape.distance(mid), default=None)
        for t in (a, b):
            x, y = w.world(t, 0, 0)[:2]
            pts.append((t, max(0.0, min(w.height, f.z(x, y) - gap - w.base)) if f else w.height))
    if not pts or min(z for _, z in pts) >= w.height - 0.5:
        return
    low = min(z for _, z in pts)
    if max(z for _, z in pts) - low > 0.5:
        line = [(0.0, 0.0), (round(L, 3), 0.0)] + [(round(t, 3), round(z, 3)) for t, z in reversed(pts)]
        w.outline = [p for i, p in enumerate(line) if p != line[i - 1]]
        w.height = max(min(pts[0][1], pts[-1][1]), low)
    else:
        w.height = low


def stand(w: Wall, low: float) -> bool:
    """Keep a wall whose top follows the roof to the stretch where it stands at least `low` high: where the
    roof comes lower there is no wall, the roof meets the floor. False if no stretch worth a wall is left."""
    top = w.outline[2:]
    top = sorted(top)                                    # the top's points along u; a jump has two at one u
    if min(v for _, v in top) >= low:
        return True
    keep, best = [], []
    for (ua, va), (ub, vb) in zip(top, top[1:]):
        if va < low and vb < low:
            keep = []
            continue
        a = (ua, va) if va >= low else (ua + (ub - ua) * (low - va) / (vb - va), low)
        b = (ub, vb) if vb >= low else (ua + (ub - ua) * (low - va) / (vb - va), low)
        keep = keep + [a, b] if keep and va >= low else [a, b]
        if keep[-1][0] - keep[0][0] > (best[-1][0] - best[0][0] if best else 0):
            best = list(keep)
        if vb < low:
            keep = []
    if not best or best[-1][0] - best[0][0] < 2 * KNEE:
        return False
    u0, u1 = best[0][0], best[-1][0]
    start, end = w.world(u0, 0, 0)[:2], w.world(u1, 0, 0)[:2]
    pts = [(round(u - u0, 3), round(v, 3)) for u, v in best]
    if hasattr(w, "t0"):
        w.t0 += u0
    w.start, w.end = start, end
    w.__dict__.pop("frame", None)
    w.height = min(v for _, v in pts)
    line = [(0.0, 0.0), (round(u1 - u0, 3), 0.0)] + list(reversed(pts))
    w.outline = [p for i, p in enumerate(line) if p != line[i - 1]] if max(v for _, v in pts) - w.height > 0.5 else None
    return True


def top_over(w: Wall, u0: float, u1: float) -> float:
    """The lowest the wall's top comes between u0 and u1."""
    if not w.outline:
        return w.height
    tops = []
    for (ua, va), (ub, vb) in zip(w.outline, w.outline[1:] + w.outline[:1]):
        if va <= 0 and vb <= 0:
            continue
        tops += [v for u, v in ((ua, va), (ub, vb)) if u0 - 1 <= u <= u1 + 1 and v > 0]
        tops += [va + (vb - va) * (u - ua) / (ub - ua) for u in (u0, u1) if min(ua, ub) < u < max(ua, ub)]
    return min(tops) if tops else 0.0


def clear(w: Wall, u0: float, u1: float, v1: float, margin: float = 12.0, tee: float = 24.0) -> bool:
    """True if an opening from u0 to u1 up to v1 fits the wall: clear of its ends, its other openings, the walls
    that meet it, and under its top."""
    if u0 < margin or u1 > w.length - margin:
        return False
    if any(u0 < o.u1 + margin and o.u0 - margin < u1 for o in w.openings):
        return False
    if any(u0 - tee < t.u < u1 + tee for t in w.tees):
        return False
    return top_over(w, u0, u1) >= v1 + 8.5


def cut(w: Wall, kind: str, u0: float, width: float, v0: float, v1: float, **how) -> bool:
    u0 = round(u0, 1)
    if not clear(w, u0, u0 + width, v1, **how):
        return False
    w.openings.append(Opening(f"{w.id}o{len(w.openings)}", kind, u0, u0 + width, v0, v1))
    w.openings.sort(key=lambda o: o.u0)
    return True


def openings(rng, house: House, style: Style, level: float, sides: dict) -> None:
    """Windows at each run's columns, the same columns on every storey, lower where a wall is low; a front and
    a back door; a window in a tall gable; a door or two in each wall inside. Where a brief saw a storey of a
    side, its openings are placed instead: each on the wall of that storey nearest the viewer there, moved a
    little if it must to clear the walls that meet the wall."""
    outer = [w for w in house.walls if w.role == "exterior"]
    storey = lambda w: round(w.base / level) + 1
    faces = lambda w, d: -(w.normal[0] * d[0] + w.normal[1] * d[1])
    side_of = lambda w: max(SIDES, key=lambda s: faces(w, SIDES[s]))
    seen = lambda w: (sides.get(side_of(w)) or {}).get(str(storey(w)))      # None: the brief is silent on this wall
    briefed_ = any(sides.values())
    for side, storeys in sides.items():
        d = SIDES[side]
        along = lambda p: -d[1] * p[0] + d[0] * p[1]
        ends = [along(p) for w in outer for p in (w.start, w.end)]
        r0, r1 = min(ends), max(ends)
        for k, items in (storeys or {}).items():
            for item in items or []:
                kind, c = item.get("kind", "window"), r0 + float(item["at"]) * (r1 - r0)
                over = [w for w in outer if storey(w) == int(k) and faces(w, d) > 0.5
                        and min(along(w.start), along(w.end)) - 1 <= c <= max(along(w.start), along(w.end)) + 1]
                if not over:
                    house.missed.append(f"{kind} at {item['at']} on the {side} side, storey {k}: no wall of that storey faces the side there")
                    continue
                part = lambda w: (c - along(w.start)) / (along(w.end) - along(w.start))
                depth = lambda w: (w.start[0] + part(w) * (w.end[0] - w.start[0])) * d[0] + (w.start[1] + part(w) * (w.end[1] - w.start[1])) * d[1]
                w = max(over, key=depth)
                u = min(max(part(w), 0.0), 1.0) * w.length
                ww = float(item.get("w") or (36 if kind == "door" else style.width))
                how = {}
                if w.length < ww + 26:            # a short wall (a bay's face): the opening in its middle, studs to each side
                    ww, u, how = min(ww, w.length - 12), w.length / 2, {"margin": 4.5}
                for shift in (0, 6, -6, 12, -12, 18, -18, 24, -24, 30, -30) if not how else (0,):
                    if kind == "door":
                        if ww >= 24 and cut(w, "door", u + shift - ww / 2, ww, 0.0, min(HEAD, top_over(w, u + shift - ww / 2, u + shift + ww / 2) - 9), **how):
                            house.placed += 1
                            break
                    else:
                        head = min(style.head, top_over(w, u + shift - ww / 2, u + shift + ww / 2) - 9)
                        high = min(float(item.get("h") or style.height), head - 20)
                        if ww >= 16 and high >= 22 and cut(w, "window", u + shift - ww / 2, ww, head - high, head, **how):
                            house.placed += 1
                            break
                else:
                    house.missed.append(f"{kind} at {item['at']} on the {side} side, storey {k}: no clear place on wall {w.id} ({w.length:.0f} in. long, {top_over(w, 0, w.length):.0f} high)")
    ground = [w for w in outer if w.base == 0 and w.length >= 60 and not w.abutted and seen(w) is None]
    side = rng.choice([(0, -1), (0, 1), (1, 0), (-1, 0), (1, 0), (-1, 0)])      # the street: more often off an end
    facing = lambda w, s: -w.normal[0] * s[0] - w.normal[1] * s[1]
    have = sum(o.kind == "door" for w in outer for o in w.openings)
    for s, door in ((side, 38), ((-side[0], -side[1]), 34)):
        if (door == 34 and rng.random() > 0.8) or have >= (1 if door == 38 else 2) or (briefed_ and have):
            continue
        done = False
        for w in sorted(ground, key=lambda w: (-round(facing(w, s), 1), -w.length)):
            columns = [t - w.t0 for t in w.run.columns if 0 < t - w.t0 < w.length]
            for u in sorted(columns, key=lambda u: abs(u - w.length * rng.choice([0.25, 0.5, 0.75]))) + [w.length / 2, w.length / 3]:
                if cut(w, "door", u - door / 2, door, 0.0, HEAD):
                    done = True
                    break
            if done:
                have += 1
                break
    for w in outer:                      # a porch: open between its corner posts
        if id(w.run.mass) in house.porches and seen(w) is None and not w.abutted and w.length >= 60:
            bays = 1 if w.length <= 150 else 2
            wide = (w.length - 12 * (bays + 1)) / bays
            if all([cut(w, "door", 12 + i * (wide + 12), wide, 0.0, min(HEAD, top_over(w, 0, w.length) - 9), margin=11.5, tee=6.0) for i in range(bays)]):
                house.has.add("open porch")
    if rng.random() < (0.6 if style.late else 0.2):          # a wide window, or a sliding door, on the ground storey
        for w in sorted([w for w in ground if id(w.run.mass) not in house.porches and not w.openings], key=lambda w: -w.length)[:rng.choice([1, 1, 2])]:
            spots = [t - w.t0 for t in w.run.columns if 0 < t - w.t0 < w.length] or [w.length / 2]
            u, wide = rng.choice(spots), rng.choice([72, 84, 96, 108])
            slider = style.late and rng.random() < 0.4
            if cut(w, "door", u - 36, 72, 0.0, HEAD) if slider else cut(w, "window", u - wide / 2, wide, style.head - 60, style.head):
                house.has.add("wide opening")
    for w in outer:
        if w.abutted or seen(w) is not None or id(w.run.mass) in house.porches:
            continue
        for t in w.run.columns:
            u = t - w.t0
            if not 0 < u < w.length or rng.random() < 0.08:
                continue
            ww, hh = (24, 36) if rng.random() < 0.1 else (style.width, style.height)
            head = min(style.head, top_over(w, u - ww / 2, u + ww / 2) - 9)       # lower under a low top
            hh = min(hh, head - 20)
            if hh >= 22:
                cut(w, "window", u - ww / 2, ww, head - hh, head)
        if w.outline:                       # a window under the peak of a tall gable
            u, v = max(w.outline, key=lambda p: p[1])
            if v - w.height >= 66 and rng.random() < 0.75:
                cut(w, "window", u - 14, 28, w.height + 14, w.height + 14 + 40)
    for w in house.walls:
        if w.role != "interior" or w.length < 60:
            continue
        bearing = w.id[1] in "sj"
        if w.id[1] == "s" and w.height >= HEAD + 9 and rng.random() < (0.4 if w.base == 0 else 0.1):
            # a bearing line opened up: a beam on posts, a pier left at each end and where a wall meets it
            marks = [0.0] + [t.u for t in w.tees] + [w.length]
            for a, b in zip(marks, marks[1:]):
                wide = min(b - a - 40, 192.0)
                if wide >= 96 and cut(w, "door", (a + b - wide) / 2, wide, 0.0, HEAD, tee=6.0):
                    house.has.add("posts and a beam")
            if any(o.width >= 96 for o in w.openings):
                continue
        for i in range(max(1, int(w.length // 192)) if bearing else int(rng.random() < 0.6)):
            wide = rng.choice([34, 34, 34, 60, 72]) if bearing else 34
            for _ in range(30):
                if cut(w, "door", 2.0 * round(rng.uniform(12, max(13, w.length - 12 - wide)) / 2), wide, 0.0, min(HEAD, w.height - 9)):
                    break


def rooms_of(house: House, base: float, stair):
    """A storey's rooms (the regions its walls close), which rooms each door joins, and the rooms that can be
    reached: from the outside doors on the ground floor, from the stair above. Returns (walls, rooms, sides,
    links, reached); sides(wall, u) gives the rooms on the two sides of a wall at u."""
    walls = [w for w in house.walls if w.base == base]
    lines = []
    for w in walls:
        d = w.dir
        lines.append(LineString([(w.start[0] - d[0], w.start[1] - d[1]), (w.end[0] + d[0], w.end[1] + d[1])]))
    rooms = [r for r in polygonize(unary_union(lines)) if r.area > 8 * 144] if lines else []

    def room(p) -> int | None:
        return next((i for i, r in enumerate(rooms) if r.contains(Point(p))), None)

    def sides(w: Wall, u: float) -> tuple:
        return room(w.world(u, 0, 5.0)[:2]), room(w.world(u, 0, -5.0)[:2])
    links = {i: set() for i in range(len(rooms))}
    reached = set()
    for w in walls:
        for o in w.openings:
            if o.kind != "door":
                continue
            a, b = sides(w, (o.u0 + o.u1) / 2)
            if a is not None and b is not None:
                links[a].add(b), links[b].add(a)
            elif w.role == "exterior":
                reached |= {x for x in (a, b) if x is not None}
    if stair is not None:
        reached |= {i for i, r in enumerate(rooms) if r.intersects(stair)}
    if not reached and rooms:
        reached = {max(range(len(rooms)), key=lambda i: rooms[i].area)}
    spread(links, reached)
    return walls, rooms, sides, links, reached


def spread(links: dict, reached: set) -> None:
    todo = list(reached)
    while todo:
        for b in links[todo.pop()] - reached:
            reached.add(b)
            todo.append(b)


def connect(house: House, base: float, stair) -> None:
    """Doors until every room on a storey can be reached: a room that cannot be gets a door in a wall it shares
    with one that can."""
    walls, rooms, sides, links, reached = rooms_of(house, base, stair)
    while len(reached) < len(rooms):
        for w in sorted(walls, key=lambda w: (w.role != "interior", -w.length)):      # a wall between two rooms, whatever its role
            hit = False
            for u in [w.length / 2] + [x + 0.0 for x in range(24, int(w.length) - 23, 6)]:
                a, b = sides(w, u)
                if a is None or b is None or (a in reached) == (b in reached):
                    continue
                if cut(w, "door", u - 17, 34, 0.0, min(HEAD, w.height - 9), margin=4.0, tee=4.0):
                    links[a].add(b), links[b].add(a)
                    spread(links, reached)
                    hit = True
                    break
            if hit:
                break
        else:
            return          # a room no door can reach: closed in by short walls
