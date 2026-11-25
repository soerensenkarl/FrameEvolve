"""Can the frame stand up at all: rule errors, pieces too long for stock or running into openings, members that
clash, members with nothing holding them up, and level and sloped members spanning, overhanging and bearing as
the IRC span tables allow. Rafters also need a tie against thrust that reaches across the house.

Span tables are Spruce-Pine-Fir No. 2, the common grade around Cambridge, MA: by depth, then by spacing on centre
(12, 16, 19.2, 24"). A member's spacing is measured to its neighbours and read in the next column up.
"""
from __future__ import annotations

import math

from frameevolve.geometry import EPS, Vec, dot
from frameevolve.graph import GROUND, Graph
from frameevolve.model import STOCK, Floor, Member, Roof, Wall
from frameevolve.units import ftin, inches
from frameevolve.verifier.report import Fault
from frameevolve.verifier.site import Site, axis, column, level, name, nominal, on_edge, vertical

MAX_CLEAR_FLAT = 24.0    # a plate laid flat, between supports: the 24" module
# A beam on edge in a wall (not a header over an opening; those are in code.py), clear span by depth: IRC Table
# R602.7(1), two plies carrying roof and ceiling, 24 ft building width, 50 psf ground snow column (Cambridge 40 psf,
# 780 CMR Table R301.2(2)), as the headers in code.py.
WALL_BEAM_CLEAR = {3.5: 31.0, 5.5: 47.0, 7.25: 60.0, 9.25: 71.0, 11.25: 83.0}
# Floor joist clear span: IRC Table R502.3.1(2), 40 psf live, 10 psf dead, L/360.
JOIST_CLEAR = {5.5: {12: 123.0, 16: 112.0, 19.2: 105.0, 24: 97.0}, 7.25: {12: 162.0, 16: 147.0, 19.2: 138.0, 24: 123.0},
               9.25: {12: 207.0, 16: 185.0, 19.2: 169.0, 24: 151.0}, 11.25: {12: 247.0, 16: 214.0, 19.2: 195.0, 24: 175.0}}
# Ceiling joist clear span: IRC Table R802.5.1(1), attic without storage, 10 psf live, 5 psf dead (2x12 as 2x10).
CEILING_CLEAR = {3.5: {12: 142.0, 16: 129.0, 19.2: 122.0, 24: 113.0}, 5.5: {12: 224.0, 16: 203.0, 19.2: 191.0, 24: 177.0},
                 7.25: {12: 295.0, 16: 268.0, 19.2: 252.0, 24: 225.0}, 9.25: {12: 312.0, 16: 312.0, 19.2: 308.0, 24: 275.0},
                 11.25: {12: 312.0, 16: 312.0, 19.2: 308.0, 24: 275.0}}
# Rafter span, measured level: IRC Table R802.4.1(5), 50 psf ground snow (the table above Cambridge's 40 psf),
# ceiling not attached to the rafters, L/180, Spruce-Pine-Fir No. 2, 20 psf dead load column: the analysis takes 15 psf
# of roof dead load (analysis.ROOF_LOAD), which the 10 psf column does not cover.
RAFTER_RUN = {3.5: {12: 85.0, 16: 74.0, 19.2: 67.0, 24: 60.0}, 5.5: {12: 125.0, 16: 108.0, 19.2: 99.0, 24: 88.0},
              7.25: {12: 158.0, 16: 137.0, 19.2: 125.0, 24: 112.0}, 9.25: {12: 193.0, 16: 167.0, 19.2: 153.0, 24: 137.0},
              11.25: {12: 224.0, 16: 194.0, 19.2: 177.0, 24: 158.0}}
