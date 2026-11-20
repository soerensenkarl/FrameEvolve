"""Detail an envelope into a House: everything a real building model does not record, made up to fit it.

The envelope gives masses with their roofs (envelope.py); the assessor's record gives the storeys and the year.
From those, with a seeded random choice wherever a real house could differ:

  levels     a storey height by the house's age, as many storeys as the record says, and what is left of the
             main mass's height over the ground taken off as foundation; each mass gets the storeys its own
             eave reaches
  roofs      every roof face a roof plane, its eave edges pushed out for an overhang
  walls      each storey's exterior walls around the masses that reach it, a junction wall where two meet; a
             top wall follows the roof, a raised heel under the plane at an eave
  floors     a floor at every level over the masses that reach it, a ceiling on each mass's top walls
  inside     bearing walls so no floor spans too far, partitions between them, a stair through every floor
  openings   windows in columns that line up over the storeys, a front and a back door, a window in a tall gable,
             doors through the walls inside

Everything is a surface with its openings, as the generator's houses are. Inches.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from frameevolve.envelope import FLAT, Envelope, Face, Mass, eave, free
from frameevolve.houses import EAVE, HEAD, HEEL, SPAN, plane
from frameevolve.model import Floor, House, Opening, Wall

JOISTS = 10.875     # a floor's depth with its subfloor: a level less a wall's height
PLATES = (97.125, 109.125)   # wall heights for 92 5/8" and 104 5/8" precut studs
KNEE = 24.0         # a wall lower than this is not built: the roof comes down to the floor
ROOM = 78.0         # a top wall this high has a flat ceiling on it; lower, the room is under the rafters
STAIR = (36.0, 120.0)


@dataclass
class Run:
    """A straight stretch of a mass's outline, counter-clockwise, with the windows' places along it."""
    mass: Mass
    a: tuple
    b: tuple
    columns: list

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)

    def at(self, t: float) -> tuple:
        L = self.length
        return (self.a[0] + (self.b[0] - self.a[0]) * t / L, self.a[1] + (self.b[1] - self.a[1]) * t / L)


def detail(env: Envelope, record: dict, seed: int = 0, id: str = "") -> House:
    """A complete House on an envelope, by the assessor's record of it."""
    rng = random.Random(f"{id}/{seed}")
    year = int(record.get("condition_yearbuilt") or 1900)
    ms = sorted(env.masses, key=lambda m: -m.shape.area)
    eaves = {id_(m): eave(m, ms) for m in ms}
    level, plate, cut, top = levels(rng, eaves[id_(ms[0])], float(record.get("exterior_numstories") or 2), year)
    ms = [m for m in ms if eaves[id_(m)] - HEEL - cut >= ROOM - HEEL]
    for m in ms:                          # the foundation is taken off: z = 0 is the ground floor
        for f in m.faces:
            f.c -= cut
    E = {id_(m): eaves[id_(m)] - HEEL - cut for m in ms}                     # each mass's wall top
    n = {id_(m): 1 + sum(E[id_(m)] - k * level >= KNEE for k in range(1, 9)) for m in ms}
    E[id_(ms[0])] = (n[id_(ms[0])] - 1) * level + top                        # the main mass, exactly
    house = House(id, [], kind=(record.get("exterior_style") or "").lower())
    house.foundation = cut            # how far the ground lies under the ground floor
    runs = {id_(m): outline_runs(m) for m in ms}
    for k in range(1, max(n.values()) + 1):
        here = [m for m in ms if n[id_(m)] >= k]
        storey_walls(house, k, here, runs, E, n, level)
        if k > 1:
            for j, piece in enumerate(pieces(unary_union([m.shape.buffer(0.5, join_style=2) for m in here]).buffer(-0.5, join_style=2))):
                house.floors.append(Floor(f"f{k}" + "abcdefgh"[j - 1] * (j > 0), ring(piece), (k - 1) * level))
    for j, m in enumerate(ms):
        h = E[id_(m)] - (n[id_(m)] - 1) * level
        main_face = max(m.faces, key=lambda f: f.shape.area)
        if h >= ROOM and main_face.slope >= FLAT:
            ax = (abs(main_face.b), abs(main_face.a)) if abs(main_face.b) >= abs(main_face.a) else (abs(main_face.b), abs(main_face.a))
            s = math.hypot(*ax)
            house.floors.append(Floor(f"c{j}" if j else "c", ring(m.shape), E[id_(m)], role="ceiling", axis=(ax[0] / s, ax[1] / s)))
    for j, (m, f) in enumerate((m, f) for m in ms for f in m.faces):
        house.roofs.append(roof(f"r{j + 1}", f, m, ms))
    stair = stair_place(rng, ms[0], level) if n[id_(ms[0])] > 1 else None
    for k in range(1, max(n.values()) + 1):
        for j, m in enumerate(m for m in ms if n[id_(m)] >= k):
            h = level if k < n[id_(m)] else E[id_(m)] - (k - 1) * level
            inside(rng, house, k, j, m, h, (k - 1) * level, stair)
    house.link()
    if stair:
        for f in house.floors:
            if f.role == "floor" and Polygon(f.outline).contains(stair.buffer(6)):
                x0, y0, x1, y1 = stair.bounds
                (u0, v0, _), (u1, v1, _) = f.local((x0, y0, f.z)), f.local((x1, y1, f.z))
                f.openings.append(Opening(f"{f.id}o0", "stair", min(u0, u1), max(u0, u1), min(v0, v1), max(v0, v1)))
    openings(rng, house, runs, year, plate)
    house.link()
    return house


