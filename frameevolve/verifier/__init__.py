"""The verifier: deterministic checks that turn a frame into a report. No LLM.

It asks what a building inspector, an engineer and a panel shop would ask of a timber frame, in that order:

  physical.py   Can it stand?      Rule errors, stock length, openings, clashes, support down to the ground,
                                   spans and bearing by the IRC tables, rafter thrust and its ties.
  analysis.py   Will it hold?      A simple structural analysis: loads followed down through the frame,
                                   bending, compression and crushing against what the wood allows.
  boards.py     Can it be skinned? Backing for every board, heads and sills at openings, room for insulation.
  code.py       Would it pass?     The IRC's prescriptive rules: studs, headers, notches, in-line framing,
                                   bearing walls over the floor below, ridges, lateral restraint.
  prefab.py     Can it be built?   Prefab panels small and light enough to truck and lift, pieces a standard
                                   automated saw can cut, and an order of erection that works.
  cost.py       What does it cost? Timber bought in stock lengths, pieces, site work and crane lifts.

Every check is a function check(site) -> faults (site.py: what a check reads). Hard faults make a frame
unbuildable or unsafe; soft faults are details a good grammar also gets right. A frame's score is (hard, soft,
cost), compared in that order. The limits sit at the top of each module, with the code section they come from.
"""
from __future__ import annotations

from frameevolve.model import Frame, House
from frameevolve.verifier import analysis, boards, code, cost, physical, prefab
from frameevolve.verifier.report import CHECKS, Fault, Report
from frameevolve.verifier.site import Site

# Every check, in the order the report reads.
ORDER = [
    physical.rule_errors, physical.pieces, physical.clashes, physical.floating, physical.spans, physical.rafters,
    analysis.loads,
    boards.backing, boards.openings, boards.insulation,
    code.studs, code.header_checks, code.offsets, code.inline, code.notches, code.restraint,
    prefab.panels, prefab.cutting, prefab.erection,
]
MODULES = [physical, analysis, boards, code, prefab, cost]   # where the checks and their limits live, for the workbench

__all__ = ["CHECKS", "Fault", "Report", "Site", "verify"]


def verify(house: House, frame: Frame) -> Report:
    """Every check on a frame, and its cost."""
    site = Site(house, frame)
    faults = [f for check in ORDER for f in check(site)]
    return Report(house.id, faults, cost.metrics(frame), site.g)