MAX_OVERHANG = 2.0       # a loaded member past its last support
MIN_BEARING = 1.5        # IRC R502.6, R802.6: the ends of joists, beams and rafters bear 1 1/2" on wood
MIN_BEARING_FLAT = 0.75  # a plate laid flat: half a stud
# Table R802.4.1(9): with ceiling joists or rafter ties above the top of the walls the rafters rest on, rafter spans
# are multiplied by a factor, by the tie's height over the ridge's (both above the wall top): (ratio, factor).
RAISED_TIE = ((1 / 7.5, 1.00), (1 / 6, 0.90), (1 / 5, 0.83), (1 / 4, 0.76), (1 / 3, 0.67))
# Table R802.11, exposure B, 120 mph (Cambridge, 780 CMR Table R301.2(2)): uplift per rafter, lb, by spacing, then roof
# span (ft): (under 5:12, 5:12 or steeper). Over 200 lb a rafter needs a designed connector, not nails (R802.11).
UPLIFT = {12: {12: (70, 64), 18: (89, 81), 24: (108, 98), 28: (121, 109), 32: (134, 120), 36: (146, 132),
               42: (166, 149), 48: (185, 166)},
          16: {12: (93, 85), 18: (118, 108), 24: (144, 130), 28: (161, 145), 32: (178, 160), 36: (194, 176),
               42: (221, 198), 48: (246, 221)},
          24: {12: (140, 128), 18: (178, 162), 24: (216, 196), 28: (242, 218), 32: (268, 240), 36: (292, 264),
               42: (332, 298), 48: (370, 332)}}
UPLIFT_NAILED = 200.0    # R802.11 exception 1: up to this, the nailing of Table R602.3(1) holds the rafter down
SEAT_GROUP = 6.0         # bearing contacts this close together in plan are one seat
TOUCH = 0.25             # less than this beside a full seat is a graze, not a seat
LAP = 3.0                # IRC R802.5.2.1: ceiling joists lapped at least 3", or butted over a bearing (connector)


def rule_errors(s: Site) -> list[Fault]:
    """A rule that raised an error left part of the frame out."""
    return [Fault("rule error", True, e, rules=[e.split(" ", 1)[0]]) for e in s.frame.errors]


def pieces(s: Site) -> list[Fault]:
    """Each member on its own: longer than any stock length, or running into a door or window."""
    out = []
    for m in s.frame.members:
        if m.length > max(STOCK) + EPS:
            out.append(s.at(m, m.box.centre, "too long", True,
                            f"{name(m)} is {ftin(m.length)}, longer than the {ftin(max(STOCK))} stock"))
        w = s.surfs.get(m.surface)
        if not w:
            continue
        b = w.local_box(m)
        for o in w.openings:
            du = min(b.hi[0], o.u1) - max(b.lo[0], o.u0)
            dv = min(b.hi[1], o.v1) - max(b.lo[1], o.v0)
            if du > EPS and dv > EPS:
                u = (max(b.lo[0], o.u0) + min(b.hi[0], o.u1)) / 2
                v = (max(b.lo[1], o.v0) + min(b.hi[1], o.v1)) / 2
                out.append(s.at(m, w.world(u, v, 0), "opening", True,
                                f"{name(m)} on {w.id} runs {ftin(du)} into {o.kind} {o.id}"))
    return out


def clashes(s: Site) -> list[Fault]:
    """Two members in the same space."""
    out = []
    for a, b, vol in s.g.clashes:
        ma, mb = s.by_id[a], s.by_id[b]
        p = tuple((max(ma.box.lo[k], mb.box.lo[k]) + min(ma.box.hi[k], mb.box.hi[k])) / 2 for k in range(3))
        out.append(s.at(ma, p, "clash", True, f"{name(ma)} and {name(mb)} overlap by {vol:.1f} cubic inches", [mb]))
    return out


