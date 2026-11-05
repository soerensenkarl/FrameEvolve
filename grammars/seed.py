"""Hand-written seed grammar: advanced platform framing.

Exterior walls 2x6 and partitions 2x4, studs at 24" on one grid from the house's corner, so storeys and joists
line up. Single bottom and top plates. Two-stud corners and ladder junctions: blocking every 24" catches the
drywall. Jacks and headers only in bearing walls (exterior walls, and any wall under a floor), single-ply
headers on the outside; elsewhere a flat head nailed between the kings. Cripples only on the layout.
Floors: a 2x12 rim along the outline, joists at 24" cut over walls below that cross them, a joist along any
partition above or below that runs with them, and stair openings trimmed and headed with doubled 2x12s.
Inches.
"""
from frameevolve.builder import rule
from frameevolve.geometry import scan

T = 1.5
SPACING = 24
MAX_PIECE = 240                          # longest stock, 20 ft
JOIST, JOIST_DEPTH = "2x12", 11.25
DEPTH = {"2x4": 3.5, "2x6": 5.5, "2x8": 7.25, "2x10": 9.25, "2x12": 11.25}
HEADERS = [(42, "2x4"), (65, "2x6"), (82, "2x8"), (101, "2x10"), (117, "2x12")]   # clear span: section


def section(w):
    return "2x6" if w.role == "exterior" else "2x4"


def depth(w):
    return DEPTH[section(w)]


def in_wall(s):
    return s.surface.role != "floor"


def bearing(w):
    """Exterior walls carry the roof; a wall under a floor may carry the floor."""
    return w.role == "exterior" or w.above is not None


def header_for(width):
    section = next(s for span, s in HEADERS if width <= span)
    return section, DEPTH[section]


def inset(s, w, end):
    """How far framing stops short of an end: by the depth of the wall met there, when that wall's framing lies
    in the way. Exterior walls run through at their start."""
    other = w.start_meets if end == "start" else w.end_meets
    if not other or (end == "start" and w.role == "exterior"):
        return 0.0
    host = s.house.wall(other)
    across = w.dir[0] * host.normal[0] + w.dir[1] * host.normal[1]
    return depth(host) if (across > 0 if end == "start" else across < 0) else 0.0


def extent(s):
    w = s.surface
    return inset(s, w, "start"), w.length - inset(s, w, "end")


def top(s):
    """Where a wall's framing stops: under the floor joists if a floor rests on it."""
    return s.surface.height - (JOIST_DEPTH if s.surface.above else 0.0)


def tee_range(s, t):
    d = depth(s.house.wall(t.wall))
    return (t.u, t.u + d) if t.side > 0 else (t.u - d, t.u)


def zones(s):
    """u-ranges kept free of layout studs: openings with their kings (and jacks)."""
    side = 2 * T if bearing(s.surface) else T
    return [(o.u0 - side, o.u1 + side) for o in s.surface.openings]


def layout(s):
    """Stud centres every 24" from u = 0, clear of the end studs and the zones."""
    a, b = extent(s)
    return [c for c in range(SPACING, int(b), SPACING) if a + 1.5 * T <= c <= b - 1.5 * T
            and not any(z0 - T / 2 < c < z1 + T / 2 for z0, z1 in zones(s))]


def pieces(s, u0, u1):
    """A run cut into stock lengths, joined over stud centres, where the joists above land too."""
    cuts, u = [], u0
    while u1 - u > MAX_PIECE:
        u = max(c for c in layout(s) if u < c <= u + MAX_PIECE)
        cuts.append(u)
    edges = [u0, *cuts, u1]
    return list(zip(edges, edges[1:]))


def posts(s):
    """The u-ranges of this wall's full-height uprights, sorted."""
    tall = [s.local(m) for m in s.members()]
    return sorted((b.lo[0], b.hi[0]) for b in tall if b.hi[1] - b.lo[1] > 0.8 * (top(s) - 2 * T))


def rungs(s):
    """Heights of ladder blocks: every 24" up the wall, under the top plate."""
    return [float(v) for v in range(24, int(top(s)), 24) if v + T <= top(s) - T]


def ladder(s, lo, hi, role):
    """Flat blocks every 24" in each bay between uprights, from the last one left of lo to the first right of hi."""
    ps = posts(s)
    i = max(k for k, (a, b) in enumerate(ps) if b <= lo + 0.01)
    j = min(k for k, (a, b) in enumerate(ps) if a >= hi - 0.01)
    for (_, left), (right, _) in zip(ps[i:j], ps[i + 1:j + 1]):
        for v in rungs(s):
            s.place(section(s.surface), left, right, v, v + T, role=role)


@rule(10, match="wall")
def bottom_plate(s, w):
    """A single bottom plate, cut out at doors, in stock lengths joined over stud centres."""
    a, b = extent(s)
    runs = [(a, b)]
    for o in w.openings:
        if o.kind == "door":
            runs = [r for x0, x1 in runs for r in ((x0, min(x1, o.u0)), (max(x0, o.u1), x1)) if r[1] - r[0] > 0.1]
    for x0, x1 in runs:
        for u0, u1 in pieces(s, x0, x1):
            s.place(section(w), u0, u1, 0, T, role="bottom plate")