def id_(m: Mass) -> int:
    return id(m)


def levels(rng, eave_z: float, storeys: float, year: int) -> tuple[float, float, float, float]:
    """(level, wall height, foundation, top wall height) for a main mass whose eave stands eave_z over the
    ground: a storey height by the house's age; the record's count of full storeys unless the height says
    otherwise; the rest is foundation, or, where the eave is too low for a full top storey, a lower top wall."""
    plate = PLATES[1] if rng.random() < (0.7 if year < 1940 else 0.2) else PLATES[0]
    wall_top = eave_z - HEEL
    best = None
    for p in (plate, PLATES[0], PLATES[1]):
        lv = p + JOISTS
        for n in range(1, 5):
            cut = wall_top - (n - 1) * lv - p
            cost = abs(cut - 18) if cut >= 0 else 3 * -cut
            cost += 45 * abs(n - max(1, math.floor(storeys))) + (0 if p == plate else 10)
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


def outline_runs(m: Mass) -> list[Run]:
    pts = ring(m.shape)
    return [Run(m, a, b, []) for a, b in zip(pts, pts[1:] + pts[:1])]


def top_at(run: Run, t: float, side: float = 0.0) -> float:
    """How high the mass's wall stands at t along a run: up to the roof face that ends over it there, less a
    raised heel where that edge is an eave (level, with the roof rising from it)."""
    m = run.mass
    x, y = run.at(min(max(t + side, 0.01), run.length - 0.01))
    L = run.length
    nx, ny = -(run.b[1] - run.a[1]) / L, (run.b[0] - run.a[0]) / L     # inward
    p = Point(x + 1.5 * nx, y + 1.5 * ny)
    f = min(m.faces, key=lambda f: f.shape.distance(p))
    z = f.z(x, y)
    if f.slope >= FLAT:
        gx, gy = f.a / f.slope, f.b / f.slope                      # uphill
        if gx * nx + gy * ny > 0.98:
            return z - HEEL
    else:
        return z - HEEL
    return z