def supported(g: Graph, by_id: dict[str, Member]) -> set[str]:
    """Members held up: a chain of bearing down to the ground, where a piece that is not upright, nailed
    between held-up members on opposite faces (blocking between studs, a flat head between kings, a ridge board
    between rafters), also counts."""
    held = g.grounded()
    while True:
        new = set()
        for mid, m in by_id.items():
            if mid in held or vertical(m):
                continue
            dirs = [g.facing[(mid, n)] for n in g.side.get(mid, {}) if n in held]
            if any(dot(a, b) < -0.5 for i, a in enumerate(dirs) for b in dirs[i + 1:]):
                new.add(mid)
        if not new:
            return held
        held |= new
        todo = list(new)
        while todo:              # and whatever bears on what was just held up
            for a in g.carries.get(todo.pop(), {}):
                if a not in held:
                    held.add(a)
                    todo.append(a)


def floating(s: Site) -> list[Fault]:
    """Nothing holds it up."""
    return [s.at(m, m.box.centre, "floating", True, f"{name(m)} has no chain of bearing to the ground")
            for m in s.frame.members if m.id not in s.held]


def spans(s: Site) -> list[Fault]:
    """Level members that carry something (or floor and ceiling framing, which carries the boards on it, or a
    wall's top plate under the roof): clear span between supports by the IRC tables, overhang past the last
    support, and bearing length on each support. Headers over openings are code.py's."""
    from frameevolve.verifier.code import headers
    heads = {k for w in s.house.walls for k in headers(s, w)}
    out = []
    for m in s.frame.members:
        if m.id in heads or not m.aligned or m.id not in s.held or GROUND in s.g.bears[m.id] or vertical(m):
            continue
        k = max(range(3), key=lambda j: abs(m.end[j] - m.start[j]))
        w = s.surfs.get(m.surface)
        floor = isinstance(w, Floor)
        roof = (isinstance(w, Wall) and w.role == "exterior" and w.above is None
                and abs(m.box.hi[2] - (w.base + w.height)) <= EPS)
        if not (s.g.carries[m.id] or roof or floor):
            continue
        a0, a1 = m.box.lo[k], m.box.hi[k]
        sup = sorted((max(a0, s.by_id[n].box.lo[k]), min(a1, s.by_id[n].box.hi[k]), n) for n in s.g.bears[m.id])
        if floor:   # a joist end butting into the side of a header or rim hangs from it (a hanger)
            sup += [(x, x, n) for n in s.g.side.get(m.id, {}) for x in (a0, a1) if n in s.held
                    and (abs(s.by_id[n].box.lo[k] - x) <= EPS or abs(s.by_id[n].box.hi[k] - x) <= EPS)]
            sup.sort()
        if not sup:
            continue
        flat = not on_edge(m)
        col = column(s.gaps.get(m.id))
        if flat:
            limit, kind = MAX_CLEAR_FLAT, f"a flat {m.section}"
        elif floor:
            table = CEILING_CLEAR if w.role == "ceiling" else JOIST_CLEAR
            limit = table.get(m.depth, {}).get(col) if col else None
            kind = (f"a {m.section} {'ceiling joist' if w.role == 'ceiling' else 'joist'} at {col:g}\" on centre"
                    if col else f"{m.section} joists {inches(s.gaps[m.id])} apart, wider than any table")
        else:
            limit, kind = WALL_BEAM_CLEAR.get(m.depth, MAX_CLEAR_FLAT), f"a {m.section} on edge"
        least = MIN_BEARING_FLAT if flat else MIN_BEARING

        def point(x: float) -> Vec:
            p = list(m.box.centre)
            p[k] = x
            return tuple(p)

        places = bearings(sup)        # what it rests on at one place, together (a plate on two joists side by side);
        for place in places[:1] + places[-1:] if len(places) > 1 else places:   # the minimum is for its ends
            length = sum(s1 - s0 for s0, s1, _ in merged(place))
            if length < least - EPS:
                ms = [s.by_id[n] for _, _, n in place if n in s.by_id]
                out.append(s.at(m, point((place[0][0] + place[-1][1]) / 2), "bearing", True,
                                f"{name(m)} bears only {inches(length)} on {', '.join(name(x) for x in ms)}, minimum "
                                f"{inches(least)}", ms))
        reach = sup[0][1]
        for s0, s1, n in sup[1:]:      # no table (a beam or header in a floor, a rim): analysis.py checks it
            gap = s0 - reach
            if limit is not None and gap > limit + EPS:
                out.append(s.at(m, point((reach + s0) / 2), "span", True,
                                f"{name(m)} spans {ftin(gap)} clear between supports, limit {ftin(limit)} for {kind}"))
            reach = max(reach, s1)
        # R502.3.3: a floor joist may cantilever up to its nominal depth
        most = nominal(m) if (floor and not flat and w.role != "ceiling") else MAX_OVERHANG
        for over in (sup[0][0] - a0, a1 - max(s1 for _, s1, _ in sup)):
            if over > most + EPS:
                x = a0 + over / 2 if over == sup[0][0] - a0 else a1 - over / 2
                out.append(s.at(m, point(x), "overhang", True,
                                f"{name(m)} runs {ftin(over)} past its last support, limit {inches(most)}"))
    return out


