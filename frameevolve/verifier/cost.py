"""What a frame costs: timber bought in stock lengths (first fit decreasing, with a saw kerf per cut), deeper
sections weighted by their depth, a cost per piece for cutting, handling and nailing (three times as much for a
piece cut and nailed on site as for one built into a panel in the shop), and a crane lift per panel. In linear
feet of 2x4 equivalent.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from frameevolve.model import SECTIONS, STOCK, Frame

KERF = 0.125             # saw cut
PIECE_COST = 1.5         # one piece built into a panel in the shop (cut by the saw, nailed on the table)
SITE_PIECE_COST = 4.5    # one piece cut and nailed on site: three times the shop's labour
LIFT_COST = 40.0         # one panel trucked and lifted into place by crane


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


def metrics(frame: Frame) -> dict:
    """Timber bought in stock lengths, waste, pieces built on site and panels, and the cost."""
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
    site = sum(1 for m in frame.members if not m.panel)
    panels = len({m.panel for m in frame.members if m.panel})
    cost += PIECE_COST * (len(frame.members) - site) + SITE_PIECE_COST * site + LIFT_COST * panels
    return {
        "members": len(frame.members), "site_pieces": site, "panels": panels,
        "bought_ft": round(bought / 12, 2), "used_ft": round(used / 12, 2),
        "waste_ft": round((bought - used) / 12, 2), "waste_pct": round(100 * (bought - used) / bought, 1) if bought else 0.0,
        "cost": round(cost, 2), "by_section": sections,
        "by_rule": dict(Counter(m.rule for m in frame.members)),
    }
