"""The frame as a graph of contacts: what bears on what, what touches side to side, what clashes.

Exact for axis-aligned members. Members at other angles are listed as unresolved until roofs need them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from frameevolve.geometry import EPS, overlaps
from frameevolve.model import Member

GROUND = "ground"


@dataclass
class Graph:
    bears: dict[str, dict[str, float]] = field(default_factory=dict)    # a: {b: area}, a rests on b
    carries: dict[str, dict[str, float]] = field(default_factory=dict)  # b: {a: area}, the inverse
    side: dict[str, dict[str, float]] = field(default_factory=dict)     # a: {b: area}, both ways
    clashes: list[tuple[str, str, float]] = field(default_factory=list)  # (a, b, overlap volume)
    unresolved: list[str] = field(default_factory=list)

    def grounded(self) -> set[str]:
        """Members with a chain of bearing contacts down to the ground."""
        seen, todo = set(), [GROUND]
        while todo:
            for a in self.carries.get(todo.pop(), {}):
                if a not in seen:
                    seen.add(a)
                    todo.append(a)
        return seen


def build_graph(members: list[Member], ground: float = 0.0) -> Graph:
    g = Graph(carries={GROUND: {}})
    aligned = []
    for m in members:
        g.bears[m.id], g.carries[m.id], g.side[m.id] = {}, {}, {}
        if not m.aligned:
            g.unresolved.append(m.id)
            continue
        aligned.append(m)
        if abs(m.box.lo[2] - ground) <= EPS:
            s = m.box.size
            g.bears[m.id][GROUND] = g.carries[GROUND][m.id] = s[0] * s[1]
    aligned.sort(key=lambda m: m.box.lo[0])
    for i, a in enumerate(aligned):
        for b in aligned[i + 1:]:
            if b.box.lo[0] > a.box.hi[0] + EPS:
                break
            ov = overlaps(a.box, b.box)
            if min(ov) < -EPS:
                continue
            pos = [k for k in range(3) if ov[k] > EPS]
            if len(pos) == 3:
                g.clashes.append((a.id, b.id, ov[0] * ov[1] * ov[2]))
            elif len(pos) == 2:          # one face against another; edge and corner contacts are ignored
                area = ov[pos[0]] * ov[pos[1]]
                if 3 - sum(pos) == 2:    # touching in z: one rests on the other
                    top, bot = (a, b) if abs(a.box.lo[2] - b.box.hi[2]) <= EPS else (b, a)
                    g.bears[top.id][bot.id] = g.carries[bot.id][top.id] = area
                else:
                    g.side[a.id][b.id] = g.side[b.id][a.id] = area
    return g