@rule(11, match="wall")
def top_plate(s, w):
    """A single top plate: with studs and joists on one grid, framing above lines up within an inch."""
    a, b = extent(s)
    for u0, u1 in pieces(s, a, b):
        s.place(section(w), u0, u1, top(s) - T, top(s), role="top plate")


@rule(20, match="wall")
def end_studs(s, w):
    a, b = extent(s)
    for u in (a, b - T):
        s.place(section(w), u, u + T, T, top(s) - T, role="end stud")


@rule(30, match="wall")
def studs(s, w):
    for c in layout(s):
        s.place(section(w), c - T / 2, c + T / 2, T, top(s) - T, role="stud")


@rule(40, match="opening", when=lambda s, o: in_wall(s) and bearing(s.surface))
def jacks(s, o):
    """In a bearing wall, a jack each side of the opening, carrying the header."""
    s.place(section(s.surface), o.u0 - T, o.u0, T, o.v1, role="jack")
    s.place(section(s.surface), o.u1, o.u1 + T, T, o.v1, role="jack")


@rule(41, match="opening", when=lambda s, o: in_wall(s))
def kings(s, o):
    """A full-height king each side: outside the jack in a bearing wall, at the opening's edge otherwise."""
    k = 2 * T if bearing(s.surface) else T
    s.place(section(s.surface), o.u0 - k, o.u0 - k + T, T, top(s) - T, role="king")
    s.place(section(s.surface), o.u1 + k - T, o.u1 + k, T, top(s) - T, role="king")


@rule(42, match="opening", when=lambda s, o: in_wall(s) and bearing(s.surface))
def header(s, o):
    """A single-ply header on edge on the outside face, on the jacks; insulation fills behind it."""
    sec, d = header_for(o.width)
    s.place(sec, o.u0 - T, o.u1 + T, o.v1, o.v1 + d, w0=0, role="header")


@rule(43, match="opening", when=lambda s, o: in_wall(s) and not bearing(s.surface))
def flat_head(s, o):
    """In a wall that bears nothing, a flat piece across the top of the opening, nailed between the kings."""
    s.place(section(s.surface), o.u0, o.u1, o.v1, o.v1 + T, role="head")


@rule(44, match="opening", when=lambda s, o: o.kind == "window")
def sill(s, o):
    s.place(section(s.surface), o.u0, o.u1, o.v0 - T, o.v0, role="sill")


@rule(45, match="opening", when=lambda s, o: in_wall(s))
def cripples(s, o):
    """Short studs on the 24" layout above the head and under the sill."""
    over = T if bearing(s.surface) else 0.0
    head = o.v1 + (header_for(o.width)[1] if over else T)
    for c in range(SPACING, int(s.surface.length), SPACING):
        if o.u0 - over <= c - T / 2 and c + T / 2 <= o.u1 + over and head < top(s) - T - 0.06:
            s.place(section(s.surface), c - T / 2, c + T / 2, head, top(s) - T, role="cripple")
        if o.kind == "window" and o.u0 <= c - T / 2 and c + T / 2 <= o.u1:
            s.place(section(s.surface), c - T / 2, c + T / 2, T, o.v0 - T, role="cripple")


@rule(50, match="corner", when=lambda s, c: c.end == "start" and s.surface.role == "exterior")
def corner_ladder(s, c):
    """Two-stud corner: blocks every 24" from the end stud to the next upright catch the drywall at the corner."""
    ladder(s, T, T, "ladder block")


@rule(51, match="tee")
def partition_ladder(s, t):
    """Ladder junction: blocks every 24" across where a partition meets this wall catch both drywall edges."""
    lo, hi = tee_range(s, t)
    ladder(s, lo, hi, "ladder block")


def minus(runs, cuts):
    """The parts of runs outside every cut."""
    for c0, c1 in cuts:
        runs = [r for a, b in runs for r in ((a, min(b, c0)), (max(a, c1), b)) if r[1] - r[0] > 0.1]
    return runs


def runs_at(s, f, c):
    """Where a joist at u = c can run: inside the rim, cut over interior walls below that cross it, and
    stopped at the headers of any floor opening it would cross."""
    runs = [(a + T, b - T) for a, b in scan([(v, u) for u, v in f.outline_uv], c)]
    cuts = sorted(b.a[1] + b.side[1] * depth(s.house.wall(b.wall)) / 2 for b in f.bearers
                  if b.role == "interior" and b.along_u and min(b.a[0], b.b[0]) < c < max(b.a[0], b.b[0]))
    runs = [r for v0, v1 in runs for r in zip([v0, *[x for x in cuts if v0 < x < v1]],
                                              [*[x for x in cuts if v0 < x < v1], v1])]
    rims = [(min(a[1], b[1]), max(a[1], b[1])) for a, b in edges_v(f) if abs(a[0] - c) < 2 * T]
    return minus(runs, rims + [(o.v0 - 2 * T, o.v1 + 2 * T) for o in f.openings if o.u0 < c < o.u1])


