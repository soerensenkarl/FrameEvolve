"""A frame in words, exact: what the proposer reads to understand a house it built, as an execution trace (GEPA).

  overview   every surface: kind, size, storey, what it stands on and carries, its panels, its members by rule,
             its faults by check
  members    one surface in full: each member on one line, along the surface, with where it is (inches in the
             surface's u, v, w), its section, rule, role and panel, its contacts in the graph (what it rests on,
             what rests on it, what touches its side) and the faults it is in
  trace      what one rule did: each firing, what it matched, what it placed, cut or removed, and where
  raw        the frame's own data for one surface, untranslated: each member as saved (world coordinates, cut planes
             and notches as plane normals and offsets, panel)

The ground is a node of the graph like a member, named ground. Positions are the member's bounding box in its
surface's coordinates (see the builder): on a wall u along it
from its start, v up from its base, w into the framing; on a floor u, v in plan, w down from the top.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from frameevolve.loads import Takedown
from frameevolve.model import Floor, Frame, House, Member, Roof, Wall
from frameevolve.verifier import Report

LINES = 400   # the most lines one answer runs to: past it, filter by rule


def kind(x) -> str:
    if isinstance(x, Wall):
        return ("gable " if x.outline else "") + ("exterior wall" if x.role == "exterior" else "partition")
    if isinstance(x, Roof):
        return f"roof plane, {x.pitch:g}:12"
    return "ceiling" if x.role == "ceiling" else "floor"


def faults_of(report: Report) -> dict[str, list[str]]:
    """Member id -> the checks of the faults it is in (hard in capitals)."""
    out: dict[str, list[str]] = defaultdict(list)
    for f in report.faults:
        for mid in f.members:
            out[mid].append(f.check.upper() if f.hard else f.check)
    return out


def overview(house: House, frame: Frame, report: Report) -> str:
    """Every surface of the house as built: what it is, its panels and members, and its faults."""
    s = report.site
    lines = [f"House {house.id}: {len(frame.members)} members, {report.hard} hard faults, {report.soft} soft. "
             f"{report.metrics.get('panels', 0)} panels, {report.metrics.get('site_pieces', 0)} pieces built on site."]
    td = Takedown(house, frame.guides)
    lb = lambda L: f"{L.sum:,.0f} lb (dead {L.dead:,.0f}, live {L.live:,.0f}, snow {L.snow:,.0f})"
    if td.lost:
        lines.append("Loads the layout leaves with nothing under them: "
                     + "; ".join(f"{sid}: {lb(L)}, {why}" for sid, L, why in td.lost[:6]))
    lines += [f"Wind: {x}; each of these walls is asked for all it could hold." for x in td.short]
    surface_faults: dict[str, Counter] = defaultdict(Counter)
    for f in report.faults:
        if f.surface:
            surface_faults[f.surface][f.check.upper() if f.hard else f.check] += 1
    for x in house.surfaces:
        ms = s.on.get(x.id, [])
        U, V = x.size
        rests = Counter(s.by_id[n].surface if n in s.by_id else "ground" for m in ms for n in s.g.bears[m.id]
                        if n not in s.by_id or s.by_id[n].surface != x.id)
        carried = Counter(s.by_id[n].surface for m in ms for n in s.g.carries[m.id] if n in s.by_id and s.by_id[n].surface != x.id)
        panels = Counter(m.panel or "site" for m in ms)
        lines.append(f"\n{x.id}: {kind(x)}, {U:.1f} x {V:.1f} in., {len(ms)} members"
                     + (f", {len(x.openings)} openings ({', '.join(f'{o.id} {o.kind} u {o.u0:g}-{o.u1:g} v {o.v0:g}-{o.v1:g}' for o in x.openings)})" if x.openings else ""))
        if isinstance(x, Wall):
            pts = td.points(x.id)
            lines.append(f"  wind racks it with {td.shear.get(x.id, 0):,.0f} lb; load on its top, by the takedown "
                         f"on the surfaces: {lb(td.on(x.id))}"
                         + (f"; points: {', '.join(f'{p.load.sum:,.0f} lb at u {p.u:g} ({p.source})' for p in pts)}" if pts else ""))
        else:
            A = td.area[x.id]
            lines.append(f"  area load {A.dead:g} dead, {A.live:g} live, {A.snow:g} snow psf"
                         + (f", spans along {td.span[x.id]}" if x.id in td.span else ""))
        if rests:
            lines.append(f"  rests on {', '.join(f'{k} ({n})' for k, n in rests.most_common())}")
        if carried:
            lines.append(f"  carries {', '.join(f'{k} ({n})' for k, n in carried.most_common())}")
        if ms:
            lines.append(f"  by rule: {', '.join(f'{k} {n}' for k, n in Counter(m.rule for m in ms).most_common())}")
            lines.append(f"  panels: {', '.join(f'{k} ({n})' for k, n in sorted(panels.items()))}")
        if surface_faults[x.id]:
            lines.append(f"  faults: {', '.join(f'{k} {n}' for k, n in surface_faults[x.id].most_common())}")
    return "\n".join(lines)


def line(x, m: Member, report: Report, faults: dict) -> str:
    """One member on its surface: where, what, its contacts and its faults."""
    s = report.site
    b = x.local_box(m)
    ids = lambda ns: ",".join(sorted(n if n in s.by_id else "ground" for n in ns)[:6]) + ("..." if len(ns) > 6 else "")
    shape = (" cut" if m.cuts else "") + (" notched" if m.notches else "") + ("" if m.aligned else " sloped")
    out = (f"{m.id} {m.role or '-'} {m.section} rule {m.rule} panel {m.panel or 'site'}{shape}: "
           f"u {b.lo[0]:.2f}-{b.hi[0]:.2f} v {b.lo[1]:.2f}-{b.hi[1]:.2f} w {b.lo[2]:.2f}-{b.hi[2]:.2f}, "
           f"length {m.length:.2f}")
    if s.g.bears[m.id]:
        out += f"; on {ids(s.g.bears[m.id])}"
    if s.g.carries[m.id]:
        out += f"; carries {ids(s.g.carries[m.id])}"
    if s.g.side[m.id]:
        out += f"; beside {ids(s.g.side[m.id])}"
    if m.id not in s.held:
        out += "; NOT HELD UP"
    if faults.get(m.id):
        out += f"; faults: {', '.join(sorted(set(faults[m.id])))}"
    return out


def members(house: House, frame: Frame, report: Report, sid: str, rule: str = "") -> str:
    """Every member on one surface (of one rule, if given), along the surface: the full dump."""
    x = next((y for y in house.surfaces if y.id == sid), None)
    if x is None:
        return f"No surface {sid}. Surfaces: {', '.join(y.id for y in house.surfaces)}."
    ms = [m for m in report.site.on.get(sid, []) if not rule or m.rule == rule]
    ms.sort(key=lambda m: (round(x.local_box(m).lo[0], 1), x.local_box(m).lo[1]))
    faults = faults_of(report)
    head = (f"{sid}: {kind(x)}, {x.size[0]:.1f} x {x.size[1]:.1f} in., {len(ms)} members"
            + (f" of rule {rule}" if rule else "") + " (u along it, v up it, w into the framing; capital faults are hard)")
    rows = [line(x, m, report, faults) for m in ms]
    loose = [f.message for f in report.faults if f.surface == sid and not f.members][:10]
    if len(rows) > LINES:
        rows = rows[:LINES] + [f"... and {len(rows) - LINES} more: ask for one rule at a time"]
    return "\n".join([head, *rows] + (["Faults on it with no member (something missing):", *[f"  - {m}" for m in loose]]
                                       if loose else []))


def trace(house: House, frame: Frame, rule: str) -> str:
    """What one rule did on this house: each firing, what it matched, what it placed, cut or removed."""
    steps = [(i, st) for i, st in enumerate(frame.steps) if st["rule"] == rule]
    if not steps:
        rules = sorted({st["rule"] for st in frame.steps})
        return f"Rule {rule} did nothing on {house.id}." + ("" if rule in rules else f" Rules that did: {', '.join(rules)}.")
    by_id = {m.id: m for m in frame.members + frame.removed}
    surfs = {x.id: x for x in house.surfaces}
    out = [f"Rule {rule} on {house.id}: {len(steps)} firings."]
    for i, st in steps[:LINES // 2]:
        x = surfs.get(st["surface"])
        def where(mid):
            m = by_id.get(mid)
            if m is None or x is None:
                return mid
            b = x.local_box(m)
            return f"{mid} {m.section} u {b.lo[0]:.1f}-{b.hi[0]:.1f} v {b.lo[1]:.1f}-{b.hi[1]:.1f}"
        parts = []
        if st["placed"]:
            parts.append("placed " + "; ".join(where(k) for k in st["placed"][:8]) + ("; ..." if len(st["placed"]) > 8 else ""))
        if st.get("shaped"):
            parts.append("cut or notched " + ", ".join(st["shaped"][:8]))
        if st["removed"]:
            parts.append("removed " + ", ".join(st["removed"][:8]))
        if st.get("assigned"):
            parts.append(f"put {len(st['assigned'])} into panels")
        if st.get("guides"):
            parts.append(f"laid out {len(st['guides'])} guides")
        out.append(f"step {i + 1}, pass {st['pass']}, on {st['surface'] or 'the house'}, matched {st['match']}: "
                   + ("; ".join(parts) or "nothing"))
    if len(steps) > LINES // 2:
        out.append(f"... and {len(steps) - LINES // 2} more firings")
    return "\n".join(out)


def raw(frame: Frame, sid: str) -> str:
    """The members on one surface exactly as the frame stores them, as JSON lines."""
    import json
    ms = [m for m in frame.members if m.surface == sid]
    if not ms:
        return f"No members on {sid}."
    return "\n".join(json.dumps(m.to_dict()) for m in ms[:LINES]) + (f"\n... and {len(ms) - LINES} more" if len(ms) > LINES else "")
