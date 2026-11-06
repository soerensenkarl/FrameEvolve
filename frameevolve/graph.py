"""The frame as a graph of contacts: what bears on what, what touches side to side, what clashes.

Exact at any angle. Plain members (axis-aligned, uncut boxes) meet by comparing boxes; anything cut, notched or
at an angle meets by clipping solids (solid.py). A face contact bears when it is closer to level than to plumb:
the member above rests on the one below. Otherwise it is a side contact, and `facing` keeps its direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from frameevolve import solid
from frameevolve.geometry import EPS, Vec, add, mul, overlaps, unit
from frameevolve.model import Member

GROUND = "ground"
LEVEL = 0.5   # a contact whose normal is at least this vertical bears


@dataclass
class Graph:
    bears: dict[str, dict[str, float]] = field(default_factory=dict)    # a: {b: area}, a rests on b
    carries: dict[str, dict[str, float]] = field(default_factory=dict)  # b: {a: area}, the inverse
    side: dict[str, dict[str, float]] = field(default_factory=dict)     # a: {b: area}, both ways
    facing: dict[tuple[str, str], Vec] = field(default_factory=dict)    # (a, b): the side contact's normal out of a
    at: dict[tuple[str, str], Vec] = field(default_factory=dict)        # (a, b): the middle of where they touch
    clashes: list[tuple[str, str, float]] = field(default_factory=list)  # (a, b, overlap volume)

    def grounded(self) -> set[str]:
        """Members with a chain of bearing contacts down to the ground."""
        seen, todo = set(), [GROUND]
        while todo:
            for a in self.carries.get(todo.pop(), {}):
                if a not in seen:
                    seen.add(a)
                    todo.append(a)
        return seen

    def _bear(self, top: str, bot: str, area: float, c: Vec) -> None:
        self.bears[top][bot] = self.carries[bot][top] = self.bears[top].get(bot, 0.0) + area
        self.at[(top, bot)] = self.at[(bot, top)] = c

    def _side(self, a: str, b: str, area: float, n: Vec, c: Vec) -> None:
        self.side[a][b] = self.side[b][a] = self.side[a].get(b, 0.0) + area
        self.facing[(a, b)], self.facing[(b, a)] = n, mul(n, -1)
        self.at[(a, b)] = self.at[(b, a)] = c


def meet(a: Member, b: Member, g: Graph) -> None:
    """Record how two members meet in the graph."""
    if a.plain and b.plain:
        ov = overlaps(a.box, b.box)
        pos = [k for k in range(3) if ov[k] > EPS]
        c = tuple((max(a.box.lo[k], b.box.lo[k]) + min(a.box.hi[k], b.box.hi[k])) / 2 for k in range(3))
        if len(pos) == 3:
            g.clashes.append((a.id, b.id, ov[0] * ov[1] * ov[2]))
        elif len(pos) == 2:          # one face against another; edge and corner contacts are ignored
            area = ov[pos[0]] * ov[pos[1]]
            k = 3 - sum(pos)
            if k == 2:               # touching in z: one rests on the other
                top, bot = (a, b) if abs(a.box.lo[2] - b.box.hi[2]) <= EPS else (b, a)
                g._bear(top.id, bot.id, area, c)
            else:
                n = [0.0, 0.0, 0.0]
                n[k] = 1.0 if abs(a.box.hi[k] - b.box.lo[k]) <= EPS else -1.0
                g._side(a.id, b.id, area, tuple(n), c)
        return
    vol, contacts = solid.meet(a.pieces, b.pieces)
    if vol > 1e-6:
        g.clashes.append((a.id, b.id, vol))
        return
    def total(cs):   # area, area-weighted normal and centre
        s = sum(x for x, _, _ in cs)
        n = c = (0.0, 0.0, 0.0)
        for x, d, p in cs:
            n, c = add(n, mul(d, x)), add(c, mul(p, x / s))
        return s, (unit(n) if any(abs(k) > 1e-9 for k in n) else cs[0][1]), c

    for top, bot, cs in ((a, b, [x for x in contacts if x[1][2] <= -LEVEL]), (b, a, [x for x in contacts if x[1][2] >= LEVEL])):
        if cs:
            s, _, c = total(cs)
            g._bear(top.id, bot.id, s, c)
    sides = [x for x in contacts if abs(x[1][2]) < LEVEL]
    if sides:
        g._side(a.id, b.id, *total(sides))


def build_graph(members: list[Member], ground: float = 0.0) -> Graph:
    g = Graph(carries={GROUND: {}})
    for m in members:
        g.bears[m.id], g.carries[m.id], g.side[m.id] = {}, {}, {}
        if abs(m.box.lo[2] - ground) <= EPS and m.plain:
            s = m.box.size
            g.bears[m.id][GROUND] = g.carries[GROUND][m.id] = s[0] * s[1]
    order = sorted(members, key=lambda m: m.box.lo[0])
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            if b.box.lo[0] > a.box.hi[0] + EPS:
                break
            if min(overlaps(a.box, b.box)) < -EPS:
                continue
            meet(a, b, g)
    return g
