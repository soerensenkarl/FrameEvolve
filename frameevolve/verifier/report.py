"""What the verifier says: one Fault per problem found, and the Report that gathers them with the metrics.

A fault names its check, whether it is hard, says what is wrong in words a framer would use, where it is (the
surface, u and v on it, and a world point), the members involved, and the rules that placed them. A missing
member has no rule to blame, and the report says so.

A frame's score is (hard faults, soft faults, cost), compared in that order: fewer hard faults first, then
fewer soft faults, then cheaper.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from frameevolve.geometry import Vec
from frameevolve.graph import Graph

# Every check, what it means. The modules that run them say how; hard or soft is set where each fault is made.
CHECKS = {
    # physical.py: can it stand up at all
    "rule error": "a rule raised an error, so part of the frame is missing",
    "too long": "longer than the longest stock length",
    "opening": "a member runs into a door or window",
    "clash": "two members occupy the same space",
    "floating": "no chain of bearing down to the ground (a horizontal piece nailed at both ends counts)",
    "span": "a joist, rafter or beam spans further than the IRC table allows for its size and spacing",
    "overhang": "a loaded member runs too far past its last support",
    "bearing": "a member bears on too little of its support",
    "thrust": "a rafter with no tie in the lower third of its rise reaching across to the opposite rafters, so it "
              "pushes its wall out",
    # analysis.py: a simple structural analysis of the loads
    "strength": "the loads on a member stress it past what the wood allows (bending, compression, buckling)",
    "crushing": "a member presses into the one under it harder than the wood across the grain allows",
    "deflection": "a joist, rafter or beam sags more than the code allows under its loads",
    # boards.py: the skins
    "backing": "sheathing, subfloor, drywall or ceiling with nothing behind it",
    "head": "the top of an opening has nothing over it",
    "sill": "the bottom of a window has nothing under it",
    "insulation": "an exterior wall framed shallower than 2x6 leaves no room for R-20 cavity insulation",
    # code.py: the IRC's prescriptive rules
    "studs": "studs too far apart or too tall for their size and load, or not in one piece from plate to plate",
    "header": "a header spans too far for its plies and depth, or has too few jack studs under an end",
    "kings": "too few full-height studs beside a header's end in an exterior wall",
    "offset": "a bearing wall stands on joists further from the support below than their depth",
    "notch": "a notch too deep, too long, or in the middle third of a joist's or rafter's span",
    "in line": "a joist or rafter lands on a top plate too far from a stud under it",
    "ridge": "a ridge board, hip or valley shallower than the cut ends of the rafters framing into it",
    "restraint": "a joist end, or deep roof framing at its bearing, with nothing to stop it rolling over",
    # prefab.py: built as panels in a shop, trucked and lifted into place
    "panel": "a prefab panel too big to truck, too heavy to lift, not flat, not one piece, or not framed round",
    "assembly": "panels or members that cannot be put up in any order: one must go in under or through another",
}


@dataclass
class Fault:
    check: str
    hard: bool
    message: str
    surface: str | None = None  # the surface the member is on
    u: float | None = None      # where on that surface, for drawing
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
               f"{m['waste_ft']:.1f} ft wasted ({m['waste_pct']:.0f}%), {m['members']} pieces"
               + (f", {m['site_pieces']} of them built on site, {m['panels']} panels to lift." if 'panels' in m else ".")]
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
