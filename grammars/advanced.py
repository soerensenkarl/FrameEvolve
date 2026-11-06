"""Hand-written reference grammar: advanced platform framing, as prefab panels. Not the seed (that is bare
bones, in seed.py): a frame a careful framer would draw, to compare what the search finds against.

Exterior walls 2x6 and partitions 2x4, studs at 24" on one grid from the house's corner, so storeys and joists
line up. Single bottom and top plates. Two-stud corners and ladder junctions: blocking every 24" catches the
drywall. Jacks and headers only in bearing walls (exterior walls, and any wall under a floor), single-ply
headers on the outside; elsewhere a flat head nailed between the kings. Cripples only on the layout.
Floors: a 2x12 rim along the outline, joists at 24" cut over walls below that cross them, a joist along any
partition above or below that runs with them, and stair openings trimmed and headed with doubled 2x12s.
Roofs: rafters at 24", each beside a ceiling joist that ties it, plumb cut against a ridge board bevelled to
both planes, birdsmouthed over the top plate; valley rafters where roofs meet, the jacks cut against them;
balloon-framed gable walls, their studs cut to the rafters.
Prefab: a 24" grid over the plan, laid out first, that studs follow. Walls are built as panels up to 20 ft long,
joined on the grid clear of openings with a stud each side of every joint; floors as 8 ft cassettes, a joist
each side of every joint. Roofs and ceilings are framed on site.
Inches.
"""
import math

from frameevolve.builder import rule
from frameevolve.geometry import edges, inside, on_boundary, scan
from frameevolve.model import Roof, Wall

T = 1.5
SPACING = 24
PANEL = 240                              # longest wall panel: one stock length of plate
CASSETTE = 96                            # floor cassette width
MAX_PIECE = 240                          # longest stock, 20 ft
JOIST, JOIST_DEPTH = "2x12", 11.25
DEPTH = {"2x4": 3.5, "2x6": 5.5, "2x8": 7.25, "2x10": 9.25, "2x12": 11.25}
HEADERS = [(42, "2x4"), (65, "2x6"), (82, "2x8"), (101, "2x10"), (117, "2x12")]   # clear span: section
CEILING = [(118, "2x4"), (186, "2x6"), (245, "2x8"), (312, "2x10")]   # ceiling joist clear span: section
RAFTERS = [(141, "2x8"), (172, "2x10"), (200, "2x12")]                 # rafter level span: section
RIDGE = VALLEY = "2x12"


def section(w):
    return "2x6" if w.role == "exterior" else "2x4"


def depth(w):
    return DEPTH[section(w)]


def in_wall(s):
    return isinstance(s.surface, Wall)


def is_gable(w):
    """A wall whose top follows the roof (its outline is not a rectangle)."""
    return isinstance(w, Wall) and w.outline is not None


def rake(w, u):
    """How high a gable wall reaches at u: the top of its outline there."""
    return max(a[1] + (b[1] - a[1]) * (u - a[0]) / (b[0] - a[0])
               for a, b in edges(w.outline_uv) if min(a[0], b[0]) <= u <= max(a[0], b[0]) and a[0] != b[0])


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
    if w.role == "exterior" and host.role == "interior":
        return 0.0          # the partition stops short instead
    across = w.dir[0] * host.normal[0] + w.dir[1] * host.normal[1]
    return depth(host) if (across > 0 if end == "start" else across < 0) else 0.0


def extent(s):
    w = s.surface
    return inset(s, w, "start"), w.length - inset(s, w, "end")


def top(s):
    """Where a wall's framing stops: under the floor joists if a floor rests on it (a ceiling's joists sit on
    its top plate)."""
    w = s.surface
    return w.height - (JOIST_DEPTH if w.above and s.house.surface(w.above).role == "floor" else 0.0)


def tee_range(s, t):
    d = depth(s.house.wall(t.wall))
    return (t.u, t.u + d) if t.side > 0 else (t.u - d, t.u)


def zones(s):
    """u-ranges kept free of layout studs: openings with their kings (and jacks), and panel joints."""
    side = 2 * T if bearing(s.surface) else T
    return [(o.u0 - side, o.u1 + side) for o in s.surface.openings] + [(j - T, j + T) for j in joints(s)]


def layout(s):
    """Stud centres on the grid, clear of the end studs and the zones."""
    a, b = extent(s)
    return [c for c in s.crossings("grid") if a + 1.5 * T <= c <= b - 1.5 * T
            and not any(z0 - T / 2 < c < z1 + T / 2 for z0, z1 in zones(s))]


