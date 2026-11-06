"""Can it be built: as prefab panels made in a shop, cut by an automated saw, trucked to site and lifted into
place one after another, bottom up.

A panel is the members a grammar builds into one named piece (Member.panel): a wall panel, a floor cassette, a
roof panel. It is flat (one surface, one layer of framing, not a volume), framed all round (a member along every
edge of its outline) so it holds its shape when lifted and its boards end on wood, one piece, small enough to
truck and light enough to lift.
Members without a panel are cut and nailed on site; cost.py charges them more, and a crane lift per panel.

The saw: every piece is cut from stock by a standard automated framing saw. It crosscuts square or at a miter
(the board lying on its wide face) up to 60 degrees and a bevel (tilted through its thickness) up to 45, cuts
pockets and notches with up to three faces (a birdsmouth, a housing), holds no piece shorter than 6", and does
not rip along a board's length.

Erection: panels and site pieces go up one at a time, bottom up. There must be an order in which every one
rests on what is already up (or on the ground), and every panel can be lowered straight down by the crane
without passing through anything already up (a piece built on site is slid into place by hand). The verifier
builds that order, lowest first, and reports what blocks it.
"""
from __future__ import annotations

import math

from frameevolve import solid, surface
from frameevolve.geometry import EPS, cross, dot, unit
from frameevolve.graph import GROUND
from frameevolve.model import Member
from frameevolve.surface import hull
from frameevolve.units import ftin, inches
from frameevolve.verifier.report import Fault
from frameevolve.verifier.site import Site, axis, name

PANEL_LONG = 480.0        # 40 ft: the longest panel on a 48 ft flatbed, with room for tie-downs
PANEL_SHORT = 138.0       # 11'-6": stood on edge on a drop-deck trailer (2 ft deck) under the 13'-6" legal height
PANEL_THICK = 24.0        # a panel is one layer of framing, no deeper than 2 ft: a panel, not a volume
PANEL_WEIGHT = 3000.0     # lb: what a boom truck lifts at a 40 ft reach
DENSITY = 26.0 / 1728     # lb per cubic inch: Spruce-Pine-Fir at 15% moisture, 26 lb/cu ft
SKIN = 2.0 / 144          # lb per square inch: 7/16" OSB sheathing or 23/32" subfloor nailed on in the shop, ~2 psf
MIN_PIECE = 6.0           # the shortest piece an automated saw holds and cuts
MITER = 60.0              # degrees off square a saw cuts in the board's wide face
BEVEL = 45.0              # degrees a saw tilts through the board's thickness
NOTCH_FACES = 3           # faces a saw or router cuts in one notch: a birdsmouth has 2, a housing 3


# ------------------------------------------------------------------------------------------------ panels

