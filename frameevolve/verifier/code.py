"""The IRC's prescriptive rules for light-frame houses (2021 IRC, chapters 5, 6 and 8): what a plan reviewer
would fail beyond the physics. Studs by size and load, headers with their jacks and kings, bearing walls over the
floor below, notches, in-line framing on a single top plate, ridge and valley depth, and lateral restraint.
Each limit names its section.
"""
from __future__ import annotations

from frameevolve import solid
from frameevolve.geometry import EPS, dot, unit
from frameevolve.model import Floor, Member, Roof, Wall
from frameevolve.units import ftin, inches
from frameevolve.verifier.report import Fault
from frameevolve.verifier.site import (Site, along, axis, bearing_wall, floors_above, full_height, level, name,
                                       nominal, on_edge, supports, vertical)

# Table R602.3(5): stud spacing in a bearing wall by stud depth, for the floors it carries over its roof and
# ceiling (0, 1, 2); None: not permitted.
STUD_SPACING = {3.5: (24.0, 16.0, None), 5.5: (24.0, 24.0, 16.0)}
NONBEARING_SPACING = 24.0   # Table R602.3(5): studs in a wall that carries nothing
STUD_HEIGHT = 120.0         # Table R602.3(5): a bearing wall stud, 10 ft between points of lateral support
NONBEARING_HEIGHT = {3.5: 168.0, 5.5: 240.0}   # Table R602.3(5): non-bearing 2x4 14 ft, 2x6 20 ft
# Table R602.7(1), headers in an exterior bearing wall carrying roof and ceiling, 30 psf ground snow, 24 ft
# building width: (plies, depth) -> (span, jack studs at each end). Note f: 0.70 of the span for a 2x8 or
# deeper header whose top is not braced (cripples on it rather than the top plate).
HEADER_SPAN = {(1, 5.5): (37.0, 2), (1, 7.25): (47.0, 2), (1, 9.25): (56.0, 2), (1, 11.25): (65.0, 2),
               (2, 3.5): (37.0, 1), (2, 5.5): (55.0, 1), (2, 7.25): (69.0, 1), (2, 9.25): (82.0, 2),
               (2, 11.25): (97.0, 2)}
UNBRACED_HEADER = 0.70      # Table R602.7(1) note f
# Table R602.7.5: full-height (king) studs at each end of a header in an exterior wall, by header span, for
# winds under 140 mph, exposure B (Cambridge, MA, about 128 mph): (longest span, kings).
KINGS = ((48.0, 1), (96.0, 2), (168.0, 3), (216.0, 4))
INLINE = 1.0                # R602.3.2 exception: on a single top plate, joists and rafters within 1" of a stud
INLINE_DOUBLE = 5.0         # R602.3.3: framing over 16" o.c. on a double 2x4 top plate, within 5" of a stud
NOTCH = 1 / 6               # R502.8.1, R802.7.1: a notch at most 1/6 of the depth deep...
NOTCH_LENGTH = 1 / 3        # ... and 1/3 of the depth long, and none in the middle third of the span
END_NOTCH = 1 / 4           # R502.8.1, R802.7.1, R802.7.1.2, WFCM 3.5.1.1.4: at an end or a bearing, 1/4 deep
TAIL_DEPTH = 3.5            # R802.7.1.1: a notched rafter overhang keeps 3 1/2" of depth
STUD_NOTCH = {True: 0.25, False: 0.40}   # R602.6: a notch in a bearing / non-bearing stud, share of its depth
MIN_PITCH = 3.0             # R802.4.4: under 3:12, ridges, hips and valleys are beams to design, not boards
RESTRAINT_RATIO = 5         # R802.8: roof framing deeper than 5 times its thickness (nominal) is held at bearings


# ---------------------------------------------------------------------------------------------- walls

