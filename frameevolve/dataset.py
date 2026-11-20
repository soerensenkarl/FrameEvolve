"""Choose the houses of a dataset so that, together, they cover what houses ask of a framer.

No house has everything, the set must: bearing walls inside, a bearing line opened into posts and a beam, a
long span, a wide opening, an open porch, a stair, a room of double height, a top storey open to the roof, a
loft, knee walls, walls off the square, a wing against a higher wall, and every roof form. situations() names
what a detailed house has; choose() picks, among houses that pass check.py, the ones that even the count out,
rare situations first. `python -m frameevolve.dataset [sample] [size]` details a sample of the downloaded
houses, prints how often each situation comes up among the valid ones and in the chosen set, and writes the
chosen models to data/cambridge/chosen.json.
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from frameevolve import cambridge, envelope
from frameevolve.cambridge_view import sample
from frameevolve.check import problems
from frameevolve.detail import ROOM, detail
from frameevolve.model import House


def situations(house: House) -> set[str]:
    """The design situations a detailed house has: those the detailer gave it (house.has) and those of its
    shape."""
    out = set(house.has)
    outer = [w for w in house.walls if w.role == "exterior"]
    bases = sorted({w.base for w in house.walls})
    out.add(f"{len(bases)} storey{'s' if len(bases) > 1 else ''}")
    seams = {x.kind for r in house.roofs for x in r.seams}
    sloped = [r for r in house.roofs if r.pitch >= 1]
    if any(r.pitch < 1 for r in house.roofs):
        out.add("flat roof")
    if any(r.pitch >= 24 for r in house.roofs):
        out.add("steep roof sides (mansard, gambrel)")
    if "hip" in seams:
        out.add("hip")
    if "valley" in seams:
        out.add("valley")
    if "ridge" in seams and any(w.outline for w in outer):
        out.add("gable")
    if sloped and "ridge" not in seams and "hip" not in seams:
        out.add("shed roof")
    if any(w.id[1] == "s" for w in house.walls):
        out.add("bearing wall inside")
    if any(w.base == bases[-1] and not w.outline and 24 <= w.height < ROOM for w in outer):
        out.add("knee walls")
    if any(min(abs(w.dir[0]), abs(w.dir[1])) > 0.05 for w in outer):
        out.add("walls off the square (a bay)")
    if any(w.abutted for w in outer):
        out.add("a lower roof against a higher wall")
    if any(o.kind == "stair" for f in house.floors for o in f.openings):
        out.add("stair")
    if any(o.width >= 72 for w in outer for o in w.openings):
        out.add("wide opening")
    return out


def choose(have: dict[str, set[str]], size: int) -> list[str]:
    """`size` houses of `have` (model -> situations) that even out how often each situation comes up: each
    pick is the house whose situations are rarest in the set so far."""
    chosen, count = [], Counter()
    left = dict(have)
    while left and len(chosen) < size:
        best = max(sorted(left), key=lambda m: sum(1 / (1 + count[s]) for s in left[m]))
        chosen.append(best)
        count.update(left.pop(best))
    return chosen


def main(many: int = 300, size: int = 100) -> None:
    houses = json.loads((cambridge.OUT / "houses.json").read_text())
    have, failed = {}, Counter()
    for h in sample(houses, many):
        try:
            house = detail(envelope.envelope(cambridge.OUT / "models" / f"{h['model']}.obj"), h, 0, h["model"])
            wrong = problems(house)
        except Exception as e:
            wrong = [f"crash: {type(e).__name__}"]
        if wrong:
            failed.update({w.split(":")[0] for w in wrong})
        elif len({w.base for w in house.walls}) <= 3:
            have[h["model"]] = situations(house)
    chosen = choose(have, size)
    everywhere, picked = Counter(s for v in have.values() for s in v), Counter(s for m in chosen for s in have[m])
    print(f"{many} houses detailed, {len(have)} valid and of at most 3 storeys (failing: {dict(failed.most_common())}); {len(chosen)} chosen")
    print(f"{'situation':40} {'valid':>6} {'chosen':>7}")
    for s, n in sorted(everywhere.items(), key=lambda x: -x[1]):
        print(f"{s:40} {n:6d} {picked[s]:7d}")
    (cambridge.OUT / "chosen.json").write_text(json.dumps(chosen, indent=1))


if __name__ == "__main__":
    main(*map(int, sys.argv[1:3]))