def joints(s):
    """Where this surface's panels meet: u values."""
    return s.crossings("panel joint")


def pieces(s, u0, u1):
    """A run cut at the panel joints, each piece within one panel."""
    edges = [u0, *[j for j in joints(s) if u0 < j < u1], u1]
    return list(zip(edges, edges[1:]))


@rule(1, match="house")
def grid(s, h):
    """A 24" grid over the plan from the house's corner, both ways: studs, joists and panel joints follow it."""
    xs = [p[0] for w in h.walls for p in (w.start, w.end)]
    ys = [p[1] for w in h.walls for p in (w.start, w.end)]
    for x in range(0, int(max(xs)) + 1, SPACING):
        s.guide("grid", (x, min(ys)), (x, max(ys)))
    for y in range(0, int(max(ys)) + 1, SPACING):
        s.guide("grid", (min(xs), y), (max(xs), y))


def clear(s, u):
    """True where a panel joint at u keeps 6" off every opening's framing."""
    return not any(z0 - 6 < u < z1 + 6 for z0, z1 in zones(s)[:len(s.surface.openings)])


def next_joint(s, a):
    """The furthest grid line within a panel's length of a that is clear of openings (any grid line if none)."""
    grid = [c for c in s.crossings("grid") if a + SPACING <= c <= a + PANEL]
    return max([c for c in grid if clear(s, c)] or grid)


@rule(5, match="wall")
def wall_joints(s, w):
    """Panel joints on the grid, as far apart as a panel may be long, clear of openings where it can."""
    a, b = extent(s)
    while b - a > PANEL:
        a = next_joint(s, a)
        s.guide("panel joint", (a, 0), (a, w.size[1]))


@rule(5, match="floor", when=lambda s, f: f.role == "floor")
def floor_joints(s, f):
    """Cassette joints across the floor every 8 ft, just past a grid joist."""
    for c in range(CASSETTE, int(f.length) - SPACING, CASSETTE):
        s.guide("panel joint", (c + T / 2, 0), (c + T / 2, f.width))


def panel_of(s, m):
    """The panel a member falls in: the surface, and how many joints lie before its middle."""
    b = s.local(m)
    k = sum(1 for j in joints(s) if j < (b.lo[0] + b.hi[0]) / 2)
    return f"{s.surface.id}.{k + 1}"


@rule(96, match="member", when=lambda s, m: in_wall(s) or s.surface.role == "floor")
def panels(s, m):
    """Walls and floors are built in the shop: every member into the panel it falls in."""
    s.assign(m, panel_of(s, m))


def posts(s):
    """This wall's full-height uprights, sorted: (u0, u1, top)."""
    tops = {}
    for b in map(s.local, s.members()):
        if b.hi[1] - b.lo[1] > 0.8 * (top(s) - 2 * T):        # a spliced stud is one upright
            tops[(b.lo[0], b.hi[0])] = max(b.hi[1], tops.get((b.lo[0], b.hi[0]), 0.0))
    return sorted((u0, u1, t) for (u0, u1), t in tops.items())


def rungs(s):
    """Heights of ladder blocks: every 24" up the wall, under the top plate."""
    return [float(v) for v in range(24, int(top(s)), 24) if v + T <= top(s) - T]


def ladder(s, lo, hi, role):
    """Flat blocks every 24" in each bay between uprights, from the last one left of lo to the first right of hi,
    kept below the uprights' tops (a gable wall's are cut to the roof)."""
    ps = posts(s)
    i = max(k for k, (a, b, _) in enumerate(ps) if b <= lo + 0.01)
    j = min(k for k, (a, b, _) in enumerate(ps) if a >= hi - 0.01)
    for (_, left, t0), (right, _, t1) in zip(ps[i:j], ps[i + 1:j + 1]):
        for v in rungs(s):
            if v + T <= min(t0, t1) - (2 if is_gable(s.surface) else 0):
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


@rule(11, match="wall", when=lambda s, w: not is_gable(w))
def top_plate(s, w):
    """A single top plate: with studs and joists on one grid, framing above lines up within an inch."""
    a, b = extent(s)
    for u0, u1 in pieces(s, a, b):
        s.place(section(w), u0, u1, top(s) - T, top(s), role="top plate")


