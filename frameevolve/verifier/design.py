"""Design objectives: what makes a sound, buildable frame a good one to build. Each one counts as soft faults, so the
search pursues it once the frame is sound (hard faults first), and before cost.

Fewest panels: every panel is a crane lift, a set of connections on site and a joint in the skin. A surface
needs at least as many panels as its size takes to truck (prefab.PANEL_LONG by PANEL_SHORT, turned whichever way
needs fewer) and its weight to lift (PANEL_WEIGHT); each panel beyond that is one soft fault. The limits that
keep a panel truckable are prefab.py's hard faults, so fewer panels never means oversized ones.
"""
from __future__ import annotations

import math

from frameevolve.verifier.prefab import DENSITY, PANEL_LONG, PANEL_SHORT, PANEL_WEIGHT, SKIN, volume
from frameevolve.verifier.report import Fault
from frameevolve.verifier.site import Site
from frameevolve.units import ftin


def fewest(s: Site, sid: str) -> int:
    """The fewest panels that could carry a surface's panel framing: by its extent on the truck, and its weight."""
    x = s.surfs[sid]
    ms = [m for m in s.on.get(sid, []) if m.panel]
    boxes = [x.local_box(m) for m in ms]
    du = max(b.hi[0] for b in boxes) - min(b.lo[0] for b in boxes)
    dv = max(b.hi[1] for b in boxes) - min(b.lo[1] for b in boxes)
    by_size = min(math.ceil(du / PANEL_LONG - 1e-6) * math.ceil(dv / PANEL_SHORT - 1e-6),
                  math.ceil(du / PANEL_SHORT - 1e-6) * math.ceil(dv / PANEL_LONG - 1e-6))
    weight = sum(volume(m) for m in ms) * DENSITY + du * dv * SKIN
    return max(1, by_size, math.ceil(weight / PANEL_WEIGHT))


def panel_count(s: Site) -> list[Fault]:
    """Each surface built in more panels than its size and weight need: one soft fault per extra panel."""
    out = []
    for sid, ms in s.on.items():
        names = sorted({m.panel for m in ms if m.panel})
        if not names or sid not in s.surfs:
            continue
        need = fewest(s, sid)
        x = s.surfs[sid]
        for extra in range(len(names) - need):
            out.append(s.flag("panels", False, f"{sid} is built as {len(names)} panels ({', '.join(names[:6])}"
                              f"{', ...' if len(names) > 6 else ''}); {need} would truck and lift (at most "
                              f"{ftin(PANEL_LONG)} by {ftin(PANEL_SHORT)} each): fewer panels, fewer lifts and joints",
                              sid, x.size[0] / 2, x.size[1] / 2, [], sorted({m.rule for m in ms if m.panel})))
    return out
