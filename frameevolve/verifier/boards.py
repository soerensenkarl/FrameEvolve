"""The skins: every board needs wood behind it, every opening a head and a window a sill, and an exterior wall
room for its insulation.

Backing is checked on every boarded face: sheathing and drywall on walls, subfloor and the ceiling below on
floors, the ceiling under a roof, roof sheathing. A face's boards stop where another wall's framing meets it, or
where any framing passes through it, so those edges need backing too (surface.py works out the gaps).
"""
from __future__ import annotations

from frameevolve import surface
from frameevolve.geometry import EPS
from frameevolve.units import ftin, inches
from frameevolve.verifier.report import Fault
from frameevolve.verifier.site import Site

MIN_EXTERIOR_DEPTH = 5.5   # 2x6: room for the R-20 cavity insulation the energy code asks of exterior walls
BOARDS = {("roof", "outer"): "roof sheathing", ("ceiling", "outer"): "ceiling", ("floor", "outer"): "subfloor",
          ("floor", "inner"): "ceiling", ("exterior", "outer"): "sheathing"}   # anything else: drywall


def backing(s: Site) -> list[Fault]:
    """Boards with nothing behind them: an edge that runs too far unsupported, or a field too wide both ways."""
    walls = {w.id: w for w in s.house.walls}
    out = []
    for w in s.house.surfaces:
        for face in w.faces:
            board = BOARDS.get((w.role, face), "drywall")
            for gp in surface.gaps(w, s.frame.members, face=face, walls=walls):
                where = f"u {ftin(gp.u0)} to {ftin(gp.u1)}, v {ftin(gp.v0)} to {ftin(gp.v1)}"
                msg = (f"{w.id} {face} face: {board} edge at {where} has nothing behind it" if gp.kind == "edge" else
                       f"{w.id} {face} face: {board} spans {ftin(gp.u1 - gp.u0)} by {ftin(gp.v1 - gp.v0)} with "
                       f"nothing behind it at {where}; it needs support within {ftin(surface.MAX_CLEAR)} one way")
                out.append(s.flag("backing", True, msg, w.id, (gp.u0 + gp.u1) / 2, (gp.v0 + gp.v1) / 2))
    return out


def openings(s: Site) -> list[Fault]:
    """Every opening needs something along its top (a header or head), and a window something along its bottom
    (a sill)."""
    out = []
    for w in s.house.walls:
        boxes = [(m, w.local_box(m)) for m in s.on.get(w.id, [])]
        for o in w.openings:
            edges = [("head", o.v1, lambda b, o=o: abs(b.lo[1] - o.v1) <= EPS)]
            if o.kind == "window":
                edges.append(("sill", o.v0, lambda b, o=o: abs(b.hi[1] - o.v0) <= EPS))
            for check, v, touches in edges:
                missing = surface.subtract([(o.u0, o.u1)], [(b.lo[0], b.hi[0]) for _, b in boxes if touches(b)])
                if missing:
                    what = "top" if check == "head" else "bottom"
                    out.append(s.flag(check, True, f"{w.id}: {what} of {o.kind} {o.id} has nothing along u "
                                      f"{ftin(missing[0][0])} to {ftin(missing[0][1])}", w.id,
                                      (missing[0][0] + missing[0][1]) / 2, v))
    return out


def insulation(s: Site) -> list[Fault]:
    """An exterior wall framed shallower than 2x6 has no room for R-20 cavity insulation."""
    out = []
    for w in s.house.walls:
        d = surface.depth(w, s.frame.members)
        if w.role == "exterior" and d is not None and d < MIN_EXTERIOR_DEPTH - EPS:
            ms = s.on.get(w.id, [])
            out.append(s.flag("insulation", True, f"{w.id}: framed {inches(d)} deep; an exterior wall needs "
                              f"{inches(MIN_EXTERIOR_DEPTH)} (2x6) for R-20 cavity insulation", w.id, w.length / 2,
                              w.height / 2, [m.id for m in ms[:1]], sorted({m.rule for m in ms})))
    return out
