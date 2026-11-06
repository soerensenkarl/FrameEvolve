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
from frameevolve.verifier.site import Site, axis, column, level, name, on_edge, vertical

MAX_CLEAR_FLAT = 24.0    # a plate laid flat, between supports: the 24" module
# A beam on edge in a wall (not a header over an opening; those are in code.py), clear span by depth: IRC Table
# R602.7(1), two plies carrying roof and ceiling, 24 ft building width, 30 psf ground snow.
WALL_BEAM_CLEAR = {3.5: 37.0, 5.5: 55.0, 7.25: 69.0, 9.25: 82.0, 11.25: 97.0}
# Floor joist clear span: IRC Table R502.3.1(2), 40 psf live, 10 psf dead, L/360.
JOIST_CLEAR = {5.5: {12: 123.0, 16: 112.0, 19.2: 105.0, 24: 97.0}, 7.25: {12: 162.0, 16: 147.0, 19.2: 138.0, 24: 123.0},
               9.25: {12: 207.0, 16: 185.0, 19.2: 169.0, 24: 151.0}, 11.25: {12: 247.0, 16: 214.0, 19.2: 195.0, 24: 175.0}}
# Ceiling joist clear span: IRC Table R802.5.1(1), attic without storage, 10 psf live, 5 psf dead (2x12 as 2x10).
CEILING_CLEAR = {3.5: {12: 142.0, 16: 129.0, 19.2: 122.0, 24: 113.0}, 5.5: {12: 224.0, 16: 203.0, 19.2: 191.0, 24: 177.0},
                 7.25: {12: 295.0, 16: 268.0, 19.2: 252.0, 24: 225.0}, 9.25: {12: 312.0, 16: 312.0, 19.2: 308.0, 24: 275.0},
                 11.25: {12: 312.0, 16: 312.0, 19.2: 308.0, 24: 275.0}}
# Rafter span, measured level: IRC Table R802.4.1(5), 50 psf ground snow (the table above Cambridge's 40 psf),
# ceiling not attached to the rafters, 10 psf dead, L/180.
RAFTER_RUN = {3.5: {12: 92.0, 16: 80.0, 19.2: 73.0, 24: 65.0}, 5.5: {12: 135.0, 16: 117.0, 19.2: 107.0, 24: 95.0},
              7.25: {12: 171.0, 16: 148.0, 19.2: 135.0, 24: 121.0}, 9.25: {12: 209.0, 16: 181.0, 19.2: 165.0, 24: 148.0},
              11.25: {12: 242.0, 16: 210.0, 19.2: 191.0, 24: 171.0}}
MAX_OVERHANG = 2.0       # a loaded member past its last support
MIN_BEARING = 1.5        # IRC R502.6, R802.6: joists, beams and rafters bear 1 1/2" on wood
MIN_BEARING_FLAT = 0.75  # a plate laid flat: half a stud
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

        for s0, s1, n in sup:
            if s0 < s1 and s1 - s0 < least - EPS:
                out.append(s.at(m, point((s0 + s1) / 2), "bearing", True,
                                f"{name(m)} bears only {inches(s1 - s0)} on {name(s.by_id[n])}, minimum {inches(least)}",
                                [s.by_id[n]]))
        reach = sup[0][1]
        for s0, s1, n in sup[1:]:      # no table (a beam or header in a floor, a rim): analysis.py checks it
            gap = s0 - reach
            if limit is not None and gap > limit + EPS:
                out.append(s.at(m, point((reach + s0) / 2), "span", True,
                                f"{name(m)} spans {ftin(gap)} clear between supports, limit {ftin(limit)} for {kind}"))
            reach = max(reach, s1)
        for over in (sup[0][0] - a0, a1 - max(s1 for _, s1, _ in sup)):
            if over > MAX_OVERHANG + EPS:
                x = a0 + over / 2 if over == sup[0][0] - a0 else a1 - over / 2
                out.append(s.at(m, point(x), "overhang", True,
                                f"{name(m)} runs {ftin(over)} past its last support, limit {inches(MAX_OVERHANG)}"))
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
    its rise whose tie line also ties a rafter on the slope across the ridge. Hips, valleys and the jacks
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
    out, cut_ends = [], {}
    for m in rs:
        other = set().union(*(reach.get(q, set()) for q in opposite.get(m.surface, ())))
        across = None if m.surface not in opposite else any(lines.get(n, n) in other for n in tied[m.id])
        out += rafter(s, m, tied[m.id], across, roofs, cut_ends)
    return out + ridges(s, cut_ends)


def rafter(s: Site, m: Member, tied: list[str], across: bool | None, roofs: set[str], cut_ends: dict) -> list[Fault]:
    """One rafter (see rafters). cut_ends collects, for each member it butts at its top, the deepest plumb cut."""
    g, a = s.g, axis(m)
    run = math.hypot(a[0], a[1])

    def where(n: str) -> float:   # along m to the middle of where n touches it, found in plan
        c = g.at[(m.id, n)]
        return min(max(sum((c[k] - m.start[k]) * a[k] for k in range(2)) / run ** 2, 0.0), m.length)

    out = []
    rests = sorted(where(n) for n in g.bears[m.id] if n in s.held)
    top = [n for n in g.side[m.id] if n in s.held and where(n) > m.length - 3 * m.depth]
    for n in top:
        if s.by_id[n].surface in roofs and abs(dot(g.facing[(m.id, n)], a)) > 0.5:
            if m.depth / run > cut_ends.get(n, (0.0, None))[0]:
                cut_ends[n] = (m.depth / run, m)
    butts = [where(n) for n in top]
    sup = sorted(rests + butts[:1] if butts and rests and max(butts) > max(rests) else rests)
    spacing = s.gaps.get(m.id)
    col = column(spacing)
    limit = RAFTER_RUN.get(m.depth, {}).get(col) if col else None
    for t0, t1 in zip(sup, sup[1:]):
        if limit is None or (t1 - t0) * run > limit + EPS:
            out.append(s.at(m, s.point(m, (t0 + t1) / 2), "span", True,
                            f"{name(m)} spans {ftin((t1 - t0) * run)} level between supports, limit "
                            + (f"{ftin(limit)} for a {m.section} rafter at {col:g}\" on centre" if limit else
                               f"none: no table for {m.section} rafters {inches(spacing or 0)} apart")))
    lo, hi = m.box.lo[2], m.box.hi[2]
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
