"""A building model as an envelope: its flat roof faces, grouped into the masses the building is made of.

The city's models are roofs dropped to the ground: every plan point has one roof over it, and walls stand where
the roof ends or steps. So a model is read as its roof faces (a plane and a shape in plan each); faces that meet
along an edge in space (a ridge, a hip, a valley) are one mass, and where the roof steps there are two: a main
block, a wing, a bay, a porch, a dormer. What a framed House cannot say is taken off here: a chimney is dropped,
a dormer is closed over by the roof it stands on, and what is too low to stand in (steps, a deck) is left out.
The envelope is turned so its walls run along x and y, its lowest ground at z = 0. Inches.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

FLAT = 1 / 12        # a roof face under 1:12 is flat: no eave, no ceiling under it
WELD = 0.5           # vertices closer than this are one, inches
CHIMNEY = 25 * 144   # a mass smaller than this in plan is a chimney or a vent, square inches
DORMER = 200 * 144   # a mass smaller than this that mostly stands on other roofs is a dormer
LOW = 78.0           # a mass whose roof starts lower than this over the ground is not a room: steps, a deck
Pt = tuple[float, float]


@dataclass
class Face:
    """A flat roof face: its plane z = a x + b y + c and its shape in plan."""
    a: float
    b: float
    c: float
    shape: Polygon
    mass: int = -1

    def z(self, x: float, y: float) -> float:
        return self.a * x + self.b * y + self.c

    @property
    def slope(self) -> float:
        return math.hypot(self.a, self.b)

    @property
    def edges(self) -> list[tuple[Pt, Pt]]:
        """The edges of its outline, counter-clockwise: the face lies to the left of each."""
        ring = list(self.shape.exterior.coords)
        return list(zip(ring, ring[1:]))


@dataclass
class Mass:
    """Roof faces that meet in space, and the ground they cover."""
    faces: list[Face]
    shape: Polygon = field(default=None)

    def z(self, x: float, y: float) -> float:
        """The roof's height over a point of the mass (or just beside it)."""
        p = Point(x, y)
        return min(self.faces, key=lambda f: f.shape.distance(p)).z(x, y)


def read(path) -> tuple[list, list]:
    """An OBJ file's vertices (welded, inches, z from the lowest) and triangles."""
    vs, index, tris = [], {}, []
    raw = []
    for line in Path(path).read_text().splitlines():
        p = line.split()
        if p[:1] == ["v"]:
            raw.append(tuple(12 * float(x) for x in p[1:4]))
        elif p[:1] == ["f"]:
            ids = [int(x.split("/")[0]) - 1 for x in p[1:]]
            tris += [(ids[0], ids[i], ids[i + 1]) for i in range(1, len(ids) - 1)]
    z0 = min(v[2] for v in raw)
    remap = []
    for x, y, z in raw:
        key = (round(x / WELD), round(y / WELD), round((z - z0) / WELD))
        if key not in index:
            index[key] = len(vs)
            vs.append((x, y, z - z0))
        remap.append(index[key])
    tris = [tuple(remap[i] for i in t) for t in tris]
    return vs, [t for t in tris if len(set(t)) == 3]