def studs(s: Site) -> list[Fault]:
    """Table R602.3(5) and R602.3: stud spacing and height by depth and load, and studs in one piece from the
    bottom plate to the top plate."""
    out = []
    for w in s.house.walls:
        vert = [m for m in s.on.get(w.id, []) if vertical(m)]
        if not vert:
            continue
        bearing, floors = bearing_wall(s, w), floors_above(s.house, w)
        for m in vert:
            under = [s.by_id[n] for n in s.g.bears[m.id] if n in s.by_id and vertical(s.by_id[n])]
            for n in under:
                out.append(s.at(m, m.box.lo, "studs", True, f"{name(m)} stands on {name(n)}: a stud runs in one "
                                f"piece from the bottom plate to the top plate (R602.3)", [n]))
            limit = STUD_HEIGHT if bearing else NONBEARING_HEIGHT.get(m.depth, STUD_HEIGHT)
            if m.length > limit + EPS:
                out.append(s.at(m, m.box.centre, "studs", True, f"{name(m)} is {ftin(m.length)} tall; a "
                                f"{'bearing' if bearing else 'non-bearing'} {m.section} stud may be {ftin(limit)} "
                                f"between supports (Table R602.3(5))"))
        full = [m for m in vert if w.local_box(m).lo[1] <= w.height / 2 <= w.local_box(m).hi[1]]
        if not full:
            continue
        d = min(m.depth for m in full)
        limit = STUD_SPACING.get(d, (24.0, 24.0, 16.0))[min(floors, 2)] if bearing else NONBEARING_SPACING
        u = lambda m: (w.local_box(m).lo[0] + w.local_box(m).hi[0]) / 2
        if limit is None:
            out.append(s.flag("studs", True, f"{w.id}: {full[0].section} studs cannot carry {floors} floors over "
                              f"the roof (Table R602.3(5)); this wall needs 2x6", w.id, w.length / 2, w.height / 2,
                              [full[0].id], sorted({m.rule for m in full})))
            continue
        cs = sorted(u(m) for m in full)
        wide = [(a, b) for a, b in zip(cs, cs[1:]) if b - a > limit + 0.5
                and not any(o.u0 < b and o.u1 > a for o in w.openings)]
        if wide:
            a, b = max(wide, key=lambda x: x[1] - x[0])
            out.append(s.flag("studs", True, f"{w.id}: studs {inches(b - a)} apart at u {ftin(a)}"
                              f"{f' and {len(wide) - 1} more bays' if len(wide) > 1 else ''}; {full[0].section} "
                              f"studs in a {'bearing' if bearing else 'non-bearing'} wall carrying {floors} floors "
                              f"may be {inches(limit)} on centre (Table R602.3(5))", w.id, (a + b) / 2,
                              w.height / 2, [], sorted({m.rule for m in full})))
    return out


def headers(s: Site, w: Wall) -> dict[str, tuple]:
    """The headers over each opening of a wall: member id -> (opening, plies), the on-edge level members right
    over it that reach across it."""
    out = {}
    for o in w.openings:
        over = []
        for m in s.on.get(w.id, []):
            if level(m) and on_edge(m):
                b = w.local_box(m)
                if b.lo[0] <= o.u0 + EPS and b.hi[0] >= o.u1 - EPS and o.v1 - EPS <= b.lo[1] <= o.v1 + 12:
                    over.append((round(b.lo[1], 2), m))
        if over:
            low = min(v for v, _ in over)
            ply = [m for v, m in over if v == low]
            for m in ply:
                out[m.id] = (o, len(ply))
    return out