def profile(run: Run, t0: float, t1: float) -> list[tuple]:
    """The wall top from t0 to t1 along a run as (t, z) points: straight between the points where the roof face
    over the wall changes."""
    m = run.mass
    cuts = {t0, t1}
    line = LineString([run.at(t0), run.at(t1)])
    for f in m.faces:
        for p in f.shape.exterior.coords:
            if line.distance(Point(p)) < 1.5:
                t = math.dist(run.a, p)
                if t0 + 1 < t < t1 - 1:
                    cuts.add(t)
    ts = sorted(cuts)
    out = []
    for a, b in zip(ts, ts[1:]):
        out += [(a, top_at(run, a, 0.5)), (b, top_at(run, b, -0.5))]
    return out


def storey_walls(house: House, k: int, here: list[Mass], runs, E, n, level: float) -> None:
    """Storey k's walls around the masses that reach it: exterior where a run has no other such mass beyond
    it, a junction wall (framed by the mass with the higher eave) where it has."""
    base = (k - 1) * level
    count = {"w": 0, "j": 0}
    for m in here:
        for run in runs[id_(m)]:
            L = run.length
            shared = []
            for o in here:
                if o is m:
                    continue
                part = LineString([run.a, run.b]).intersection(o.shape.exterior.buffer(1.5))
                for g in getattr(part, "geoms", [part]):
                    if g.geom_type == "LineString" and g.length > 6:
                        ts = sorted(math.dist(run.a, p) for p in g.coords)
                        shared.append((ts[0], ts[-1], o))
            shared.sort(key=lambda s: s[0])
            t = 0.0
            spans = []
            for t0, t1, o in shared:
                if t0 - t > 6:
                    spans.append((t, t0, None))
                spans.append((t0, t1, o))
                t = max(t, t1)
            if L - t > 6:
                spans.append((t, L, None))
            for t0, t1, o in spans:
                if o is not None and (E[id_(o)], o.shape.area) > (E[id_(m)], m.shape.area):
                    continue                      # the other mass frames this junction wall
                pts = [(t, z - base) for t, z in profile(run, t0, t1)]
                if k < n[id_(m)]:
                    pts = [(t, min(z, level)) for t, z in pts]
                    if min(z for _, z in pts) > level - 3:
                        pts = [(t0, level), (t1, level)]
                elif all(abs(z - (E[id_(m)] - base)) < 3 for _, z in pts):
                    pts = [(t0, E[id_(m)] - base), (t1, E[id_(m)] - base)]
                pts = [(t, max(z, 0.0)) for t, z in pts]
                if max(z for _, z in pts) < KNEE:
                    continue
                kind = "j" if o is not None else "w"
                w = Wall(f"{k}{kind}{count[kind]}", run.at(t0), run.at(t1), min(z for _, z in pts if z > 0) if any(z > 0 for _, z in pts) else 0,
                         base, role="interior" if o is not None else "exterior")
                if max(z for _, z in pts) - min(z for _, z in pts) > 0.5:
                    top = [(round(t - t0, 3), round(z, 3)) for t, z in reversed(pts)]
                    line = [(0.0, 0.0), (round(t1 - t0, 3), 0.0)] + top
                    w.outline = [p for i, p in enumerate(line) if p != line[i - 1]]
                    w.height = max(min(pts[0][1], pts[-1][1]), min(z for _, z in pts))
                w.run, w.t0 = run, t0
                house.walls.append(w)
                count[kind] += 1


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
        e = (gy, -gx)
    else:
        e = (1.0, 0.0)
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
    """The stretches of the line x = c (or y = c) inside a shape."""
    x0, y0, x1, y1 = shape.bounds
    line = LineString([(x0 - 1, c), (x1 + 1, c)] if along_x else [(c, y0 - 1), (c, y1 + 1)])
    part = shape.intersection(line)
    out = []
    for g in getattr(part, "geoms", [part]):
        if g.geom_type == "LineString" and g.length > 1:
            vs = sorted(p[0 if along_x else 1] for p in g.coords)
            out.append((vs[0], vs[-1]))
    return out