def bearings(sup: list[tuple]) -> list[list[tuple]]:
    """A member's supports (from, to, id), in order, gathered into places it rests on: those that overlap or touch
    are one place. Hangers (a point) are not bearings."""
    out: list[list[tuple]] = []
    for x in sorted(x for x in sup if x[1] > x[0]):
        if out and x[0] <= max(y[1] for y in out[-1]) + EPS:
            out[-1].append(x)
        else:
            out.append([x])
    return out


def merged(place: list[tuple]) -> list[tuple]:
    """The stretches of a place covered by its supports, overlaps counted once."""
    out = []
    for s0, s1, n in sorted(place):
        if out and s0 <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], s1), n)
        else:
            out.append((s0, s1, n))
    return out


# ------------------------------------------------------------------------------------------------ rafters

def ties(s: Site, m: Member, framing: set[str]) -> list[str]:
    """What ties rafter m against thrust: level ceiling or roof framing nailed to its side or under it, in the
    lower third of its rise."""
    lo, hi = m.box.lo[2], m.box.hi[2]
    return [n for n in [*s.g.side[m.id], *s.g.bears[m.id]] if n in s.held and s.by_id[n].surface in framing
            and level(s.by_id[n]) and s.g.at[(m.id, n)][2] <= lo + (hi - lo) / 3]


def tie_lines(s: Site, framing: set[str]) -> dict[str, str]:
    """Level framing on floors, ceilings and roofs joined into lines that carry tension across a house: each
    member's line. Two members are one line where they lap face to face by at least 3", or butt end to end over
    the same bearing wall (with a connector, IRC R802.5.2.1)."""
    root = {m.id: m.id for m in s.frame.members if m.surface in framing and level(m)}

    def find(x):
        while root[x] != x:
            root[x] = root[root[x]]
            x = root[x]
        return x
    for mid in root:
        m = s.by_id[mid]
        for n, area in s.g.side[mid].items():
            if n not in root or abs(dot(axis(m), axis(s.by_id[n]))) < 0.99:
                continue
            if abs(dot(s.g.facing[(mid, n)], axis(m))) < 0.1:      # face to face: a lap
                joined = area / min(m.depth, s.by_id[n].depth) >= LAP - EPS
            else:                                                  # end to end: a butt over one bearing wall
                under = lambda k: {s.by_id[x].surface for x in s.g.bears[k] if x in s.by_id}
                joined = bool(under(mid) & under(n) & {w.id for w in s.house.walls})
            if joined:
                root[find(mid)] = find(n)
    return {k: find(k) for k in root}