def header_checks(s: Site) -> list[Fault]:
    """Table R602.7(1): a header's span by plies and depth, the jack studs under each end; Table R602.7.5: the
    king studs beside each end in an exterior wall."""
    out = []
    for w in s.house.walls:
        if not bearing_wall(s, w):
            continue
        done = set()
        for mid, (o, plies) in headers(s, w).items():
            if o.id in done:
                continue
            done.add(o.id)
            m = s.by_id[mid]
            span, nj = HEADER_SPAN.get((min(plies, 2), m.depth), (0.0, 2))
            cripples = any(vertical(s.by_id[n]) for n in s.g.carries[m.id] if n in s.by_id)
            if cripples and m.depth >= 7.25:
                span *= UNBRACED_HEADER
            clear = o.u1 - o.u0
            if clear > span + EPS:
                out.append(s.at(m, m.box.centre, "header", True,
                                f"{plies}-ply {m.section} header over {o.kind} {o.id} on {w.id} spans {ftin(clear)}; "
                                f"the limit is {ftin(span) if span else 'none, it is not in the table'}"
                                f"{', its top braced only by cripples' if cripples and m.depth >= 7.25 else ''} "
                                f"(Table R602.7(1))"))
            b = w.local_box(m)
            jacks = {"left": set(), "right": set()}
            for x in (mid, *[k for k, (oo, _) in headers(s, w).items() if oo is o]):
                for n in s.g.bears[x]:
                    nb = s.by_id.get(n)
                    if nb and vertical(nb):
                        c = (w.local_box(nb).lo[0] + w.local_box(nb).hi[0]) / 2
                        jacks["left" if c < (o.u0 + o.u1) / 2 else "right"].add(n)
            for end, js in jacks.items():
                if len(js) < nj:
                    out.append(s.at(m, w.world(o.u0 if end == "left" else o.u1, o.v1, 0), "header", True,
                                    f"{plies}-ply {m.section} header over {o.kind} {o.id} on {w.id} rests on "
                                    f"{len(js)} jack stud(s) at its {end} end; a span of {ftin(clear)} needs {nj} "
                                    f"(Table R602.7(1))"))
            if w.role == "exterior":
                need = next((k for most, k in KINGS if clear <= most), KINGS[-1][1])
                for end, u in (("left", b.lo[0]), ("right", b.hi[0])):
                    k = kings(s, w, u, -1 if end == "left" else 1)
                    if k < need:
                        out.append(s.at(m, w.world(u, w.height / 2, 0), "kings", False,
                                        f"{o.kind} {o.id} on {w.id}: {k} full-height stud(s) at its {end} end; a header "
                                        f"spanning {ftin(clear)} needs {need} (Table R602.7.5)"))
    return out


def kings(s: Site, w: Wall, u: float, way: int) -> int:
    """Full-height studs side by side starting at u on a wall and going the way given (-1 left, +1 right)."""
    full = sorted((w.local_box(m).lo[0], w.local_box(m).hi[0]) for m in full_height(s, w))
    n, edge = 0, u
    while True:
        nxt = [x for x in full if (abs(x[1] - edge) <= EPS if way < 0 else abs(x[0] - edge) <= EPS)]
        if not nxt:
            return n
        n += 1
        edge = nxt[0][0] if way < 0 else nxt[0][1]


def offsets(s: Site) -> list[Fault]:
    """R502.4: a bearing wall standing on floor joists that cross it is no further from the support under the
    joists than their depth."""
    out = []
    for w in s.house.walls:
        if not w.below or not bearing_wall(s, w) or not isinstance(s.house.surface(w.below), Floor):
            continue
        worst = None
        for p in s.on.get(w.id, []):
            if vertical(p):
                continue
            for j in s.g.bears[p.id]:
                J = s.by_id.get(j)
                if not J or J.surface != w.below or not level(J) or abs(dot(axis(J), w.dir)) > 0.1:
                    continue
                t = along(J, s.g.at[(p.id, j)])
                under = supports(s, J) + [along(J, s.g.at[(J.id, n)]) for n in s.g.side[J.id]
                                          if abs(dot(s.g.facing[(J.id, n)], axis(J))) > 0.9]
                if not under:
                    continue
                off = min(abs(t - x) for x in under)
                if off > J.depth + EPS and (worst is None or off > worst[0]):
                    worst = (off, p, J)
        if worst:
            off, p, J = worst
            out.append(s.at(p, s.g.at[(p.id, J.id)], "offset", True,
                            f"bearing wall {w.id} stands {ftin(off)} from the support under {name(J)}; a bearing "
                            f"wall across joists may be at most their depth, {inches(J.depth)}, from it (R502.4)", [J]))
    return out


