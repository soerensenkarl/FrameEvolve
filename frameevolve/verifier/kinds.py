"""What each member is, read from its geometry alone: a stud, a king, a header, a joist, a rafter... The grammar's
own labels (roles) are never trusted, so a grammar cannot pass a check or dress up a report by renaming a member.

Walls     bottom plate, top plate (level, laid flat, at the wall's base, or with no upright on it), rake plate (sloped, along a
          gable's top); header (level, right over an opening), sill (level, right under a window); king (an
          upright beside an opening that runs on up past its head), jack (an upright that stops under a header), cripple (a short
          upright over a header or under a sill), stud (any other upright); blocking (any other level piece)
Floors    rim (along the outline's edge), joist (level, on edge, the way most run), blocking (on edge, across
          the joists), plate (laid flat); in a ceiling, ceiling joist
Roofs     rafter (up the slope), ridge (level, at the plane's top), hip or valley (sloped, across the slope),
          blocking (level, elsewhere)
"""
from __future__ import annotations

from collections import Counter

from frameevolve.geometry import EPS
from frameevolve.model import Floor, Member, Roof, Wall
from frameevolve.verifier.site import axis, level, on_edge, vertical

NEAR = 2.0      # how close counts as over or under, inches
BESIDE = 6.5    # a king stands this close to its opening: up to three jacks between


def kinds(house, members: list[Member]) -> dict[str, str]:
    """Member id -> what it is."""
    surfs = {x.id: x for x in house.surfaces}
    on: dict[str, list[Member]] = {}
    for m in members:
        on.setdefault(m.surface, []).append(m)
    out = {}
    for sid, ms in on.items():
        x = surfs.get(sid)
        name = wall if isinstance(x, Wall) else roof if isinstance(x, Roof) else floor if isinstance(x, Floor) else None
        out.update(name(x, ms) if name else {m.id: "member" for m in ms})
    return out


def wall(w: Wall, ms: list[Member]) -> dict[str, str]:
    box = {m.id: w.local_box(m) for m in ms}
    ups = [m for m in ms if vertical(m)]
    out = {}
    heads, sills = [], []       # (u0, u1, v) of each header's underside and each sill's top
    for m in ms:
        if vertical(m):
            continue
        b = box[m.id]
        if not level(m):
            out[m.id] = "rake plate"
            continue
        over = [o for o in w.openings if b.lo[0] < o.u1 - EPS and b.hi[0] > o.u0 + EPS]
        if any(abs(b.lo[1] - o.v1) <= 12 and b.lo[1] >= o.v1 - EPS for o in over) and on_edge(m):
            out[m.id] = "header"
            heads.append((b.lo[0], b.hi[0], b.lo[1]))
        elif any(o.kind == "window" and abs(b.hi[1] - o.v0) <= NEAR for o in over):
            out[m.id] = "sill"
            sills.append((b.lo[0], b.hi[0], b.hi[1]))
        elif not on_edge(m) and b.lo[1] <= NEAR:
            out[m.id] = "bottom plate"
        elif not on_edge(m) and not any(box[n.id].lo[1] >= b.hi[1] - EPS and box[n.id].lo[0] < b.hi[0] - EPS
                                        and box[n.id].hi[0] > b.lo[0] + EPS for n in ups):
            out[m.id] = "top plate"       # laid flat with no upright of this wall on it
        else:
            out[m.id] = "blocking"
    for m in ups:
        b = box[m.id]
        u0, u1, v0, v1 = b.lo[0], b.hi[0], b.lo[1], b.hi[1]
        beside = any(abs(u1 - o.u0) <= BESIDE or abs(u0 - o.u1) <= BESIDE for o in w.openings
                     if v0 <= o.v0 + NEAR and v1 >= o.v1 + 2 * NEAR)    # past the opening's head: not a jack
        under_head = any(a - EPS <= u0 and u1 <= c + EPS and abs(v1 - v) <= NEAR for a, c, v in heads)
        on_head = any(a - EPS <= u0 and u1 <= c + EPS and v0 >= v - EPS for a, c, v in heads)
        under_sill = any(a - EPS <= u0 and u1 <= c + EPS and v1 <= v + EPS for a, c, v in sills)
        if on_head or under_sill:
            out[m.id] = "cripple"
        elif under_head:
            out[m.id] = "jack"
        elif beside:
            out[m.id] = "king"
        else:
            out[m.id] = "stud"
    return out


def floor(f: Floor, ms: list[Member]) -> dict[str, str]:
    box = {m.id: f.local_box(m) for m in ms}
    us = [u for u, _ in f.outline_uv]
    vs = [v for _, v in f.outline_uv]
    edge = lambda b: (min(abs(b.lo[0] - u) for u in us) <= NEAR and b.hi[0] - b.lo[0] <= NEAR + 1.5) or \
                     (min(abs(b.lo[1] - v) for v in vs) <= NEAR and b.hi[1] - b.lo[1] <= NEAR + 1.5) or \
                     (min(abs(b.hi[0] - u) for u in us) <= NEAR and b.hi[0] - b.lo[0] <= NEAR + 1.5) or \
                     (min(abs(b.hi[1] - v) for v in vs) <= NEAR and b.hi[1] - b.lo[1] <= NEAR + 1.5)
    along = lambda m: 0 if box[m.id].hi[0] - box[m.id].lo[0] >= box[m.id].hi[1] - box[m.id].lo[1] else 1
    deep = [m for m in ms if level(m) and on_edge(m)]
    # the joists run the way most of the on-edge length does, the rim aside
    length = Counter()
    for m in deep:
        if not edge(box[m.id]):
            length[along(m)] += m.length
    way = length.most_common(1)[0][0] if length else 0
    joist = "ceiling joist" if f.role == "ceiling" else "joist"
    out = {}
    for m in ms:
        if m not in deep:
            out[m.id] = "plate" if level(m) else "post" if vertical(m) else "member"
        elif f.role != "ceiling" and edge(box[m.id]):
            out[m.id] = "rim"
        else:
            out[m.id] = joist if along(m) == way else "blocking"
    return out


def roof(r: Roof, ms: list[Member]) -> dict[str, str]:
    top = max(v for _, v in r.outline_uv)
    out = {}
    for m in ms:
        a = r.local_dir(axis(m))
        b = r.local_box(m)
        if abs(a[1]) > 0.95:
            out[m.id] = "rafter"
        elif abs(a[0]) > 0.95:
            out[m.id] = "ridge" if b.hi[1] >= top - 12 else "blocking"
        else:
            out[m.id] = "hip or valley"
    return out