def rafters(s: Site) -> list[Fault]:
    """Every rafter: its span measured level between what it rests on and the ridge it butts, by the table for
    its spacing; and unless it rests on something high up (a gable wall, a beam), a tie in the lower third of
    its rise whose tie line reaches across the ridge: it also ties a rafter on the other slope, or runs across
    the house in plan as far as the other eave. Hips, valleys and the jacks
    hanging on them are not checked for thrust yet. Ridges, hips and valleys must be as deep as the rafters'
    plumb cuts into them (code.ridges)."""
    from frameevolve.verifier.code import ridges
    roofs = {r.id for r in s.house.roofs}
    framing = roofs | {f.id for f in s.house.floors}
    rs = [m for m in s.frame.members if m.surface in roofs and m.id in s.held and not vertical(m)
          and abs(axis(m)[2]) >= 0.05]
    lines = tie_lines(s, framing)
    tied = {m.id: ties(s, m, framing) for m in rs}
    reach: dict[str, set] = {}
    for m in rs:
        reach.setdefault(m.surface, set()).update(lines.get(n, n) for n in tied[m.id])
    opposite: dict[str, set] = {}
    for r in s.house.roofs:
        for x in r.seams:
            if x.kind == "ridge":
                opposite.setdefault(r.id, set()).add(x.other)
                opposite.setdefault(x.other, set()).add(r.id)
    members_of: dict[str, list] = {}
    for k, line in lines.items():
        members_of.setdefault(line, []).append(s.by_id[k])
    out, cut_ends = [], {}
    for m in rs:
        other = set().union(*(reach.get(q, set()) for q in opposite.get(m.surface, ())))
        across = None if m.surface not in opposite else any(
            lines.get(n, n) in other or spans_house(s, m, members_of.get(lines.get(n, n), [])) for n in tied[m.id])
        out += rafter(s, m, tied[m.id], across, roofs, cut_ends)
    return out + ridges(s, cut_ends)


def raised_tie(s: Site, m: Member, tied: list[str], rests: list[float], ridge: float) -> tuple[float, str]:
    """Table R802.4.1(9): the factor on rafter m's span for its lowest tie's height above the top of the wall it
    rests on, over the ridge's; between the tabulated ratios, interpolated. With the ratio, for the message."""
    if not tied or not rests:
        return 1.0, ""
    wall = min(s.point(m, t)[2] for t in rests)
    if ridge - wall <= EPS:
        return 1.0, ""
    r = max(0.0, min(s.by_id[n].box.lo[2] for n in tied) - wall) / (ridge - wall)
    pts = RAISED_TIE
    if r <= pts[0][0]:
        return 1.0, ""
    for (r0, f0), (r1, f1) in zip(pts, pts[1:]):
        if r <= r1:
            return f0 + (f1 - f0) * (r - r0) / (r1 - r0), f"{r:.2f}"
    return pts[-1][1], f"{r:.2f}"   # above a third: the thrust check flags it


def seats(s: Site, m: Member, roofs: set[str]) -> list[Fault]:
    """R802.6: each rafter bears at least 1 1/2" on what it rests on (a wall plate or a beam), measured along the
    rafter at each seat; contacts close together in plan are one seat. Members of the roof it lies along (a rake
    plate) are not seats."""
    out, groups = [], []
    for n, area in s.g.bears[m.id].items():
        o = s.by_id.get(n)
        if o is None or n not in s.held or o.surface in roofs or abs(dot(axis(o), axis(m))) > 0.95:
            continue
        c = s.g.at[(m.id, n)]
        for gp in groups:
            if math.hypot(gp[0][0] - c[0], gp[0][1] - c[1]) <= SEAT_GROUP:
                gp[1].append((n, area))
                break
        else:
            groups.append((c, [(n, area)]))
    lengths = [sum(a for _, a in contacts) / m.width for _, contacts in groups]
    seated = any(x >= MIN_BEARING - EPS for x in lengths)
    for (c, contacts), length in zip(groups, lengths):
        if seated and length < TOUCH:
            continue      # a corner grazing a stud or plate beside a real seat, not a seat itself
        if length < MIN_BEARING - EPS:
            ms = [s.by_id[n] for n, _ in contacts]
            out.append(s.at(m, c, "bearing", True,
                            f"{name(m)} bears only {inches(length)} on {', '.join(name(x) for x in ms)}, minimum "
                            f"{inches(MIN_BEARING)} (IRC R802.6)", ms))
    return out


