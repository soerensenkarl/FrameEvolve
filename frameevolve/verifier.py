"""The verifier: deterministic checks that turn a frame into a report. No LLM.

A placeholder for the codes. Each check is a simplified reading of IRC chapter 6 and the WFCM, enough to
tell a buildable wall from a broken one. Every fault says where it is and which members and rules made it.

Hard faults make a frame unbuildable. Soft faults are code or practice issues a good grammar avoids.
A frame's score is (hard faults, soft faults, cost), compared in that order: fewer hard faults first,
then fewer soft faults, then cheaper.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from frameevolve import surface
from frameevolve.geometry import EPS, Vec, cross, dot
from frameevolve.graph import GROUND, Graph, build_graph
from frameevolve.model import SECTIONS, STOCK, Floor, Frame, House, Member, Roof, Wall
from frameevolve.units import ftin, inches

# Simplified limits, in inches. Placeholders until each is checked against the tables.
MAX_CLEAR_FLAT = 24.0    # flat plate between supports: the 24" module
# On-edge header clear span by depth: roughly IRC Table R602.7(1) for two plies carrying roof and ceiling,
# 20 ft building width, 30 psf ground snow (2x4 3'-6", 2x6 5'-5", 2x8 6'-10", 2x10 8'-5", 2x12 9'-9").
HEADER_CLEAR = {3.5: 42.0, 5.5: 65.0, 7.25: 82.0, 9.25: 101.0, 11.25: 117.0}
# Floor joist clear span by depth: roughly IRC Table R502.3.1(2), 40 psf live load, 16" centres, #2 grade.
JOIST_CLEAR = {7.25: 144.0, 9.25: 180.0, 11.25: 210.0}
# Ceiling joist clear span by depth: roughly IRC Table R802.5.1(1), attic without storage, 24" centres, #2 grade.
CEILING_CLEAR = {3.5: 118.0, 5.5: 186.0, 7.25: 245.0, 9.25: 312.0}
# Rafter span, measured level, by depth: roughly IRC Table R802.4.1(1), 40 psf ground snow (Cambridge), ceiling
# not attached, 24" centres, #2 grade.
RAFTER_RUN = {5.5: 111.0, 7.25: 141.0, 9.25: 172.0, 11.25: 200.0}
MIN_EXTERIOR_DEPTH = 5.5 # 2x6: room for the R-20 cavity insulation the energy code asks of exterior walls
MAX_OVERHANG = 2.0       # a loaded member past its last support
MIN_BEARING = 0.75       # half a stud
KERF = 0.125             # saw cut
PIECE_COST = 1.5         # cost of one piece (cutting, handling, nailing) in linear feet of 2x4

CHECKS = {
    "rule error": "a rule raised an error, so part of the frame is missing",
    "too long": "longer than the longest stock length",
    "opening": "a member runs into a door or window",
    "clash": "two members occupy the same space",
    "floating": "no chain of bearing down to the ground (a horizontal piece nailed at both ends counts)",
    "span": "a loaded member spans too far between supports",
    "overhang": "a loaded member runs too far past its last support",
    "bearing": "a member bears on too little of its support",
    "backing": "sheathing, subfloor, drywall or ceiling with nothing behind it",
    "thrust": "a rafter with no tie in the lower third of its rise, so it pushes its wall out",
    "head": "the top of an opening has nothing over it",
    "sill": "the bottom of a window has nothing under it",
    "insulation": "an exterior wall framed shallower than 2x6 leaves no room for R-20 cavity insulation",
}


@dataclass
class Fault:
    check: str
    hard: bool
    message: str
    wall: str | None = None
    u: float | None = None      # where on the wall, for drawing
    v: float | None = None
    at: Vec | None = None       # where in the world
    members: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)


@dataclass
class Report:
    house: str
    faults: list[Fault]
    metrics: dict
    graph: Graph | None = None

    @property
    def hard(self) -> int:
        return sum(f.hard for f in self.faults)

    @property
    def soft(self) -> int:
        return sum(not f.hard for f in self.faults)

    @property
    def score(self) -> tuple[int, int, float]:
        return (self.hard, self.soft, self.metrics["cost"])

    def to_dict(self) -> dict:
        return {"house": self.house, "hard": self.hard, "soft": self.soft, "score": list(self.score),
                "metrics": self.metrics, "faults": [asdict(f) for f in self.faults]}

    def text(self, examples: int = 2) -> str:
        """The report in words: what a person or the proposer reads."""
        m = self.metrics
        out = [f"House {self.house}: {m['members']} members, {self.hard} hard faults, {self.soft} soft faults.",
               f"Cost {m['cost']:.1f} (linear feet of 2x4 equivalent): {m['bought_ft']:.1f} ft of lumber bought, "
               f"{m['waste_ft']:.1f} ft wasted "
               f"({m['waste_pct']:.0f}%), {m['members']} pieces."]
        if m["by_rule"]:
            out.append("Members by rule: " + ", ".join(f"{r} {n}" for r, n in m["by_rule"].items()) + ".")
        groups = defaultdict(list)
        for f in self.faults:
            groups[(f.hard, f.check)].append(f)
        for (hard, check), fs in sorted(groups.items(), key=lambda kv: (not kv[0][0], -len(kv[1]))):
            blame = Counter(r for f in fs for r in (f.rules or ["none: nothing was placed here"]))
            out.append(f"\n{'HARD' if hard else 'soft'} {check} x{len(fs)}: {CHECKS.get(check, '')}. "
                       f"Rules involved: " + ", ".join(f"{r} {n}" for r, n in blame.most_common()) + ".")
            for f in fs[:examples]:
                out.append(f"  - {f.message}")
            if len(fs) > examples:
                out.append(f"  - ... and {len(fs) - examples} more")
        if not self.faults:
            out.append("No faults.")
        return "\n".join(out)


def _name(m: Member) -> str:
    return f"{m.id} ({m.role or m.rule})"


def _axis(m: Member) -> int:
    d = [abs(m.end[k] - m.start[k]) for k in range(3)]
    return d.index(max(d))


def purchase(lengths: list[float]) -> tuple[float, int]:
    """Total stock length bought to cut these pieces, first fit decreasing. Returns (inches bought, boards)."""
    boards: list[list[float]] = []   # [stock length, length left]
    longest = max(STOCK)
    pieces = []
    for L in lengths:                # a piece longer than any board is bought as several boards
        while L > longest:
            pieces.append(longest - KERF)
            L -= longest - KERF
        pieces.append(L)
    for L in sorted(pieces, reverse=True):
        for b in boards:
            if b[1] >= L + KERF:
                b[1] -= L + KERF
                break
        else:
            s = min(x for x in STOCK if x >= L)
            boards.append([s, s - L - KERF])
    return sum(b[0] for b in boards), len(boards)


def _vertical(m: Member) -> bool:
    return abs(m.end[2] - m.start[2]) > 0.9 * m.length


def supported(g, by_id: dict[str, Member]) -> set[str]:
    """Members held up: a chain of bearing down to the ground, where a piece that is not upright, nailed
    between held-up members on opposite faces (blocking between studs, a flat head between kings, a ridge board
    between rafters), also counts."""
    held = g.grounded()
    while True:
        new = set()
        for mid, m in by_id.items():
            if mid in held or _vertical(m):
                continue
            dirs = [g.facing[(mid, n)] for n in g.side.get(mid, {}) if n in held]
            if any(sum(a[k] * b[k] for k in range(3)) < -0.5 for i, a in enumerate(dirs) for b in dirs[i + 1:]):
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


def rafter(m: Member, g: Graph, by_id: dict[str, Member], held: set[str], at_wall) -> list[Fault]:
    """A sloped member of a roof. Its span is measured level between what it rests on, and what it butts against
    at its top (a ridge board). Unless it also rests on something in the top third of its rise (a gable wall,
    a beam), it needs a tie against thrust: something level nailed to its side in the lower third."""
    a = [(m.end[k] - m.start[k]) / m.length for k in range(3)]
    run = math.hypot(a[0], a[1])
    if abs(a[2]) < 0.05:
        return []

    def where(n: str) -> float:   # along m from its start, to the middle of where n touches it, found in plan
        c = g.at[(m.id, n)]
        return min(max(sum((c[k] - m.start[k]) * a[k] for k in range(2)) / run ** 2, 0.0), m.length)

    def point(t: float) -> Vec:
        return tuple(m.start[k] + a[k] * t for k in range(3))

    out = []
    rests = sorted(where(n) for n in g.bears[m.id] if n in held)
    butts = [t for t in (where(n) for n in g.side[m.id] if n in held) if t > m.length - 3 * m.depth]
    sup = sorted(rests + butts[:1] if butts and rests and max(butts) > max(rests) else rests)
    limit = RAFTER_RUN.get(m.depth)
    for t0, t1 in zip(sup, sup[1:]):
        if limit is None or (t1 - t0) * run > limit + EPS:
            out.append(at_wall(m, point((t0 + t1) / 2), "span", True,
                               f"{_name(m)} spans {ftin((t1 - t0) * run)} level between supports, limit "
                               f"{ftin(limit) if limit else 'none for a ' + m.section + ' rafter'}"))
    lo, hi = m.box.lo[2], m.box.hi[2]
    if any(point(t)[2] >= lo + 2 * (hi - lo) / 3 for t in rests):
        return out
    level = lambda o: abs(o.end[2] - o.start[2]) < 0.05 * o.length
    across = cross(tuple(a), m.up)                       # a tie is nailed to the rafter's side face
    on_side = lambda n: abs(dot(g.facing[(m.id, n)], across)) > 0.9
    if not any(n in held and level(by_id[n]) and on_side(n) and point(where(n))[2] <= lo + (hi - lo) / 3
               for n in g.side[m.id]):
        out.append(at_wall(m, point(m.length / 4), "thrust", True,
                           f"{_name(m)} has no tie nailed to it in the lower third of its rise (a ceiling joist or "
                           f"rafter tie), so it pushes its wall out"))
    return out


def verify(house: House, frame: Frame) -> Report:
    g = build_graph(frame.members)
    by_id = {m.id: m for m in frame.members}
    walls = {w.id: w for w in house.walls}
    surfs = {x.id: x for x in house.surfaces}
    faults: list[Fault] = []

    def at_wall(m: Member, p: Vec, check: str, hard: bool, message: str, others=()) -> Fault:
        w = surfs.get(m.surface)
        u = v = None
        if w:
            u, v, _ = w.local(p)
        ms = [m, *others]
        return Fault(check, hard, message, m.surface or None, u, v, p, [x.id for x in ms],
                     sorted({x.rule for x in ms}))

    # rule errors
    for e in frame.errors:
        rule = e.split(" ", 1)[0]
        faults.append(Fault("rule error", True, e, rules=[rule]))

    # per member
    for m in frame.members:
        centre = tuple((m.box.lo[k] + m.box.hi[k]) / 2 for k in range(3))
        if m.length > max(STOCK) + EPS:
            faults.append(at_wall(m, centre, "too long", True,
                                  f"{_name(m)} is {ftin(m.length)}, longer than the {ftin(max(STOCK))} stock"))
        w = surfs.get(m.surface)
        if w:
            b = w.local_box(m)
            for o in w.openings:
                du = min(b.hi[0], o.u1) - max(b.lo[0], o.u0)
                dv = min(b.hi[1], o.v1) - max(b.lo[1], o.v0)
                if du > EPS and dv > EPS:
                    u = (max(b.lo[0], o.u0) + min(b.hi[0], o.u1)) / 2
                    v = (max(b.lo[1], o.v0) + min(b.hi[1], o.v1)) / 2
                    faults.append(at_wall(m, w.world(u, v, 0), "opening", True,
                                          f"{_name(m)} on {w.id} runs {ftin(du)} into {o.kind} {o.id}"))

    # clashes
    for a, b, vol in g.clashes:
        ma, mb = by_id[a], by_id[b]
        p = tuple((max(ma.box.lo[k], mb.box.lo[k]) + min(ma.box.hi[k], mb.box.hi[k])) / 2 for k in range(3))
        faults.append(at_wall(ma, p, "clash", True, f"{_name(ma)} and {_name(mb)} overlap by {vol:.1f} cubic inches", [mb]))

    # support
    grounded = supported(g, by_id)
    for m in frame.members:
        if m.id not in grounded:
            centre = tuple((m.box.lo[k] + m.box.hi[k]) / 2 for k in range(3))
            faults.append(at_wall(m, centre, "floating", True, f"{_name(m)} has no chain of bearing to the ground"))

    # spans, overhangs and bearing of loaded horizontal members
    for m in frame.members:
        if not m.aligned or m.id not in grounded or GROUND in g.bears[m.id]:
            continue
        k = _axis(m)
        if k == 2:
            continue   # vertical members: no span check yet
        w = surfs.get(m.surface)
        floor = isinstance(w, Floor)   # floor framing carries the floor's own load; ceiling framing its own
        roof = (isinstance(w, Wall) and w.role == "exterior" and w.above is None
                and abs(m.box.hi[2] - (w.base + w.height)) <= EPS)
        if not (g.carries[m.id] or roof or floor):
            continue
        a0, a1 = m.box.lo[k], m.box.hi[k]
        sup = sorted((max(a0, by_id[s].box.lo[k]), min(a1, by_id[s].box.hi[k]), s) for s in g.bears[m.id])
        if floor:   # a joist end butting into the side of a header or rim hangs from it (a hanger)
            sup += [(x, x, n) for n in g.side.get(m.id, {}) for x in (a0, a1) if n in grounded
                    and abs(by_id[n].box.lo[k] - x) <= EPS or abs(by_id[n].box.hi[k] - x) <= EPS]
            sup.sort()
        if not sup:
            continue
        flat = abs(m.box.size[2] - m.width) <= EPS
        table = (CEILING_CLEAR if w.role == "ceiling" else JOIST_CLEAR) if floor else HEADER_CLEAR
        limit = MAX_CLEAR_FLAT if flat else table.get(m.depth, MAX_CLEAR_FLAT)
        kind = f"flat {m.section}" if flat else f"{m.section} on edge"

        def point(x: float) -> Vec:
            p = [(m.box.lo[j] + m.box.hi[j]) / 2 for j in range(3)]
            p[k] = x
            return tuple(p)

        for s0, s1, s in sup:
            if s0 < s1 and s1 - s0 < MIN_BEARING - EPS:
                faults.append(at_wall(m, point((s0 + s1) / 2), "bearing", True,
                                      f"{_name(m)} bears only {inches(s1 - s0)} on {_name(by_id[s])}, minimum {inches(MIN_BEARING)}",
                                      [by_id[s]]))
        reach = sup[0][1]
        for s0, s1, s in sup[1:]:
            if s0 - reach > limit + EPS:
                faults.append(at_wall(m, point((reach + s0) / 2), "span", True,
                                      f"{_name(m)} spans {ftin(s0 - reach)} clear between supports, limit {ftin(limit)} for {kind}"))
            reach = max(reach, s1)
        for over in (sup[0][0] - a0, a1 - max(s1 for _, s1, _ in sup)):
            if over > MAX_OVERHANG + EPS:
                x = a0 + over / 2 if over == sup[0][0] - a0 else a1 - over / 2
                faults.append(at_wall(m, point(x), "overhang", True,
                                      f"{_name(m)} runs {ftin(over)} past its last support, limit {inches(MAX_OVERHANG)}"))

    # rafters: span, measured level between supports, and a tie against thrust
    for m in frame.members:
        if isinstance(surfs.get(m.surface), Roof) and m.id in grounded and not _vertical(m):
            faults += rafter(m, g, by_id, grounded, at_wall)

    # faces of every surface: sheathing and drywall on walls, subfloor and ceiling on floors, roof sheathing
    boards = {("roof", "outer"): "roof sheathing", ("ceiling", "outer"): "ceiling", ("floor", "outer"): "subfloor",
              ("floor", "inner"): "ceiling", ("exterior", "outer"): "sheathing"}
    for w in house.surfaces:
        for face in w.faces:
            board = boards.get((w.role, face), "drywall")
            for gp in surface.gaps(w, frame.members, face=face, walls=walls):
                u, v = (gp.u0 + gp.u1) / 2, (gp.v0 + gp.v1) / 2
                where = f"u {ftin(gp.u0)} to {ftin(gp.u1)}, v {ftin(gp.v0)} to {ftin(gp.v1)}"
                msg = (f"{w.id} {face} face: {board} edge at {where} has nothing behind it" if gp.kind == "edge" else
                       f"{w.id} {face} face: {board} spans {ftin(gp.u1 - gp.u0)} by {ftin(gp.v1 - gp.v0)} with "
                       f"nothing behind it at {where}; it needs support within {ftin(surface.MAX_CLEAR)} one way")
                faults.append(Fault("backing", True, msg, w.id, u, v, w.world(u, v, 0), [], []))

    # walls: opening heads and sills, exterior wall depth
    for w in house.walls:
        boxes = [(m, w.local_box(m)) for m in frame.members if m.surface == w.id]
        for o in w.openings:
            edges = [("head", o.v1, lambda b, o=o: abs(b.lo[1] - o.v1) <= EPS)]
            if o.kind == "window":
                edges.append(("sill", o.v0, lambda b, o=o: abs(b.hi[1] - o.v0) <= EPS))
            for check, v, touches in edges:
                cover = [(b.lo[0], b.hi[0]) for _, b in boxes if touches(b)]
                missing = surface.subtract([(o.u0, o.u1)], cover)
                if missing:
                    u = (missing[0][0] + missing[0][1]) / 2
                    what = "top" if check == "head" else "bottom"
                    faults.append(Fault(check, True, f"{w.id}: {what} of {o.kind} {o.id} has nothing along "
                                        f"u {ftin(missing[0][0])} to {ftin(missing[0][1])}", w.id, u, v, w.world(u, v, 0),
                                        [], []))
        d = surface.depth(w, frame.members)
        if w.role == "exterior" and d is not None and d < MIN_EXTERIOR_DEPTH - EPS:
            u, v = w.length / 2, w.height / 2
            faults.append(Fault("insulation", True, f"{w.id}: framed {inches(d)} deep; an exterior wall needs "
                                f"{inches(MIN_EXTERIOR_DEPTH)} (2x6) for R-20 cavity insulation", w.id, u, v,
                                w.world(u, v, 0), [m.id for m, _ in boxes[:1]], sorted({m.rule for m, _ in boxes})))

    # cost
    by_section = defaultdict(list)
    for m in frame.members:
        by_section[m.section].append(m.length)
    bought = used = cost = 0.0
    sections = {}
    for sec, lengths in sorted(by_section.items()):
        b, n = purchase(lengths)
        u = sum(lengths)
        bought, used = bought + b, used + u
        cost += b / 12 * SECTIONS[sec][1] / 3.5
        sections[sec] = {"pieces": len(lengths), "boards": n, "bought_ft": round(b / 12, 2)}
    cost += PIECE_COST * len(frame.members)
    metrics = {
        "members": len(frame.members), "bought_ft": round(bought / 12, 2), "used_ft": round(used / 12, 2),
        "waste_ft": round((bought - used) / 12, 2), "waste_pct": round(100 * (bought - used) / bought, 1) if bought else 0.0,
        "cost": round(cost, 2), "by_section": sections,
        "by_rule": dict(Counter(m.rule for m in frame.members)),
    }
    return Report(house.id, faults, metrics, g)