def edges_v(f):
    """The outline's edges that run along v, where rims stand."""
    pts = f.outline_uv
    return [(a, b) for a, b in zip(pts, pts[1:] + pts[:1]) if a[0] == b[0]]


def joist(s, f, c, role="joist"):
    """A joist centred at u = c, in every run the floor allows there."""
    for v0, v1 in runs_at(s, f, c):
        s.place(JOIST, c - T / 2, c + T / 2, v0, v1, role=role)


def along(s, f):
    """u-centres of partitions above or below this floor that run with the joists."""
    walls = [b for b in f.bearers + f.loads if b.role == "interior" and not b.along_u]
    return sorted({round(b.a[0] + b.side[0] * depth(s.house.wall(b.wall)) / 2, 3) for b in walls})


def kept_clear(f, c):
    """True where a layout joist would crowd a rim along v, a trimmer, or a joist along a partition."""
    return (any(abs(c - a[0]) < 2.5 * T for a, _ in edges_v(f))
            or any(o.u0 - 3 * T < c < o.u0 + T / 2 or o.u1 - T / 2 < c < o.u1 + 3 * T for o in f.openings))


def stock(a, b):
    """a to b in equal pieces no longer than the stock."""
    n = int((b - a - 0.01) // MAX_PIECE) + 1
    return [(a + (b - a) * i / n, a + (b - a) * (i + 1) / n) for i in range(n)]


@rule(60, match="floor")
def rim(s, f):
    """A rim joist along every edge of the floor's outline, on the walls below; those along v fit between."""
    pts = f.outline_uv
    for (u0, v0), (u1, v1) in zip(pts, pts[1:] + pts[:1]):
        inward = 1 if (u1 > u0 or v1 < v0) else -1       # the floor lies left of each counter-clockwise edge
        if v0 == v1:
            for a, b in stock(min(u0, u1), max(u0, u1)):
                s.place(JOIST, a, b, v0, v0 + inward * T, role="rim")
        else:
            for a, b in stock(min(v0, v1) + T, max(v0, v1) - T):
                s.place(JOIST, u0, u0 + inward * T, a, b, role="rim")


@rule(61, match="floor")
def joists(s, f):
    """Joists at 24" across the floor, on the same grid as the studs, clear of rims, trimmers and the
    joists along partitions."""
    for c in range(SPACING, int(f.length), SPACING):
        if not kept_clear(f, c) and all(abs(c - a) >= 2 * T for a in along(s, f)):
            joist(s, f, c)


@rule(62, match="floor")
def joists_along_partitions(s, f):
    """A joist along every partition above or below that runs with the joists: something for its plates."""
    for c in along(s, f):
        joist(s, f, c)


@rule(64, match="opening", when=lambda s, o: s.surface.role == "floor")
def trimmers(s, o):
    """Doubled joists each side of a floor opening."""
    for c in (o.u0 - T / 2, o.u0 - 1.5 * T, o.u1 + T / 2, o.u1 + 1.5 * T):
        joist(s, s.surface, c, role="trimmer")


@rule(65, match="opening", when=lambda s, o: s.surface.role == "floor")
def opening_headers(s, o):
    """Doubled headers across each end of a floor opening, nailed between the trimmers; the cut joists hang
    from them."""
    for v in (o.v0 - 2 * T, o.v0 - T, o.v1, o.v1 + T):
        s.place(JOIST, o.u0, o.u1, v, v + T, role="header")


@rule(95, match="load", when=lambda s, b: b.role == "interior" and b.along_u)
def blocking_under_plate_ends(s, b):
    """A block between joists under each end of a bottom plate upstairs that runs across the joists."""
    across = sorted((m_.lo[0], m_.hi[0]) for m_ in map(s.local, s.members()) if m_.hi[1] - m_.lo[1] > 24)
    bays = set()
    for p in map(s.local, s.members(wall=b.wall, role="bottom plate")):
        for u in (p.lo[0], p.hi[0]):
            if not any(a - 0.01 <= u <= c + 0.01 for a, c in across):
                bays.add((max(c for a, c in across if c < u), min(a for a, c in across if a > u)))
    v = (p.lo[1] + p.hi[1]) / 2
    for left, right in bays:
        s.place(JOIST, left, right, v - T / 2, v + T / 2, role="block")


@rule(90, match="gap", when=lambda s, g: g.kind == "field" and g.face == "outer")
def fill_gaps(s, g):
    """An upright (in a wall) or a joist (in a floor) wherever a board would span too far."""
    u, v = (g.u0 + g.u1) / 2, (g.v0 + g.v1) / 2
    if s.surface.role == "floor":
        return joist(s, s.surface, u)
    lo, hi = s.below(u - T / 2, u + T / 2, v), s.above(u - T / 2, u + T / 2, v)
    s.place(section(s.surface), u - T / 2, u + T / 2, lo, hi, role="stud")