def uplift(s: Site, m: Member, spacing: float | None, span_ft: float) -> list[Fault]:
    """R802.11, Table R802.11: the wind uplift on rafter m, by its spacing, the roof's span (twice the rafter's run
    for a roof with an opposite slope) and pitch, interpolated between spans. Over 200 lb it needs a connector to
    the wall, which the model cannot show: soft, a reminder that one is required."""
    roof = s.surfs.get(m.surface)
    if spacing is None or not isinstance(roof, Roof):
        return []
    col = min((c for c in UPLIFT if c >= spacing - EPS), default=None)
    if col is None:
        return []
    k = 1 if roof.pitch >= 5.0 - EPS else 0
    rows = sorted(UPLIFT[col].items())
    if span_ft <= rows[0][0]:
        force = rows[0][1][k]
    elif span_ft >= rows[-1][0]:
        force = rows[-1][1][k] * span_ft / rows[-1][0]
    else:
        (a, fa), (b, fb) = next((x, y) for x, y in zip(rows, rows[1:]) if x[0] <= span_ft <= y[0])
        force = fa[k] + (fb[k] - fa[k]) * (span_ft - a) / (b - a)
    if force <= UPLIFT_NAILED + EPS:
        return []
    return [s.at(m, m.start if m.start[2] < m.end[2] else m.end, "uplift", False,
                 f"{name(m)}: wind lifts it about {force:.0f} lb (a {span_ft:.0f} ft roof span at {roof.pitch:.1f}:12, "
                 f"{col}\" on centre, 120 mph, Table R802.11), over the {UPLIFT_NAILED:.0f} lb nails hold, so it needs a "
                 f"rated connector to the wall (R802.11)")]


def spans_house(s: Site, m: Member, line: list[Member]) -> bool:
    """Whether a tie line reaches from where rafter m bears across the house in plan, as far as the mirror of
    its bearing beyond the ridge, less a foot: where the opposite eave wall is on a gable, even where a valley
    takes the opposite rafters."""
    a = axis(m)
    run = math.hypot(a[0], a[1])
    d = (a[0] / run, a[1] / run, 0.0) if a[2] > 0 else (-a[0] / run, -a[1] / run, 0.0)
    rests = [dot(s.g.at[(m.id, n)], d) for n in s.g.bears[m.id]]
    if not rests:
        return False
    foot, top = min(rests), max(dot(p, d) for p in m.points)
    far = max((dot(p, d) for o in line for p in o.points), default=foot)
    return far - foot >= 2 * (top - foot) - 12.0