def panels(s: Site) -> list[Fault]:
    """Every panel: flat on one surface, small enough to truck, light enough to lift, one piece, framed at both
    ends of its length."""
    out = []
    for p, ms in s.frame.panels().items():
        on = sorted({m.surface for m in ms})
        x = s.surfs.get(on[0])
        rules = sorted({m.rule for m in ms})
        ids = [m.id for m in ms]
        if len(on) > 1 or x is None:
            out.append(s.at(ms[0], ms[0].box.centre, "panel", True, f"panel {p} has members on {', '.join(on)}: a "
                            f"panel is flat, on one wall, floor or roof", ms[1:4]))
            continue
        boxes = [x.local_box(m) for m in ms]
        lo = [min(b.lo[k] for b in boxes) for k in range(3)]
        hi = [max(b.hi[k] for b in boxes) for k in range(3)]
        du, dv, dw = (hi[k] - lo[k] for k in range(3))
        here = lambda check, msg: s.flag(check, True, msg, x.id, (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, ids, rules)
        if max(du, dv) > PANEL_LONG + EPS or min(du, dv) > PANEL_SHORT + EPS:
            out.append(here("panel", f"panel {p} on {x.id} is {ftin(du)} by {ftin(dv)}: too big to truck; a panel is at "
                                     f"most {ftin(PANEL_LONG)} long and {ftin(PANEL_SHORT)} wide"))
        if dw > PANEL_THICK + EPS:
            out.append(here("panel", f"panel {p} on {x.id} is {ftin(dw)} deep: not flat; a panel is one layer of "
                                     f"framing, at most {ftin(PANEL_THICK)}"))
        weight = sum(volume(m) for m in ms) * DENSITY + du * dv * SKIN
        if weight > PANEL_WEIGHT:
            out.append(here("panel", f"panel {p} on {x.id} weighs about {weight:,.0f} lb with its skin: too heavy to "
                                     f"lift; at most {PANEL_WEIGHT:,.0f} lb"))
        parts = pieces_of(s, ms)
        if len(parts) > 1:
            loose = min(parts, key=len)
            out.append(here("panel", f"panel {p} on {x.id} is {len(parts)} separate pieces, not one: "
                                     f"{', '.join(sorted(loose)[:4])} touch nothing else in it"))
        for (a, b) in unframed(x, ms):
            out.append(here("panel", f"panel {p} on {x.id} has nothing along its edge from u {ftin(a[0])}, v "
                                     f"{ftin(a[1])} to u {ftin(b[0])}, v {ftin(b[1])}: frame a panel all round, so it "
                                     f"holds its shape when lifted and its boards end on wood"))
    return out


def unframed(x, ms: list[Member]) -> list[tuple]:
    """The edges of a panel's outline (the hull of its members seen square to its surface, edges over a foot)
    with no member running along at least half of them."""
    shapes = [poly for m in ms for poly in surface.outlines(x, m)]
    rim = hull([q for poly in shapes for q in poly])
    out = []
    for a, b in zip(rim, rim[1:] + rim[:1]):
        L = math.dist(a, b)
        if L < 12.0:
            continue
        d = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        off = lambda q: abs((q[0] - a[0]) * d[1] - (q[1] - a[1]) * d[0])
        t = lambda q: (q[0] - a[0]) * d[0] + (q[1] - a[1]) * d[1]
        spans = sorted((max(0.0, min(t(p), t(q))), min(L, max(t(p), t(q)))) for poly in shapes
                       for p, q in zip(poly, poly[1:] + poly[:1]) if off(p) <= 0.3 and off(q) <= 0.3)
        covered, reach = 0.0, 0.0
        for s0, s1 in spans:
            covered += max(0.0, s1 - max(s0, reach))
            reach = max(reach, s1)
        if covered < 0.5 * L:
            out.append((a, b))
    return out


def volume(m: Member) -> float:
    return m.width * m.depth * m.length if m.plain else sum(solid.volume(p) for p in m.pieces)


def pieces_of(s: Site, ms: list[Member]) -> list[set[str]]:
    """The parts of a group of members that touch each other (bear or side by side)."""
    ids = {m.id for m in ms}
    out, seen = [], set()
    for m in ms:
        if m.id in seen:
            continue
        part, todo = set(), [m.id]
        while todo:
            a = todo.pop()
            if a in part:
                continue
            part.add(a)
            todo += [n for n in (*s.g.bears[a], *s.g.carries[a], *s.g.side[a]) if n in ids and n not in part]
        seen |= part
        out.append(part)
    return out


# --------------------------------------------------------------------------------------------- the saw

def cutting(s: Site) -> list[Fault]:
    """Every piece as the saw sees it: long enough to hold, each end cut within the saw's miter and bevel and
    not along the board, and each notch one the saw can cut."""
    out = []
    for m in s.frame.members:
        if m.length < MIN_PIECE - EPS:
            out.append(s.at(m, m.box.centre, "cut", True, f"{name(m)} is {inches(m.length)} long; the shortest piece an "
                            f"automated saw holds is {inches(MIN_PIECE)}"))
        a = axis(m)
        up = unit(m.up)
        thick = unit(cross(a, up))
        for n, _ in m.cuts:
            along, deep, through = abs(dot(n, a)), abs(dot(n, up)), abs(dot(n, thick))
            if along < 0.05:
                out.append(s.at(m, m.box.centre, "cut", True, f"{name(m)} is ripped along its length (a bevel or "
                                f"taper the length of the board): a saw crosscuts; drop it or design it out"))
                continue
            miter, bevel = math.degrees(math.atan2(deep, along)), math.degrees(math.atan2(through, along))
            if miter > MITER + 0.5 or bevel > BEVEL + 0.5:
                out.append(s.at(m, m.box.centre, "cut", True, f"{name(m)} has an end cut {miter:.0f} degrees off square "
                                f"in its face and {bevel:.0f} through its thickness; a saw cuts up to {MITER:.0f} and "
                                f"{BEVEL:.0f}"))
        for region in m.notches:
            faces, ripped = notch_faces(m, region)
            if ripped:
                out.append(s.at(m, m.box.centre, "cut", True, f"{name(m)} has a groove or chamfer along its length: a "
                                f"saw crosscuts and notches; drop it or design it out"))
            elif faces > NOTCH_FACES:
                out.append(s.at(m, m.box.centre, "cut", True, f"{name(m)} has a notch with {faces} faces: a saw cuts a "
                                f"notch with up to {NOTCH_FACES} (a birdsmouth, a housing)"))
    return out


def notch_faces(m: Member, region) -> tuple[int, bool]:
    """How many faces the saw cuts for a notch (planes of the region that bound wood taken out of m), and whether
    one of them runs along the board for more than twice its depth (a groove, not a notch)."""
    piece = solid.box_faces(m.start, m.end, m.up, m.width, m.depth)
    for n, d in m.cuts:
        piece = solid.clip(piece, tuple(n), d) if piece else piece
    for n, d in region:
        piece = solid.clip(piece, tuple(n), d) if piece else piece
    if not piece or solid.volume(piece) < 1e-3:
        return 0, False
    a = axis(m)
    faces, ripped = 0, False
    for n, d in region:
        on = [pts for fn, fd, pts in piece if dot(fn, tuple(n)) > 1 - 1e-6 and abs(fd - d) < 1e-6]
        if on and solid.area(on[0]) > 0.01:
            faces += 1
            if abs(dot(tuple(n), a)) < 0.05:
                ts = [dot(p, a) for p in on[0]]
                ripped |= max(ts) - min(ts) > 2 * m.depth
    return faces, ripped


# ------------------------------------------------------------------------------------------- erection

def units(s: Site) -> dict[str, list[Member]]:
    """What goes up as one: each panel, and each member built on site on its own."""
    out: dict[str, list[Member]] = {}
    for m in s.frame.members:
        out.setdefault(m.panel or m.id, []).append(m)
    return out


def erection(s: Site) -> list[Fault]:
    """Put everything up bottom first: each unit (a panel, or a piece built on site) goes up once everything it
    rests on is up, lowest first. A unit that rests on one that can only go up after it (a cycle) has no order;
    a unit with something already up over it cannot be lowered into place."""
    us = units(s)
    of = {m.id: k for k, ms in us.items() for m in ms}
    bears = lambda n: bool(s.g.bears.get(n))
    needs = {}
    for k, ms in us.items():
        need = set()
        for m in ms:
            under = [n for n in s.g.bears[m.id] if n != GROUND]
            if not bears(m.id):     # held from the side (blocking, a flat head): by what beside it bears
                under = [n for n in s.g.side[m.id] if bears(n)]
            need |= {of[n] for n in under if n in of and of[n] != k}
        needs[k] = need
    bottom = {k: min(m.box.lo[2] for m in ms) for k, ms in us.items()}
    up, order, out = set(), [], []
    grid: dict[tuple[int, int], list[Member]] = {}
    todo = set(us)
    while todo:
        ready = [k for k in todo if needs[k] <= up]
        stuck = not ready
        k = min(ready or todo, key=lambda x: (bottom[x], x))
        if stuck:
            waits = sorted(needs[k] - up)
            out.append(fault_at(s, us[k], f"{label(k, us)} rests on {', '.join(label(w, us) for w in waits[:3])}, "
                                          f"which can only go up after it: there is no order to put them up"))
        over = blocked(us[k], grid) if us[k][0].panel else None    # a crane lowers a panel; a site piece is
        if over:                                                    # slid into place by hand
            m, p = over
            out.append(fault_at(s, us[k], f"{label(k, us)} cannot be lowered into place: {name(p)} of "
                                          f"{label(of[p.id], us)}, already up, is over {name(m)}", [p]))
        todo.discard(k)
        up.add(k)
        order.append(k)
        for m in us[k]:
            for cell in cells(m):
                grid.setdefault(cell, []).append(m)
    return out


CELL = 48.0


def cells(m: Member):
    lo, hi = m.box.lo, m.box.hi
    for i in range(int(lo[0] // CELL), int(hi[0] // CELL) + 1):
        for j in range(int(lo[1] // CELL), int(hi[1] // CELL) + 1):
            yield (i, j)


def blocked(ms: list[Member], grid) -> tuple[Member, Member] | None:
    """A member already up that is over one of these, overlapping it in plan: in the way of lowering them."""
    for m in ms:
        seen = set()
        for cell in cells(m):
            for p in grid.get(cell, ()):
                if p.id in seen:
                    continue
                seen.add(p.id)
                if p.box.lo[2] < m.box.hi[2] - EPS:
                    continue
                if any(min(m.box.hi[k], p.box.hi[k]) - max(m.box.lo[k], p.box.lo[k]) <= EPS for k in (0, 1)):
                    continue
                if plan_overlap(m, p) > 1.0:
                    return m, p
    return None


def plan_overlap(a: Member, b: Member) -> float:
    """The area where two members overlap seen from above, in square inches."""
    pa = hull([(p[0], p[1]) for p in a.points])
    pb = hull([(p[0], p[1]) for p in b.points])
    if len(pa) < 3 or len(pb) < 3:
        return 0.0
    poly = [(u, v, 0.0) for u, v in pa]
    for (x0, y0), (x1, y1) in zip(pb, pb[1:] + pb[:1]):
        n = (y1 - y0, -(x1 - x0), 0.0)          # outward for a counter-clockwise hull
        poly = solid.clip_poly(poly, n, n[0] * x0 + n[1] * y0)
        if len(poly) < 3:
            return 0.0
    return solid.area(poly)


def label(k: str, us: dict) -> str:
    return f"panel {k}" if len(us[k]) > 1 or us[k][0].panel else f"{name(us[k][0])} (built on site)"


def fault_at(s: Site, ms: list[Member], message: str, others=()) -> Fault:
    m = min(ms, key=lambda x: x.box.lo[2])
    return s.at(m, m.box.centre, "assembly", True, message, list(others))