def inline(s: Site) -> list[Fault]:
    """R602.3.2 and R602.3.3: a joist or rafter on a single top plate lands within 1" of a stud; on a double 2x4
    plate, framing more than 16" apart lands within 5" of one."""
    out = []
    for w in s.house.walls:
        mine = {m.id for m in s.on.get(w.id, [])}
        for P in s.on.get(w.id, []):
            if not level(P) or on_edge(P):
                continue
            below = [s.by_id[n] for n in s.g.bears[P.id] if n in mine]
            double = [q for q in below if level(q) and not on_edge(q)]
            plate = double[0] if double else P
            if double and plate.depth >= 5.5:
                continue
            posts = [(w.local_box(n).lo[0] + w.local_box(n).hi[0]) / 2 for n in
                     (s.by_id[k] for k in s.g.bears[plate.id] if k in mine) if vertical(n)]
            beams = [w.local_box(n) for n in (s.by_id[k] for k in s.g.bears[plate.id] if k in mine) if on_edge(n)]
            for x in s.g.carries[P.id]:
                X = s.by_id.get(x)
                if not X or X.surface == w.id or abs(dot(axis(X), w.dir)) > 0.5:
                    continue
                if double and (s.gaps.get(x) or 24.0) <= 16.0 + 0.5:
                    continue
                c = w.local(s.g.at[(x, P.id)])[0]
                if any(b.lo[0] - EPS <= c <= b.hi[0] + EPS for b in beams):
                    continue        # over a header: the header carries it
                tol = INLINE_DOUBLE if double else INLINE
                if not posts or min(abs(c - p) for p in posts) > tol + EPS:
                    near = min((abs(c - p) for p in posts), default=None)
                    out.append(s.at(X, s.g.at[(x, P.id)], "in line", True,
                                    f"{name(X)} lands on the {'double' if double else 'single'} top plate of {w.id} "
                                    f"{inches(near) + ' from' if near is not None else 'with no'} stud under it; it must "
                                    f"be within {inches(tol)} ({'R602.3.3' if double else 'R602.3.2'})", [P]))
    return out


# ------------------------------------------------------------------------------------- floors and roofs

def extents(m: Member, notches: list, step: float) -> list[tuple[float, float | None]]:
    """m's depth at sections along it: (distance from its start, how deep it is there, or None past its ends)."""
    pieces = solid.solid(m.start, m.end, m.up, m.width, m.depth, m.cuts, notches)
    a, up = axis(m), unit(m.up)
    out = []
    for i in range(int(m.length / step)):
        t = (i + 0.5) * step
        polys = solid.section(pieces, a, dot(a, m.start) + t)
        vals = [dot(up, q) for poly in polys for q in poly]
        out.append((t, max(vals) - min(vals) if vals else None))
    return out


def notches(s: Site) -> list[Fault]:
    """R502.8.1, R802.7.1, R602.6: how deep a notch takes a member, measured square to it. At an end or over a
    bearing, at most 1/4 of the depth (a rafter's birdsmouth, a ceiling joist's taper), and a notched overhang keeps
    3 1/2"; elsewhere 1/6 deep, 1/3 of the depth long, and none in the middle third of the span. A stud may lose a
    quarter of its depth, or 40% in a wall that carries nothing."""
    out = []
    walls = {w.id: w for w in s.house.walls}
    for m in s.frame.members:
        if not m.notches:
            continue
        step = 0.5
        full = extents(m, [], step)
        cut = extents(m, m.notches, step)
        lost = [(t, (f or 0.0) - (c or 0.0)) for (t, f), (_, c) in zip(full, cut) if f]
        runs, cur = [], []
        for t, r in lost:
            if r > 0.06:
                cur.append((t, r))
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        if not runs:
            continue
        ends = [t for t, f in full if f]
        rests = supports(s, m)
        for run in runs:
            t0, t1 = run[0][0] - step / 2, run[-1][0] + step / 2
            r = max(x for _, x in run)
            d = m.depth
            if vertical(m):
                w = walls.get(m.surface)
                bearing = w is not None and bearing_wall(s, w)
                if r > STUD_NOTCH[bearing] * d + EPS:
                    out.append(s.at(m, m.box.centre, "notch", True, f"{name(m)} is notched {inches(r)} deep, more "
                                    f"than {round(100 * STUD_NOTCH[bearing])}% of its {inches(d)} (R602.6)"))
                continue
            at_end = t0 <= ends[0] + step or t1 >= ends[-1] - step
            over = [x for x in rests if t0 - d <= x <= t1 + d]
            p = tuple(m.start[k] + axis(m)[k] * (t0 + t1) / 2 for k in range(3))
            if at_end or over:
                tail = over and (min(over) - ends[0] > d or ends[-1] - max(over) > d)
                if r > END_NOTCH * d + EPS:
                    out.append(s.at(m, p, "notch", True, f"{name(m)} is notched {inches(r)} deep "
                                    f"{'over its bearing' if over else 'at its end'}; at most a quarter of its "
                                    f"{inches(d)} depth, {inches(END_NOTCH * d)} (R502.8.1, R802.7.1)"))
                elif tail and d - r < TAIL_DEPTH - EPS:
                    out.append(s.at(m, p, "notch", True, f"{name(m)} keeps only {inches(d - r)} where it is notched "
                                    f"over its bearing; a notched overhang keeps {inches(TAIL_DEPTH)} (R802.7.1.1)"))
                continue
            left = max((x for x in rests if x <= t0), default=ends[0])
            right = min((x for x in rests if x >= t1), default=ends[-1])
            third = (right - left) / 3
            why = []
            if r > NOTCH * d + EPS:
                why.append(f"{inches(r)} deep (at most {inches(NOTCH * d)})")
            if t1 - t0 > NOTCH_LENGTH * d + EPS:
                why.append(f"{inches(t1 - t0)} long (at most {inches(NOTCH_LENGTH * d)})")
            if t1 > left + third and t0 < right - third:
                why.append("in the middle third of its span")
            if why:
                out.append(s.at(m, p, "notch", True, f"{name(m)} has a notch " + ", ".join(why) +
                                " (R502.8.1, R802.7.1)"))
    return out