def stud_top(s, u0, u1):
    """Up to the top plate, or in a gable wall up to the roof (cut to fit the rafters later)."""
    w = s.surface
    return max(rake(w, u0), rake(w, u1)) if is_gable(w) else top(s) - T


def upright(s, u0, u1, v0, role):
    """A stud from v0 up to the top plate or the roof; one too long for stock is spliced where the top plate
    would be."""
    v1 = stud_top(s, u0, u1)
    cuts = [v0, top(s) - T, v1] if v1 - v0 > MAX_PIECE else [v0, v1]
    for a, b in zip(cuts, cuts[1:]):
        s.place(section(s.surface), u0, u1, a, b, role=role)


@rule(20, match="wall")
def end_studs(s, w):
    """A stud at each end of the wall, and one each side of every panel joint."""
    a, b = extent(s)
    for u in (a, b - T, *[x for j in joints(s) for x in (j - T, j)]):
        upright(s, u, u + T, T, "end stud")


@rule(30, match="wall")
def studs(s, w):
    for c in layout(s):
        upright(s, c - T / 2, c + T / 2, T, "stud")


@rule(40, match="opening", when=lambda s, o: in_wall(s) and bearing(s.surface))
def jacks(s, o):
    """In a bearing wall, a jack each side of the opening, carrying the header."""
    s.place(section(s.surface), o.u0 - T, o.u0, T, o.v1, role="jack")
    s.place(section(s.surface), o.u1, o.u1 + T, T, o.v1, role="jack")


@rule(41, match="opening", when=lambda s, o: in_wall(s))
def kings(s, o):
    """A full-height king each side: outside the jack in a bearing wall, at the opening's edge otherwise."""
    k = 2 * T if bearing(s.surface) else T
    upright(s, o.u0 - k, o.u0 - k + T, T, "king")
    upright(s, o.u1 + k - T, o.u1 + k, T, "king")


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


def spaced(a, b):
    """Centres on the 24" layout between a and b, plus one beside a or b wherever a bay would be too wide."""
    cs = [c for c in range(SPACING, int(b) + 1, SPACING) if a <= c - T / 2 and c + T / 2 <= b]
    edges = [a - T / 2, *cs, b + T / 2]
    return cs + [x + T for x, y in zip(edges, edges[1:]) if y - x - T > SPACING - T and x + 2 * T < y]


@rule(45, match="opening", when=lambda s, o: in_wall(s))
def cripples(s, o):
    """Short studs on the 24" layout above the head and under the sill."""
    over = T if bearing(s.surface) else 0.0
    head = o.v1 + (header_for(o.width)[1] if over else T)
    if head < top(s) - T - 0.06:
        for c in spaced(o.u0 - over, o.u1 + over):
            upright(s, c - T / 2, c + T / 2, head, "cripple")
    for c in range(SPACING, int(s.surface.length), SPACING):
        if o.kind == "window" and o.u0 <= c - T / 2 and c + T / 2 <= o.u1:
            s.place(section(s.surface), c - T / 2, c + T / 2, T, o.v0 - T, role="cripple")


@rule(80, match="corner", when=lambda s, c: s.surface.role == "exterior"
      and (c.end == "start" or s.house.wall(c.other).role == "interior"))
def corner_ladder(s, c):
    """Two-stud corner: blocks every 24" from the end stud to the next upright catch the drywall at the corner;
    at a partition ending against this wall's end, blocks across where it meets the face."""
    if c.end == "start":
        return ladder(s, T, T, "ladder block")
    u = s.surface.length - depth(s.house.wall(c.other))
    ladder(s, u, u, "ladder block")


@rule(81, match="tee")
def partition_ladder(s, t):
    """Ladder junction: blocks every 24" across where a partition meets this wall catch both drywall edges."""
    lo, hi = tee_range(s, t)
    ladder(s, lo, hi, "ladder block")


def minus(runs, cuts):
    """The parts of runs outside every cut."""
    for c0, c1 in cuts:
        runs = [r for a, b in runs for r in ((a, min(b, c0)), (max(a, c1), b)) if r[1] - r[0] > 2 * T]
    return runs


