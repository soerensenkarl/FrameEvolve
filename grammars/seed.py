"""Hand-written seed grammar for platform-framed walls.

2x4 studs at 16" on centre, a single bottom and top plate, two-ply headers sized from a simplified span table.
Exterior walls run through at their start and butt against the next wall at their end; partitions butt at both
ends. A backer stud at every inside corner and each side of every partition gives the drywall a nailing edge.
Inches.
"""
from frameevolve.builder import rule

T = 1.5          # member thickness
D = 3.5          # wall depth: 2x4 studs
SPACING = 16     # stud module
MAX_PIECE = 240  # longest stock, 20 ft
HEADERS = [(42, "2x4"), (65, "2x6"), (82, "2x8"), (101, "2x10"), (117, "2x12")]  # clear span: section


def extent(s):
    """Where this wall's framing runs along u: up to the inner face of each wall it butts into."""
    a = D if s.wall.role == "interior" and s.wall.start_meets else 0.0
    return a, s.wall.length - (D if s.wall.end_meets else 0.0)


def tee_range(t):
    """The u-range a partition's framing takes where it meets this wall."""
    return (t.u, t.u + D) if t.side > 0 else (t.u - D, t.u)


def zones(s):
    """The u-ranges taken by openings with their jacks and kings, and by partitions with their backers."""
    return ([(o.u0 - 2 * T, o.u1 + 2 * T) for o in s.wall.openings]
            + [(lo - T, hi + T) for lo, hi in map(tee_range, s.wall.tees)])


def layout(s):
    """Stud centres on the module, clear of the end studs and the openings."""
    a, b = extent(s)
    out, c = [], SPACING
    while c <= b - T - T / 2:
        if not any(z0 - T / 2 < c < z1 + T / 2 for z0, z1 in zones(s)):
            out.append(c)
        c += SPACING
    return out


def header_for(width):
    for span, section in HEADERS:
        if width <= span:
            return section, s_depth(section)
    raise ValueError(f"no header spans {width} in.")


def s_depth(section):
    return {"2x4": 3.5, "2x6": 5.5, "2x8": 7.25, "2x10": 9.25, "2x12": 11.25}[section]


@rule(10)
def bottom_plate(s):
    if not s.once():
        return
    a, b = extent(s)
    runs = [(a, b)]
    for o in s.wall.openings:
        if o.kind == "door":
            runs = [r for x0, x1 in runs for r in ((x0, min(x1, o.u0)), (max(x0, o.u1), x1)) if r[1] - r[0] > 0.1]
    for u0, u1 in runs:
        n = int((u1 - u0 - 0.01) // MAX_PIECE) + 1
        for i in range(n):
            s.place("2x4", u0 + (u1 - u0) * i / n, u0 + (u1 - u0) * (i + 1) / n, 0, T, role="bottom plate")


@rule(10)
def top_plate(s):
    """Joints land on a stud centre, so each piece bears on half a stud."""
    if not s.once():
        return
    a, b = extent(s)
    H = s.wall.height
    u = a
    while b - u > MAX_PIECE:
        c = max(j for j in layout(s) if u < j <= u + MAX_PIECE)
        s.place("2x4", u, c, H - T, H, role="top plate")
        u = c
    s.place("2x4", u, b, H - T, H, role="top plate")


@rule(20)
def end_studs(s):
    if not s.once():
        return
    a, b = extent(s)
    H = s.wall.height
    s.place("2x4", a, a + T, T, H - T, role="end stud")
    s.place("2x4", b - T, b, T, H - T, role="end stud")


@rule(21)
def corner_backer(s):
    """At the inside corner where the previous wall butts in, a stud to catch the drywall edge."""
    if s.wall.role == "exterior" and s.wall.start_meets and s.once():
        s.place("2x4", D, D + T, T, s.wall.height - T, role="corner backer")


@rule(22)
def partition_backers(s):
    """A stud each side of where a partition meets this wall, to catch the drywall edges."""
    H = s.wall.height
    for t in s.wall.tees:
        if s.once(t.wall):
            lo, hi = tee_range(t)
            s.place("2x4", lo - T, lo, T, H - T, role="partition backer")
            s.place("2x4", hi, hi + T, T, H - T, role="partition backer")


@rule(30)
def studs(s):
    if not s.once():
        return
    H = s.wall.height
    for c in layout(s):
        s.place("2x4", c - T / 2, c + T / 2, T, H - T, role="stud")


@rule(40)
def jacks(s):
    """A jack stud each side of an opening, from the bottom plate up to the head."""
    for o in s.wall.openings:
        if s.once(o.id):
            s.place("2x4", o.u0 - T, o.u0, T, o.v1, role="jack")
            s.place("2x4", o.u1, o.u1 + T, T, o.v1, role="jack")


@rule(41)
def kings(s):
    """A full-height king stud outside each jack."""
    H = s.wall.height
    for o in s.wall.openings:
        if s.once(o.id):
            s.place("2x4", o.u0 - 2 * T, o.u0 - T, T, H - T, role="king")
            s.place("2x4", o.u1 + T, o.u1 + 2 * T, T, H - T, role="king")


@rule(42)
def headers(s):
    """Two plies on edge across the opening, flush with both faces (a spacer fills the gap between them),
    bearing on the jacks and sized from the span table."""
    for o in s.wall.openings:
        if s.once(o.id):
            section, d = header_for(o.width)
            s.place(section, o.u0 - T, o.u1 + T, o.v1, o.v1 + d, w0=0, role="header")
            s.place(section, o.u0 - T, o.u1 + T, o.v1, o.v1 + d, w0=D - T, role="header")


@rule(43)
def sills(s):
    """A flat sill under each window, between the jacks."""
    for o in s.wall.openings:
        if o.kind == "window" and s.once(o.id):
            s.place("2x4", o.u0, o.u1, o.v0 - T, o.v0, role="sill")


@rule(44)
def cripples(s):
    """Short studs on the module above each header and below each sill."""
    H = s.wall.height
    for o in s.wall.openings:
        if not s.once(o.id):
            continue
        top = o.v1 + header_for(o.width)[1]
        c = SPACING * (int((o.u0 - T) // SPACING) + 1)
        while c + T / 2 <= o.u1 + T:
            if top < H - T - 0.0625 and c - T / 2 >= o.u0 - T:
                s.place("2x4", c - T / 2, c + T / 2, top, H - T, role="cripple")
            if o.kind == "window" and c - T / 2 >= o.u0 and c + T / 2 <= o.u1:
                s.place("2x4", c - T / 2, c + T / 2, T, o.v0 - T, role="cripple")
            c += SPACING


@rule(90)
def fill_gaps(s):
    """A stud wherever the sheathing would span further than the module allows."""
    for g in s.gaps():
        if g.kind != "field":
            continue
        u = (g.u0 + g.u1) / 2
        v = (g.v0 + g.v1) / 2
        lo, hi = s.below(u - T / 2, u + T / 2, v), s.above(u - T / 2, u + T / 2, v)
        if s.once(round(u, 2), round(lo, 2)):
            s.place("2x4", u - T / 2, u + T / 2, lo, hi, role="stud")
