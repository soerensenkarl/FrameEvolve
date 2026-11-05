"""The verifier: deterministic checks that turn a frame into a report. No LLM.

A placeholder for the codes. Each check is a simplified reading of IRC chapter 6 and the WFCM, enough to
tell a buildable wall from a broken one. Every fault says where it is and which members and rules made it.

Hard faults make a frame unbuildable. Soft faults are code or practice issues a good grammar avoids.
A frame's score is (hard faults, soft faults, cost), compared in that order: fewer hard faults first,
then fewer soft faults, then cheaper.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from frameevolve import surface
from frameevolve.geometry import EPS, Vec
from frameevolve.graph import GROUND, Graph, build_graph
from frameevolve.model import SECTIONS, STOCK, Frame, House, Member
from frameevolve.units import ftin, inches

# Simplified limits, in inches. Placeholders until each is checked against the tables.
MAX_CLEAR_FLAT = 22.5    # flat plate between supports: 24" centres less a stud
# On-edge header clear span by depth: roughly IRC Table R602.7(1) for two plies carrying roof and ceiling,
# 20 ft building width, 30 psf ground snow (2x4 3'-6", 2x6 5'-5", 2x8 6'-10", 2x10 8'-5", 2x12 9'-9").
HEADER_CLEAR = {3.5: 42.0, 5.5: 65.0, 7.25: 82.0, 9.25: 101.0, 11.25: 117.0}
MAX_OVERHANG = 2.0       # a loaded member past its last support
MIN_BEARING = 0.75       # half a stud
KERF = 0.125             # saw cut
PIECE_COST = 1.5         # cost of one piece (cutting, handling, nailing) in linear feet of 2x4

CHECKS = {
    "rule error": "a rule raised an error, so part of the frame is missing",
    "too long": "longer than the longest stock length",
    "opening": "a member runs into a door or window",
    "clash": "two members occupy the same space",
    "floating": "no chain of bearing down to the ground",
    "span": "a loaded member spans too far between supports",
    "overhang": "a loaded member runs too far past its last support",
    "bearing": "a member bears on too little of its support",
    "backing": "sheathing or drywall with nothing behind it",
    "head": "the top of an opening has nothing over it",
    "sill": "the bottom of a window has nothing under it",
    "single top plate": "IRC R602.3.2 asks for a double top plate",
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


def verify(house: House, frame: Frame) -> Report:
    g = build_graph(frame.members)
    by_id = {m.id: m for m in frame.members}
    walls = {w.id: w for w in house.walls}
    faults: list[Fault] = []

    def at_wall(m: Member, p: Vec, check: str, hard: bool, message: str, others=()) -> Fault:
        w = walls.get(m.surface)
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
        w = walls.get(m.surface)
        if w:
            b = w.local_box(m.box)
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
    grounded = g.grounded()
    for m in frame.members:
        if m.id not in grounded and m.aligned:
            centre = tuple((m.box.lo[k] + m.box.hi[k]) / 2 for k in range(3))
            faults.append(at_wall(m, centre, "floating", True, f"{_name(m)} has no chain of bearing to the ground"))

    # spans, overhangs and bearing of loaded horizontal members
    for m in frame.members:
        if not m.aligned or m.id not in grounded or GROUND in g.bears[m.id]:
            continue
        k = _axis(m)
        if k == 2:
            continue   # vertical members: no span check yet
        w = walls.get(m.surface)
        roof = w is not None and abs(m.box.hi[2] - (w.base + w.height)) <= EPS
        if not (g.carries[m.id] or roof):
            continue
        a0, a1 = m.box.lo[k], m.box.hi[k]
        sup = sorted((max(a0, by_id[s].box.lo[k]), min(a1, by_id[s].box.hi[k]), s) for s in g.bears[m.id])
        if not sup:
            continue
        flat = abs(m.box.size[2] - m.width) <= EPS
        limit = MAX_CLEAR_FLAT if flat else HEADER_CLEAR.get(m.depth, MAX_CLEAR_FLAT)
        kind = f"flat {m.section}" if flat else f"{m.section} on edge"

        def point(x: float) -> Vec:
            p = [(m.box.lo[j] + m.box.hi[j]) / 2 for j in range(3)]
            p[k] = x
            return tuple(p)

        for s0, s1, s in sup:
            if s1 - s0 < MIN_BEARING - EPS:
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

    # walls: sheathing backing, opening heads and sills, top plates
    for w in house.walls:
        own = [m for m in frame.members if m.surface == w.id]
        for face in ("outer", "inner"):
            board = "sheathing" if face == "outer" and w.role == "exterior" else "drywall"
            for gp in surface.gaps(w, frame.members, face=face, walls=walls):
                u, v = (gp.u0 + gp.u1) / 2, (gp.v0 + gp.v1) / 2
                where = f"u {ftin(gp.u0)} to {ftin(gp.u1)}, v {ftin(gp.v0)} to {ftin(gp.v1)}"
                msg = (f"{w.id} {face} face: {board} edge at {where} has nothing behind it" if gp.kind == "edge" else
                       f"{w.id} {face} face: {board} spans {ftin(gp.u1 - gp.u0)} between backing at {where}, "
                       f"limit {ftin(surface.MAX_CLEAR)}")
                faults.append(Fault("backing", True, msg, w.id, u, v, w.world(u, v, 0), [], []))
        boxes = [(m, w.local_box(m.box)) for m in own]
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
        top = [(m, b) for m, b in boxes if abs(b.hi[1] - w.height) <= EPS]
        if top:
            under = [(b.lo[0], b.hi[0]) for m, b in boxes
                     if any(abs(b.hi[1] - tb.lo[1]) <= EPS and b.hi[0] - b.lo[0] > b.hi[1] - b.lo[1] for _, tb in top)]
            single = surface.subtract([(0.0, w.length)], under)
            if sum(b - a for a, b in single) > w.length / 2:
                u = w.length / 2
                faults.append(Fault("single top plate", False, f"{w.id}: the top plate is single along most of the wall",
                                    w.id, u, w.height, w.world(u, w.height, 0), [m.id for m, _ in top],
                                    sorted({m.rule for m, _ in top})))

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