def ridges(s: Site, cut_ends: dict[str, tuple[float, Member]]) -> list[Fault]:
    """R802.3, R802.4.3: a ridge board, hip or valley is at least as deep as the cut end of the rafters framing
    into it; R802.4.4: under 3:12 they are beams to design. cut_ends: member id -> (deepest cut end into it,
    that rafter)."""
    out = []
    for n, (need, m) in cut_ends.items():
        R = s.by_id[n]
        if R.depth + EPS < need:
            out.append(s.at(R, R.box.centre, "ridge", True,
                            f"{name(R)} is {inches(R.depth)} deep; the rafters framing into it, like {name(m)}, have "
                            f"a {inches(need)} plumb cut, and it must be at least that deep (R802.3, R802.4.3)", [m]))
    for r in s.house.roofs:
        if r.pitch < MIN_PITCH and s.on.get(r.id):
            m = s.on[r.id][0]
            out.append(s.at(m, m.box.centre, "ridge", True, f"roof {r.id} is {r.pitch}:12; under 3:12 its ridge, "
                            f"hips and valleys must be designed beams (R802.4.4)"))
    return out


def restraint(s: Site) -> list[Fault]:
    """R502.7: each end of a floor joist is held against rolling over by blocking, a rim or header, or a stud
    beside it; R802.8: so is roof and ceiling framing deeper than 5 times its thickness, at each bearing."""
    out = []
    for m in s.frame.members:
        x = s.surfs.get(m.surface)
        if isinstance(x, Wall) or x is None or vertical(m) or not on_edge(m) and not isinstance(x, Roof):
            continue
        floor = isinstance(x, Floor) and x.role == "floor"
        if not floor and nominal(m) / 2 <= RESTRAINT_RATIO:
            continue
        if sum(s.g.bears[m.id].values()) / m.width >= m.length / 2:
            continue    # bears along its length on a wall: a rim or band, itself the restraint
        a = axis(m)
        held_at = []
        for n in s.g.side[m.id]:      # what it bears on does not hold it upright (a rafter's heel against its plate)
            o = s.by_id.get(n)
            if o and n not in s.g.bears[m.id] and (abs(dot(axis(o), a)) < 0.7 or vertical(o)):
                held_at.append(along(m, s.g.at[(m.id, n)]))
        if floor:
            spots = [0.0, m.length]
            where = "end"
        else:
            spots = supports(s, m)
            where = "bearing"
        for t in spots:
            if not any(abs(h - t) <= m.depth + 2.0 for h in held_at):
                p = tuple(m.start[k] + a[k] * t for k in range(3))
                out.append(s.at(m, p, "restraint", False, f"{name(m)} has nothing to stop it rolling over at its "
                                f"{where}: blocking, a rim or a header (R502.7, R802.8)"))
    return out
