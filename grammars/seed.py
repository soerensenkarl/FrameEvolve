"""Bare-bones seed grammar: the obvious first moves of a framer, and nothing more. The search starts here.

Walls: a bottom and a top plate, studs every 24" from the wall's start, a stud at each end; at each opening a king
stud each side, a header over it and a sill under a window. Floors: a rim around the outline and joists every 24".
Ceilings: ceiling joists every 24". Roofs: rafters every 24" and a ridge board. Each wall and each floor is one
prefab panel. Everything else (corners, jacks and cripples, birdsmouths, ties, gables, blocking, panel joints)
is left for the search to find. Inches.
"""
from frameevolve.builder import rule
from frameevolve.geometry import edges, scan
from frameevolve.model import Wall

T = 1.5
SPACING = 24
STOCK = 240                    # longest stock piece, 20 ft
JOIST, CEILING_JOIST, RAFTER, RIDGE, HEADER = "2x12", "2x6", "2x10", "2x12", "2x8"


def section(w):
    """Exterior walls 2x6, partitions 2x4."""
    return "2x6" if w.role == "exterior" else "2x4"


def pieces(a, b):
    """a to b in equal pieces no longer than a stock length."""
    n = int((b - a - 0.01) // STOCK) + 1
    return [(a + (b - a) * i / n, a + (b - a) * (i + 1) / n) for i in range(n)]


def top(s):
    """Where a wall's framing stops: under the floor joists if a floor rests on it."""
    w = s.surface
    return w.height - (11.25 if w.above and s.house.surface(w.above).role == "floor" else 0.0)


def runs(x, u):
    """The stretches along v where the line at u lies inside the surface's outline."""
    return scan([(v, u_) for u_, v in x.outline_uv], u)


@rule(10, match="wall")
def plates(s, w):
    """A bottom plate on the floor and a top plate under what the wall carries, in stock lengths."""
    for a, b in pieces(0, w.length):
        s.place(section(w), a, b, 0, T, role="bottom plate")
        s.place(section(w), a, b, top(s) - T, top(s), role="top plate")


@rule(20, match="wall")
def studs(s, w):
    """A stud at each end, and every 24" from the wall's start where no opening is."""
    clear = lambda u: not any(o.u0 - T < u < o.u1 + T for o in w.openings)
    for u in [0.0, w.length - T, *[c - T / 2 for c in range(SPACING, int(w.length - T), SPACING)]]:
        if clear(u) and clear(u + T):
            s.place(section(w), u, u + T, T, top(s) - T, role="stud")


@rule(30, match="opening", when=lambda s, o: isinstance(s.surface, Wall))
def opening(s, o):
    """A king stud each side, a header over the opening, and a sill under a window."""
    w = s.surface
    for u in (o.u0 - T, o.u1):
        s.place(section(w), u, u + T, T, top(s) - T, role="king")
    s.place(HEADER, o.u0, o.u1, o.v1, o.v1 + 7.25, role="header")
    if o.kind == "window":
        s.place(section(w), o.u0, o.u1, o.v0 - T, o.v0, role="sill")


@rule(40, match="floor", when=lambda s, f: f.role == "floor")
def rim(s, f):
    """A rim joist along every edge of the floor's outline, in stock lengths."""
    for (u0, v0), (u1, v1) in edges(f.outline_uv):
        along_u = v0 == v1
        for a, b in pieces(*sorted((u0, u1) if along_u else (v0, v1))):
            s.place(JOIST, *((a, b, v0, v0 + T) if along_u else (u0, u0 + T, a, b)), role="rim")


@rule(41, match="floor", when=lambda s, f: f.role == "floor")
def joists(s, f):
    """Joists every 24" across the floor, the length of the floor, in stock lengths."""
    for c in range(SPACING, int(f.length), SPACING):
        for v0, v1 in runs(f, c):
            for a, b in pieces(v0, v1):
                s.place(JOIST, c - T / 2, c + T / 2, a, b, role="joist")


@rule(42, match="floor", when=lambda s, f: f.role == "ceiling")
def ceiling_joists(s, f):
    """Ceiling joists every 24" across the ceiling, in stock lengths."""
    for c in range(SPACING, int(f.length), SPACING):
        for v0, v1 in runs(f, c):
            for a, b in pieces(v0, v1):
                s.place(CEILING_JOIST, c - T / 2, c + T / 2, a, b, role="ceiling joist")


@rule(50, match="roof")
def rafters(s, r):
    """Rafters every 24" along the eave, from the eave up the slope."""
    for c in range(SPACING, int(r.size[0]), SPACING):
        for v0, v1 in runs(r, c):
            s.place(RAFTER, c - T / 2, c + T / 2, v0, v1, role="rafter")


@rule(51, match="seam", when=lambda s, x: x.kind == "ridge")
def ridge(s, x):
    """A ridge board along the ridge, set down by half its depth."""
    up = s.surface.local_dir((0.0, 0.0, 1.0))
    sink = [-c * 11.25 / 2 for c in up]
    (u0, v), (u1, _) = sorted([x.a, x.b])
    for a, b in pieces(u0, u1):
        s.put(RIDGE, (a + sink[0], v + sink[1], sink[2]), (b + sink[0], v + sink[1], sink[2]), up, role="ridge")


@rule(90, match="member", when=lambda s, m: isinstance(s.surface, Wall) or s.surface.role == "floor")
def panels(s, m):
    """Each wall and each floor is built as one prefab panel."""
    s.assign(m, s.surface.id)