def runs_at(s, f, c, rim=T):
    """Where a joist at u = c can run: inside the rim, cut over interior walls below that cross it, and
    stopped at the headers of any floor opening it would cross."""
    runs = [(a + rim, b - rim) for a, b in scan_v(f, c)]
    cuts = sorted(b.a[1] + b.side[1] * depth(s.house.wall(b.wall)) / 2 for b in f.bearers
                  if b.role == "interior" and b.along_u and min(b.a[0], b.b[0]) < c < max(b.a[0], b.b[0]))
    runs = [r for v0, v1 in runs for r in zip([v0, *[x for x in cuts if v0 < x < v1]],
                                              [*[x for x in cuts if v0 < x < v1], v1]) if r[1] - r[0] > 2 * T]
    rims = [(min(a[1], b[1]), max(a[1], b[1])) for a, b in edges_v(f) if rim and abs(a[0] - c) < 2 * T]
    return minus(runs, rims + [(o.v0 - 2 * T, o.v1 + 2 * T) for o in f.openings if o.u0 < c < o.u1])


def edges_v(f):
    """The outline's edges that run along v, where rims stand."""
    return [(a, b) for a, b in edges(f.outline_uv) if a[0] == b[0]]


def scan_v(x, u):
    """The v-runs where the line at u lies inside the surface's outline."""
    return scan([(v, u_) for u_, v in x.outline_uv], u)


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


def lengths(a, b):
    """a to b in equal pieces no longer than the stock."""
    n = int((b - a - 0.01) // MAX_PIECE) + 1
    return [(a + (b - a) * i / n, a + (b - a) * (i + 1) / n) for i in range(n)]


def stock(s, a, b):
    """a to b along u cut at the panel joints, each run in stock lengths."""
    edges = [a, *[j for j in joints(s) if a < j < b], b]
    return [piece for x0, x1 in zip(edges, edges[1:]) for piece in lengths(x0, x1)]


@rule(60, match="floor", when=lambda s, f: f.role == "floor")
def rim(s, f):
    """A rim joist along every edge of the floor's outline, on the walls below; those along v fit between."""
    for (u0, v0), (u1, v1) in edges(f.outline_uv):
        inward = 1 if (u1 > u0 or v1 < v0) else -1       # the floor lies left of each counter-clockwise edge
        if v0 == v1:
            for a, b in stock(s, min(u0, u1), max(u0, u1)):
                s.place(JOIST, a, b, v0, v0 + inward * T, role="rim")
        else:
            for a, b in lengths(min(v0, v1) + T, max(v0, v1) - T):
                s.place(JOIST, u0, u0 + inward * T, a, b, role="rim")


@rule(61, match="floor", when=lambda s, f: f.role == "floor")
def joists(s, f):
    """Joists at 24" across the floor, on the same grid as the studs, clear of rims, trimmers and the
    joists along partitions."""
    for c in range(SPACING, int(f.length), SPACING):
        if not kept_clear(f, c) and all(abs(c - a) >= 2 * T for a in along(s, f)):
            joist(s, f, c)


@rule(62, match="floor", when=lambda s, f: f.role == "floor")
def joint_joists(s, f):
    """A joist just past each cassette joint, so each cassette has its own at the joint."""
    for j in joints(s):
        joist(s, f, j + T / 2)


@rule(62, match="floor", when=lambda s, f: f.role == "floor")
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


def rising(s, x, u):
    """How far framing inside surface x starts in from its outline's end at u (0 or the far end): the depth of
    a wall along that end whose framing lies inside and that rises past the surface (a gable wall through a
    ceiling, a taller wall a roof stops against)."""
    L = x.size[0]
    height = (lambda p: x.height(p[0], p[1])) if isinstance(x, Roof) else (lambda p: x.z)
    out = []
    over = lambda p: inside(x.local(p)[:2], x.outline_uv) and p[2] > height(p) + 0.1
    for w in s.house.walls:
        ends = [x.local((*p, w.base))[0] for p in (w.start, w.end)]
        inward = (w.normal[0] * x.eu[0] + w.normal[1] * x.eu[1]) * (1 if u < L / 2 else -1)
        if max(abs(e - u) for e in ends) < 0.1 and inward > 0.5 and any(over(w.world(a, b, 0)) for a, b in w.outline_uv):
            out.append(depth(w))
    return max(out, default=0.0)


@rule(66, match="floor", when=lambda s, f: f.role == "ceiling")
def ceiling_joists(s, f):
    """Ceiling joists at 24" on the stud grid, on the walls' top plates and split over the spine, sized for the
    longest run; one at each end, inside any wall rising through the ceiling, catches its edge. Each ties a
    rafter."""
    a, b = rising(s, f, 0) + T / 2, f.length - rising(s, f, f.length) - T / 2
    cs = [c for c in range(SPACING, int(f.length), SPACING) if a + T <= c <= b - T] + [a, b]
    longest = max(v1 - v0 for c in cs for v0, v1 in runs_at(s, f, c, rim=0))
    sec = next(x for span, x in CEILING if longest <= span)
    for c in cs:
        for v0, v1 in runs_at(s, f, c, rim=0):
            s.place(sec, c - T / 2, c + T / 2, v0, v1, role="ceiling joist")


@rule(73, match="member", when=lambda s, m: m.role == "ceiling joist" and s.overlapping(m))
def ceiling_under_roof(s, m):
    """A ceiling joist running into a rafter or valley rafter (at an end against a wall, at an inside corner),
    notched around it."""
    for n in s.overlapping(m):
        if n.role in ("rafter", "valley"):
            s.notch(m, n)


def eave_wall(s, r):
    """The exterior wall under the roof plane's eave, and how far in from the eave line it stands."""
    e = r.eu
    inward = lambda w: (w.start[0] - r.start[0]) * -e[1] + (w.start[1] - r.start[1]) * e[0]
    L = r.size[0]
    along = lambda w: ((w.start[0] + w.end[0]) / 2 - r.start[0]) * e[0] + ((w.start[1] + w.end[1]) / 2 - r.start[1]) * e[1]
    walls = [w for w in s.house.walls if w.role == "exterior" and not w.outline and inward(w) >= 0
             and abs(w.dir[0] * e[0] + w.dir[1] * e[1]) > 0.99 and 0 <= along(w) <= L]
    w = max(walls, key=lambda w: (-inward(w), w.base))
    return w, inward(w)


def rafter_section(s, r):
    """The smallest rafter that spans from the eave wall to the ridge and is deep enough to sit 1 1/2" on the
    plate under the heel (the roof's height over the plate at the wall's face)."""
    w, inset = eave_wall(s, r)
    span = r.size[1] / math.hypot(1, r.slope) - inset
    heel = r.height(*w.start) - (w.base + w.height)
    return next(x for run, x in RAFTERS if span <= run and DEPTH[x] * math.hypot(1, r.slope) >= heel + T * r.slope)


def spans(r, u0, u1):
    """Where a rafter from u0 to u1 can run up the plane: the outline's v-runs across both its sides."""
    runs = [(v0, v1) for u in (u0 + 0.01, u1 - 0.01) for v0, v1 in scan_v(r, u)]
    out = []
    for v0, v1 in sorted(runs):
        if out and v0 <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], v1))
        else:
            out.append((v0, v1))
    return [(v0, v1) for v0, v1 in out if v1 - v0 > 12]