def _normal(a, b, c):
    u, v = (b[0] - a[0], b[1] - a[1], b[2] - a[2]), (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def roof_faces(vs, tris) -> list[Face]:
    """The model's roof triangles joined into flat faces: neighbours across an edge that lie in one plane."""
    roofs = []
    for t in tris:
        n = _normal(*(vs[i] for i in t))
        size = math.sqrt(sum(x * x for x in n))
        if size > 1e-6 and n[2] / size > 0.05:
            roofs.append((t, tuple(x / size for x in n), size / 2))
    by_edge = defaultdict(list)
    for k, (t, _, _) in enumerate(roofs):
        for i in range(3):
            by_edge[frozenset((t[i], t[(i + 1) % 3]))].append(k)
    group = list(range(len(roofs)))

    def find(k):
        while group[k] != k:
            group[k] = group[group[k]]
            k = group[k]
        return k
    for ks in by_edge.values():
        for k in ks[1:]:
            n, m = roofs[ks[0]][1], roofs[k][1]
            if sum(a * b for a, b in zip(n, m)) > 1 - 2e-4:      # within about a degree
                group[find(k)] = find(ks[0])
    sets = defaultdict(list)
    for k in range(len(roofs)):
        sets[find(k)].append(k)
    out = []
    for ks in sets.values():
        shape = unary_union([Polygon([vs[i][:2] for i in roofs[k][0]]) for k in ks]).buffer(0)
        if shape.geom_type != "Polygon" or shape.area < 144:
            shape = max(getattr(shape, "geoms", [shape]), key=lambda g: g.area) if not shape.is_empty else shape
            if shape.is_empty or shape.area < 144:
                continue
        area = sum(roofs[k][2] for k in ks)
        n = [sum(roofs[k][1][i] * roofs[k][2] for k in ks) / area for i in range(3)]
        pts = [vs[i] for k in ks for i in roofs[k][0]]
        c = sum(n[0] * p[0] + n[1] * p[1] + n[2] * p[2] for p in pts) / len(pts)
        out.append(Face(-n[0] / n[2], -n[1] / n[2], c / n[2], Polygon(shape.exterior).buffer(0)))
    return [f for f in out if f.shape.geom_type == "Polygon"]


def _along(e, g, tol=1.5) -> float:
    """How far two plan edges run along each other, in opposite directions (as the two sides of a shared edge do)."""
    (ax, ay), (bx, by) = e
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-6:
        return 0.0
    ux, uy = (bx - ax) / L, (by - ay) / L
    ts = []
    for px, py in g:
        if abs((px - ax) * -uy + (py - ay) * ux) > tol:
            return 0.0
        ts.append((px - ax) * ux + (py - ay) * uy)
    if ts[0] < ts[1]:
        return 0.0
    return max(0.0, min(L, ts[0]) - max(0.0, ts[1]))


def masses(faces: list[Face]) -> list[Mass]:
    """Faces grouped into masses: two faces are one mass where their outlines share an edge at one height."""
    group = list(range(len(faces)))

    def find(k):
        while group[k] != k:
            group[k] = group[group[k]]
            k = group[k]
        return k
    for i, f in enumerate(faces):
        for j in range(i + 1, len(faces)):
            g = faces[j]
            if find(i) == find(j) or f.shape.distance(g.shape) > 1:
                continue
            for e in f.edges:
                for h in g.edges:
                    if _along(e, h) > 6:
                        mx, my = (max(min(e[0][0], e[1][0]), min(h[0][0], h[1][0])) + min(max(e[0][0], e[1][0]), max(h[0][0], h[1][0]))) / 2, \
                                 (max(min(e[0][1], e[1][1]), min(h[0][1], h[1][1])) + min(max(e[0][1], e[1][1]), max(h[0][1], h[1][1]))) / 2
                        if abs(f.z(mx, my) - g.z(mx, my)) < 3:
                            group[find(j)] = find(i)
                            break
                else:
                    continue
                break
    sets = defaultdict(list)
    for k, f in enumerate(faces):
        sets[find(k)].append(f)
    out = [Mass(fs) for fs in sets.values()]
    for k, m in enumerate(out):
        m.shape = _solid(unary_union([f.shape.buffer(0.25, join_style=2) for f in m.faces]).buffer(-0.25, join_style=2))
        for f in m.faces:
            f.mass = k
    return out


def _solid(shape) -> Polygon:
    """The largest piece of a shape, without its holes."""
    piece = max(getattr(shape, "geoms", [shape]), key=lambda g: g.area)
    return Polygon(piece.exterior)


def eave(m: Mass, others: list[Mass]) -> float:
    """The height a mass's walls reach: the middle, by length, of its level free edges that the roof rises from;
    for a flat roof, the roof."""
    levels = []
    for f in m.faces:
        if f.slope < FLAT:
            levels.append((f.z(*f.shape.representative_point().coords[0]), f.shape.length))
            continue
        for (a, b) in f.edges:
            za, zb = f.z(*a), f.z(*b)
            L = math.dist(a, b)
            if L < 6 or abs(za - zb) > 1.5 or not free(f, a, b, m):
                continue
            c = f.shape.centroid
            if f.z(c.x, c.y) > (za + zb) / 2 + 1:
                levels.append(((za + zb) / 2, L))
    if not levels:
        return min(f.z(x, y) for f in m.faces for x, y in f.shape.exterior.coords)
    levels.sort()
    half, run = sum(L for _, L in levels) / 2, 0.0
    for z, L in levels:
        run += L
        if run >= half:
            return z
    return levels[-1][0]


def free(f: Face, a: Pt, b: Pt, m: Mass) -> bool:
    """True if edge a-b of face f is on the edge of its mass: no other face of the mass on its other side."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    L = math.dist(a, b)
    nx, ny = (b[1] - a[1]) / L, -(b[0] - a[0]) / L        # outward: to the right of a counter-clockwise edge
    p = Point(mx + 2 * nx, my + 2 * ny)
    return not any(g is not f and g.shape.contains(p) for g in m.faces)


@dataclass
class Envelope:
    masses: list[Mass]
    turn: float              # the angle the model was turned by, radians, about `about`, before `shift` was taken off
    about: Pt
    shift: Pt
    dropped: dict            # what was taken off, by kind: chimney, dormer, low
    z0: float = 0.0          # the model's lowest point, inches

    def place(self, p) -> tuple:
        """A point of the model (feet, as in its file) in the envelope's coordinates."""
        x, y, z = 12 * p[0], 12 * p[1], 12 * p[2] - self.z0
        c, s = math.cos(self.turn), math.sin(self.turn)
        dx, dy = x - self.about[0], y - self.about[1]
        return (self.about[0] + dx * c - dy * s - self.shift[0], self.about[1] + dx * s + dy * c - self.shift[1], z)


def grounded(m: Mass, all_: Polygon) -> float:
    """The share of a mass's outline that is the building's outline: where its walls reach the ground."""
    edge = m.shape.exterior
    return edge.intersection(all_.exterior.buffer(1.0)).length / edge.length


def close_over(d: Mass, rest: list[Mass]) -> None:
    """Give a dormer's ground to the roof faces around it: each point to the face that is lowest there, as a
    roof without the dormer would run (faces meeting in a hip or a ridge)."""
    near = [f for m in rest for f in m.faces if f.shape.distance(d.shape) < 1.5]
    if not near:
        return
    hole = d.shape.buffer(0.75, join_style=2)
    x0, y0, x1, y1 = hole.bounds
    far = 1e5
    for f in near:
        part = hole
        for g in near:
            if g is f:
                continue
            a, b, c = f.a - g.a, f.b - g.b, f.c - g.c          # f is the lower where a x + b y + c <= 0
            n = math.hypot(a, b)
            if n < 1e-9:
                if c > 0:
                    part = Polygon()
                continue
            px, py = -a * c / n ** 2, -b * c / n ** 2            # a point on the line where the two are level
            tx, ty = -b / n, a / n
            half = Polygon([(px + far * tx, py + far * ty), (px - far * tx, py - far * ty),
                            (px - far * tx - far * a / n, py - far * ty - far * b / n),
                            (px + far * tx - far * a / n, py + far * ty - far * b / n)])
            part = part.intersection(half)
        if not part.is_empty and part.area > 1:
            grown = unary_union([f.shape, part]).buffer(0)
            f.shape = _solid(grown)


def envelope(path) -> Envelope:
    """Read a building model: its masses with chimneys dropped, dormers closed over and low things left out,
    turned square to x and y with its longest roof's eave along x, shifted to start at the origin."""
    vs, tris = read(path)
    ms = masses(roof_faces(vs, tris))
    if not ms:
        raise ValueError("no roof faces")
    dropped = defaultdict(int)
    while True:                           # take off the smallest thing that is not a room, until none is left
        all_ = _solid(unary_union([m.shape.buffer(0.5, join_style=2) for m in ms]).buffer(-0.5, join_style=2))
        small = [m for m in sorted(ms, key=lambda m: m.shape.area) if len(ms) > 1 and
                 (m.shape.area < CHIMNEY or (m.shape.area < DORMER and grounded(m, all_) < 0.5))]
        if not small:
            break
        m = small[0]
        ms.remove(m)
        if grounded(m, all_) < 0.5:
            close_over(m, ms)
            dropped["chimney" if m.shape.area < CHIMNEY else "dormer"] += 1
        else:
            dropped["chimney"] += 1
        for k in ms:
            k.shape = _solid(unary_union([f.shape.buffer(0.25, join_style=2) for f in k.faces]).buffer(-0.25, join_style=2))
    low = [m for m in ms if eave(m, ms) < LOW]
    if len(low) < len(ms):
        dropped["low"] = len(low)
        ms = [m for m in ms if m not in low]
    main = max(ms, key=lambda m: m.shape.area)
    f = max(main.faces, key=lambda f: f.shape.area)
    angle = -math.atan2(f.a, -f.b) if f.slope >= FLAT else -_longest(main.shape)
    about = main.shape.centroid.coords[0]
    for m in ms:
        m.shape = affinity.rotate(m.shape, angle, origin=about, use_radians=True)
        for g in m.faces:
            turn(g, angle, about)
    x0, y0 = unary_union([m.shape for m in ms]).bounds[:2]
    for m in ms:
        m.shape = affinity.translate(m.shape, -x0, -y0)
        for g in m.faces:
            g.shape = affinity.translate(g.shape, -x0, -y0)
            g.c += g.a * x0 + g.b * y0
    return Envelope(ms, angle, about, (x0, y0), dict(dropped), 12 * min(float(l.split()[3]) for l in Path(path).read_text().splitlines() if l.startswith('v ')))


def _longest(shape: Polygon) -> float:
    """The direction of a shape's longest edge, radians."""
    ring = list(shape.exterior.coords)
    a, b = max(zip(ring, ring[1:]), key=lambda e: math.dist(*e))
    return math.atan2(b[1] - a[1], b[0] - a[0])


def turn(f: Face, angle: float, about: Pt) -> None:
    """Turn a face about a point in plan."""
    c, s = math.cos(angle), math.sin(angle)
    ox, oy = about
    a, b = f.a * c - f.b * s, f.a * s + f.b * c
    f.c += f.a * ox + f.b * oy - a * ox - b * oy
    f.a, f.b = a, b
    f.shape = affinity.rotate(f.shape, angle, origin=about, use_radians=True)