def rafter(s: Site, m: Member, tied: list[str], across: bool | None, roofs: set[str], cut_ends: dict) -> list[Fault]:
    """One rafter (see rafters). cut_ends collects, for each member it butts at its top, the deepest plumb cut."""
    g, a = s.g, axis(m)
    run = math.hypot(a[0], a[1])

    def where(n: str) -> float:   # along m to the middle of where n touches it, found in plan
        c = g.at[(m.id, n)]
        return min(max(sum((c[k] - m.start[k]) * a[k] for k in range(2)) / run ** 2, 0.0), m.length)

    def along(p) -> float:   # along m to the point nearest p, found in plan
        return min(max(sum((p[k] - m.start[k]) * a[k] for k in range(2)) / run ** 2, 0.0), m.length)

    out = []
    rests = [where(n) for n in g.bears[m.id] if n in s.held]
    for n in g.bears[m.id]:   # a member it lies along (a gable wall's rake plate) holds it all the way
        if n in s.held and abs(dot(axis(s.by_id[n]), a)) > 0.95:
            rests += [along(s.by_id[n].start), along(s.by_id[n].end)]
    rests = sorted(rests)
    top = [n for n in g.side[m.id] if n in s.held and where(n) > m.length - 3 * m.depth]
    for n in top:     # a ridge board, hip or valley runs across the rafter in plan; an opposite rafter met
        o = axis(s.by_id[n])   # head on (with a gusset, IRC R802.3) runs the same way and is no ridge
        across = abs(o[0] * a[0] + o[1] * a[1]) < 0.9 * run * math.hypot(o[0], o[1]) if math.hypot(o[0], o[1]) > EPS else True
        if s.by_id[n].surface in roofs and abs(dot(g.facing[(m.id, n)], a)) > 0.5 and across:
            if m.depth / run > cut_ends.get(n, (0.0, None))[0]:
                cut_ends[n] = (m.depth / run, m)
    butts = [where(n) for n in top]
    sup = sorted(rests + butts[:1] if butts and rests and max(butts) > max(rests) else rests)
    spacing = s.gaps.get(m.id)
    col = column(spacing)
    limit = RAFTER_RUN.get(m.depth, {}).get(col) if col else None
    lo, hi = m.box.lo[2], m.box.hi[2]
    factor, raised = raised_tie(s, m, tied, rests, hi)
    for t0, t1 in zip(sup, sup[1:]):
        if limit is None or (t1 - t0) * run > limit * factor + EPS:
            out.append(s.at(m, s.point(m, (t0 + t1) / 2), "span", True,
                            f"{name(m)} spans {ftin((t1 - t0) * run)} level between supports, limit "
                            + ((f"{ftin(limit * factor)} for a {m.section} rafter at {col:g}\" on centre"
                                + (f" ({ftin(limit)} x {factor:.2f}: its tie is {raised} of the way up to the ridge, "
                                   f"Table R802.4.1(9))" if factor < 1 else "")) if limit else
                               f"none: no table for {m.section} rafters {inches(spacing or 0)} apart")))
    out += seats(s, m, roofs)
    if rests:
        out += uplift(s, m, spacing, (max(sup) - min(rests)) * run * (2 if across is not None else 1) / 12)
    if any(s.point(m, t)[2] >= lo + 2 * (hi - lo) / 3 for t in rests):
        return out           # it rests on something high up (a gable wall, a beam)
    ev = s.surfs[m.surface].ev
    if abs(a[0] * ev[0] + a[1] * ev[1]) < 0.99 * run * math.hypot(ev[0], ev[1]):
        return out           # a hip or valley rafter, across the slope: its thrust is not checked yet
    low = 0.0 if a[2] > 0 else m.length
    contacts = [(abs(where(n) - low), n in g.side[m.id] and s.by_id[n].surface in roofs)
                for n in [*g.bears[m.id], *g.side[m.id]] if n in s.held]
    if contacts and min(contacts)[1] and min(contacts)[0] < 3 * m.depth:
        return out           # its foot hangs on a valley or hip (a jack): that carries it
    if not tied:
        flat = sorted((round(g.at[(m.id, n)][2] - lo), n) for n in [*g.side[m.id], *g.bears[m.id]]
                      if n in s.by_id and level(s.by_id[n]) and s.by_id[n].surface != m.surface)
        seen = (f"; the level framing it touches is {', '.join(f'{n} {ftin(h)} up' for h, n in flat[:3])}, and the "
                f"lower third ends {ftin((hi - lo) / 3)} up" if flat else "; nothing level is nailed to it")
        out.append(s.at(m, s.point(m, m.length / 4), "thrust", True,
                        f"{name(m)} has no tie nailed to it in the lower third of its rise (a ceiling joist or "
                        f"rafter tie), so it pushes its wall out" + seen))
    elif across is False:
        out.append(s.at(m, s.point(m, m.length / 4), "thrust", True,
                        f"{name(m)} is tied by {', '.join(tied[:2])}, but that tie does not reach the rafters on the "
                        f"opposite slope: ceiling joists must run across the house in one piece, lap 3\" face to face, "
                        f"or butt over a bearing wall (IRC R802.5.2), so it pushes its wall out"))
    return out