@rule(70, match="roof")
def rafters(s, r):
    """Rafters at 24", each just past a ceiling joist on the stud grid so the joist ties it, one at each end
    (over a gable wall, or inside a wall the roof stops against), and one more beside an end where the gap
    would be too wide for the sheathing. Where the plane ends in a valley they run from it: jacks."""
    sec = rafter_section(s, r)
    L, V = r.size
    a, b = rising(s, r, 0), L - rising(s, r, L)
    g0 = sum(r.origin[k] * r.eu[k] for k in range(2))   # the grid runs from the house's corner
    us = [c + T / 2 - g0 for c in range(SPACING * math.floor(g0 / SPACING), int(g0 + L) + 1, SPACING)]
    grid = [u for u in us if a + T + 0.01 < u < b - 2 * T - 0.01]
    us = sorted([a, b - T] + grid)    # too wide a gap: one more, on the far side of the next joist if it can
    us += [y - 2 * T if y in grid and y - 2 * T > x + T else x + T for x, y in zip(us, us[1:]) if y - x - T > SPACING - T]
    for u in us:
        for v0, v1 in spans(r, u, u + T):
            s.place(sec, u, u + T, v0, v1, role="rafter")


@rule(71, match="seam", when=lambda s, x: x.kind == "ridge")
def ridge(s, x):
    """A ridge board under the ridge, its top bevelled flush with both roof planes."""
    up = s.surface.local_dir((0.0, 0.0, 1.0))
    sink = [-c * DEPTH[RIDGE] / 2 for c in up]
    (u0, v), (u1, _) = sorted([x.a, x.b])
    for a, b in stock(s, u0, u1):
        m = s.put(RIDGE, (a + sink[0], v + sink[1], sink[2]), (b + sink[0], v + sink[1], sink[2]), up, role="ridge")
        s.cut(m, (0, 0, 0), (0, 0, -1))
        s.cut(m, (0, 0, 0), (0, 0, -1), surface=s.house.surface(x.other))