def spines(m: Mass) -> tuple[bool, list[float]]:
    """Where a mass needs bearing walls so that no floor in it spans further than SPAN: (they run along x,
    their places). They run the long way; each is put in the middle of the deepest stretches left."""
    x0, y0, x1, y1 = m.shape.bounds
    along_x = x1 - x0 >= y1 - y0
    lo, hi = (x0, x1) if along_x else (y0, y1)
    if min(x1 - x0, y1 - y0) <= SPAN:
        return along_x, []
    at: list[float] = []
    for _ in range(3):
        deep = []
        for c in [lo + 12 * i for i in range(1, int((hi - lo) // 12))]:
            for a, b in scan(m.shape, c, not along_x):
                marks = [a] + sorted(s for s in at if a < s < b) + [b]
                deep += [(p + q) / 2 for p, q in zip(marks, marks[1:]) if q - p > SPAN]
        if not deep:
            break
        deep.sort()
        at.append(2.0 * round(deep[len(deep) // 2] / 2))
    return along_x, sorted(at)


def stair_place(rng, m: Mass, level: float):
    """A stair opening in the main mass, its long side across the bearing walls and clear of them."""
    along_x, at = spines(m)
    room = m.shape.buffer(-18)
    x0, y0, x1, y1 = m.shape.bounds
    for i in range(400):
        w, d = STAIR if along_x == (i < 200) else STAIR[::-1]
        x, y = rng.uniform(x0, x1 - w), rng.uniform(y0, y1 - d)
        x, y = 2.0 * round(x / 2), 2.0 * round(y / 2)
        r = box(x, y, x + w, y + d)
        lo, hi = (y, y + d) if along_x else (x, x + w)
        if room.contains(r) and all(not (lo - 12 < s < hi + 12) for s in at):
            return r
    return None


def inside(rng, house: House, k: int, j: int, m: Mass, height: float, base: float, stair) -> None:
    """A mass's walls inside on storey k: its bearing walls, and partitions from one bearing line to the next."""
    if height < KNEE:
        return
    along_x, at = spines(m)
    tag = f"{j}" if j else ""
    for i, s in enumerate(at):
        for q, (a, b) in enumerate(scan(m.shape, s, along_x)):
            if b - a >= 48:
                p0, p1 = ((a, s), (b, s)) if along_x else ((s, a), (s, b))
                house.walls.append(Wall(f"{k}s{tag}{'abc'[i]}{q or ''}", p0, p1, height, base, role="interior"))
    x0, y0, x1, y1 = m.shape.bounds
    lo, hi = (x0, x1) if along_x else (y0, y1)
    want = max(0, min(4, round(m.shape.area / 144 / 320) - 1 + rng.choice([-1, 0, 0, 1])))
    used: list[float] = []
    for i in range(want):
        for _ in range(40):
            if hi - lo < 150:
                break
            c = 2.0 * round(rng.uniform(lo + 72, hi - 72) / 2)
            if any(abs(c - u) < 72 for u in used):
                continue
            bays = []
            for a, b in scan(m.shape, c, not along_x):
                marks = [a] + [s for s in at if a < s < b] + [b]
                bays += [(p, q) for p, q in zip(marks, marks[1:]) if q - p >= 60]
            if not bays:
                continue
            a, b = rng.choice(bays)
            p0, p1 = ((c, a), (c, b)) if along_x else ((a, c), (b, c))
            if stair is not None and LineString([p0, p1]).distance(stair) < 30:
                continue
            house.walls.append(Wall(f"{k}p{tag}{i}", p0, p1, height, base, role="interior"))
            used.append(c)
            break


def clear(w: Wall, u0: float, u1: float, v1: float, margin: float = 12.0) -> bool:
    """True if an opening from u0 to u1 up to v1 fits the wall: clear of its ends, its other openings, the walls
    that meet it, and under its top."""
    if u0 < margin or u1 > w.length - margin:
        return False
    if any(u0 < o.u1 + margin and o.u0 - margin < u1 for o in w.openings):
        return False
    if any(u0 - 24 < t.u < u1 + 24 for t in w.tees):
        return False
    if w.outline:
        tops = [v for a, b in zip(w.outline, w.outline[1:] + w.outline[:1]) for u, v in [a, b]
                if v > 0 and u0 - 1 <= u <= u1 + 1]
        for (ua, va), (ub, vb) in zip(w.outline, w.outline[1:] + w.outline[:1]):
            for u in (u0, u1):
                if min(ua, ub) < u < max(ua, ub) and (va > 0 or vb > 0):
                    tops.append(va + (vb - va) * (u - ua) / (ub - ua))
        return bool(tops) and min(tops) >= v1 + 9
    return w.height >= v1 + 9


def cut(w: Wall, kind: str, u0: float, width: float, v0: float, v1: float) -> bool:
    u0 = round(u0, 1)
    if not clear(w, u0, u0 + width, v1):
        return False
    w.openings.append(Opening(f"{w.id}o{len(w.openings)}", kind, u0, u0 + width, v0, v1))
    w.openings.sort(key=lambda o: o.u0)
    return True


def openings(rng, house: House, runs, year: int, plate: float) -> None:
    """Windows in columns along each run of the outline, the same columns on every storey; a front and a back
    door; a window in a tall gable; doors through the walls inside."""
    old = year < 1940
    width = rng.choice([28, 30, 32, 36] if old else [30, 36, 48, 60])
    height = rng.choice([54, 60, 62] if old else [36, 48, 54])
    head = HEAD if plate < 105 or rng.random() < 0.4 else rng.choice([90.0, 96.0])
    pitch = rng.uniform(96, 144)
    for rs in runs.values():
        for run in rs:
            count = int((run.length - 30) // pitch)
            run.columns = [(i + 0.5) * run.length / count for i in range(count)] if count else \
                ([run.length / 2] if run.length >= width + 40 else [])
    outer = [w for w in house.walls if w.role == "exterior"]
    ground = [w for w in outer if w.base == 0 and w.length >= 72]
    if ground:
        xs = [p[0] for w in ground for p in (w.start, w.end)]
        ys = [p[1] for w in ground for p in (w.start, w.end)]
        side = rng.choice([(0, -1), (0, 1), (1, 0), (-1, 0), (1, 0), (-1, 0)])      # the street: more often off an end
        facing = lambda w, s: -w.normal[0] * s[0] - w.normal[1] * s[1] > 0.9
        for s, door in ((side, 38), ((-side[0], -side[1]), 34)):
            walls = sorted([w for w in ground if facing(w, s)], key=lambda w: -w.length)
            if walls and (door == 38 or rng.random() < 0.8):
                w = walls[0]
                spots = sorted((t - w.t0 for t in w.run.columns), key=lambda u: abs(u - w.length * rng.choice([0.25, 0.5, 0.75])))
                for u in spots + [w.length / 2, w.length / 3]:
                    if cut(w, "door", u - door / 2, door, 0.0, HEAD):
                        break
    for w in outer:
        for t in w.run.columns:
            u = t - w.t0
            if rng.random() < 0.12:
                continue
            small = rng.random() < 0.12
            ww, hh = (24, 36) if small else (width, height)
            cut(w, "window", u - ww / 2, ww, head - hh, head)
        if w.outline:                       # a window under the peak of a tall gable
            u, v = max(w.outline, key=lambda p: p[1])
            if v - w.height >= 66 and rng.random() < 0.75:
                cut(w, "window", u - 14, 28, w.height + 14, w.height + 14 + 40)
    for w in house.walls:
        if w.role != "interior" or w.length < 60:
            continue
        doors = max(1, int(w.length // 168)) if w.id[1] in "sj" else int(rng.random() < 0.7)
        for i in range(doors):
            wide = rng.choice([34, 34, 34, 60, 72]) if w.id[1] in "sj" else 34
            for _ in range(30):
                if cut(w, "door", 2.0 * round(rng.uniform(12, max(13, w.length - 12 - wide)) / 2), wide, 0.0, HEAD):
                    break