@rule(71, match="seam", when=lambda s, x: x.kind == "valley")
def valley(s, x):
    """A valley rafter under the valley line, its depth upright, its top grooved flush with both planes: the
    jacks of both planes land on it."""
    r = s.surface
    a, b = (r.world(*p, 0) for p in (x.a, x.b))
    ax = tuple((b[k] - a[k]) / math.dist(a, b) for k in range(3))
    up = tuple((k == 2) - ax[2] * ax[k] for k in range(3))
    up = r.local_dir(tuple(c / math.hypot(*up) for c in up))
    sink = [c * (T - DEPTH[VALLEY] / 2) for c in up]     # raised a little, then grooved to both planes
    m = s.put(VALLEY, (x.a[0] + sink[0], x.a[1] + sink[1], sink[2]), (x.b[0] + sink[0], x.b[1] + sink[1], sink[2]),
              up, role="valley")
    s.fit(m, r, s.house.surface(x.other))


@rule(72, match="member", when=lambda s, m: m.role in ("rafter", "valley"))
def rafter_ends(s, m):
    """A plumb cut against the ridge board (or the valley a jack lands on), and a birdsmouth over the top plate:
    a seat on the plate and a heel at its outside face."""
    for n in s.overlapping(m):
        if n.role in ("ridge", "valley") and n.role != m.role:
            s.trim(m, n)
        elif n.role == "top plate":
            s.notch(m, n, below=True)


def above_underside(m, roof, d):
    """True if m crosses the underside of a roof plane's rafters (d deep), under the plane."""
    pts = [(w, inside((u, v), roof.outline_uv) and not on_boundary((u, v), roof.outline_uv))
           for u, v, w in map(roof.local, m.points)]
    return any(w < d - 0.01 and hit for w, hit in pts) and any(w > d + 0.01 for w, _ in pts)


@rule(75, match="member", when=lambda s, m: is_gable(s.surface) and s.overlapping(m))
def fit_under_roof(s, m):
    """Gable wall framing that runs up into the roof framing, cut along the rafters' underside and under the
    ridge board; a piece wholly above the rafters comes out."""
    for roof in s.house.roofs:
        d = max([n.depth for n in s.members(surface=roof.id, role="rafter")] or [0])
        if d and above_underside(m, roof, d):
            try:
                s.cut(m, (0, 0, d), (0, 0, -1), surface=roof)
            except ValueError:
                return s.remove(m)
    for n in s.overlapping(m):   # a ridge board deeper than the rafters
        s.trim(m, n)


@rule(95, match="load", when=lambda s, b: b.role == "interior" and b.along_u)
def blocking_under_plate_ends(s, b):
    """A block between joists under each end of a bottom plate upstairs that runs across the joists."""
    across = sorted((m_.lo[0], m_.hi[0]) for m_ in map(s.local, s.members()) if m_.hi[1] - m_.lo[1] > 24)
    bays = set()
    for p in map(s.local, s.members(surface=b.wall, role="bottom plate")):
        v = (p.lo[1] + p.hi[1]) / 2
        for u in (p.lo[0], p.hi[0]):
            if not any(a - 0.01 <= u <= c + 0.01 for a, c in across):
                bays.add((max(c for a, c in across if c < u), min(a for a, c in across if a > u), v))
    for left, right, v in bays:
        s.place(JOIST, left, right, v - T / 2, v + T / 2, role="block")


@rule(90, match="gap", when=lambda s, g: g.kind == "field" and g.face == "outer" and s.surface.role != "roof")
def fill_gaps(s, g):
    """An upright (in a wall) or a joist (in a floor) wherever a board would span too far."""
    u, v = (g.u0 + g.u1) / 2, (g.v0 + g.v1) / 2
    if s.surface.role == "floor":
        return joist(s, s.surface, u)
    if s.surface.role == "ceiling":
        return s.place("2x6", u - T / 2, u + T / 2, g.v0, g.v1, role="ceiling joist")
    lo, hi = s.below(u - T / 2, u + T / 2, v), s.above(u - T / 2, u + T / 2, v)
    s.place(section(s.surface), u - T / 2, u + T / 2, lo, hi, role="stud")
