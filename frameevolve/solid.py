"""Member solids at any angle: a box, trimmed by cut planes, less notches.

A plane (n, d) is the half-space n.x <= d. A convex piece is a list of faces (n, d, points): a convex polygon on
the plane n.x = d with outward normal n. A member's solid is its box clipped by every cut, then split into convex
pieces around each notch. Overlap volumes and contact areas between two solids are exact, by clipping.
"""
from __future__ import annotations

import math

from frameevolve.geometry import EPS, Vec, add, cross, dot, mul, sub, unit

TOL = 1e-7
Plane = tuple[Vec, float]
Face = tuple[Vec, float, list[Vec]]


def box_frame(start: Vec, end: Vec, up: Vec, width: float, depth: float):
    """The box's centre, its axes (along, up, across: right-handed) and half-sizes along them."""
    a = unit(sub(end, start))
    u = unit(up)
    return mul(add(start, end), 0.5), (a, u, cross(a, u)), (math.dist(start, end) / 2, depth / 2, width / 2)


def box_planes(start: Vec, end: Vec, up: Vec, width: float, depth: float) -> list[Plane]:
    c, axes, half = box_frame(start, end, up, width, depth)
    return [(mul(e, s), s * dot(e, c) + h) for e, h in zip(axes, half) for s in (1, -1)]


def box_faces(start: Vec, end: Vec, up: Vec, width: float, depth: float) -> list[Face]:
    c, e, h = box_frame(start, end, up, width, depth)
    faces = []
    for i in range(3):
        j, k = (i + 1) % 3, (i + 2) % 3
        for s in (1, -1):
            n = mul(e[i], s)
            mid = add(c, mul(n, h[i]))
            corners = [(1, 1), (-1, 1), (-1, -1), (1, -1)][::s]
            pts = [add(mid, add(mul(e[j], a * h[j]), mul(e[k], b * h[k]))) for a, b in corners]
            faces.append((n, dot(n, mid), pts))
    return faces


def area(pts: list[Vec]) -> float:
    if len(pts) < 3:
        return 0.0
    s = (0.0, 0.0, 0.0)
    for p, q in zip(pts[1:], pts[2:]):
        s = add(s, cross(sub(p, pts[0]), sub(q, pts[0])))
    return math.sqrt(dot(s, s)) / 2


def clip_poly(pts: list[Vec], n: Vec, d: float) -> list[Vec]:
    """The part of a convex polygon where n.x <= d."""
    out = []
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        dp, dq = dot(n, p) - d, dot(n, q) - d
        if dp <= TOL:
            out.append(p)
        if (dp < -TOL and dq > TOL) or (dp > TOL and dq < -TOL):
            out.append(add(p, mul(sub(q, p), dp / (dp - dq))))
    return out


def _ring(pts: list[Vec], n: Vec) -> list[Vec]:
    """Points on a plane, without repeats, in order around their centre."""
    uniq: list[Vec] = []
    for p in pts:
        if all(math.dist(p, q) > 1e-6 for q in uniq):
            uniq.append(p)
    if len(uniq) < 3:
        return uniq
    c = mul(sum_(uniq), 1 / len(uniq))
    far = max(uniq, key=lambda p: math.dist(p, c))
    x = unit(sub(far, c))
    y = cross(n, x)
    return sorted(uniq, key=lambda p: math.atan2(dot(sub(p, c), y), dot(sub(p, c), x)))


def sum_(pts) -> Vec:
    s = (0.0, 0.0, 0.0)
    for p in pts:
        s = add(s, p)
    return s


def clip(faces: list[Face], n: Vec, d: float) -> list[Face]:
    """A convex piece cut by a plane: what lies where n.x <= d, closed with a new face on the plane."""
    out, cap = [], []
    for fn, fd, pts in faces:
        q = clip_poly(pts, n, d)
        if len(q) >= 3 and area(q) > TOL:
            out.append((fn, fd, q))
        cap += [p for p in q if abs(dot(n, p) - d) <= TOL]
    if not out:
        return []
    if not any(dot(fn, n) > 1 - 1e-9 and abs(fd - d) <= 1e-6 for fn, fd, _ in out):
        ring = _ring(cap, n)
        if len(ring) >= 3 and area(ring) > TOL:
            out.append((n, d, ring))
    return out


def points(piece: list[Face]) -> list[Vec]:
    return [p for _, _, pts in piece for p in pts]


def volume(piece: list[Face]) -> float:
    if not piece:
        return 0.0
    ps = points(piece)
    c = mul(sum_(ps), 1 / len(ps))
    return sum((d - dot(n, c)) * area(pts) for n, d, pts in piece) / 3


def bounds(piece: list[Face]) -> tuple[Vec, Vec]:
    xs, ys, zs = zip(*points(piece))
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def solid(start: Vec, end: Vec, up: Vec, width: float, depth: float, cuts=(), notches=()) -> list[list[Face]]:
    """The convex pieces of a member: its box, clipped by each cut (keep n.x <= d), less each notch (a convex
    region, the planes it lies inside)."""
    piece = box_faces(start, end, up, width, depth)
    for n, d in cuts:
        piece = clip(piece, tuple(n), d)
    pieces = [piece] if piece else []
    for region in notches:
        region = [(tuple(n), d) for n, d in region]
        out = []
        for p in pieces:
            inside = p
            for n, d in region:
                inside = clip(inside, n, d) if inside else inside
            if volume(inside) <= TOL:
                out.append(p)
                continue
            for i, (n, d) in enumerate(region):   # p less the region: outside plane i, inside the ones before
                q = clip(p, mul(n, -1), -d)
                for n2, d2 in region[:i]:
                    q = clip(q, n2, d2) if q else q
                if volume(q) > TOL:
                    out.append(q)
        pieces = out
    return pieces


def section(pieces: list[list[Face]], n: Vec, d: float) -> list[list[Vec]]:
    """Where the plane n.x = d cuts through the solid: one polygon per piece it crosses."""
    out = []
    for p in pieces:
        lo = min(dot(n, q) for q in points(p))
        hi = max(dot(n, q) for q in points(p))
        if lo < d - TOL and hi > d + TOL:
            out += [pts for fn, fd, pts in clip(p, n, d) if dot(fn, n) > 1 - 1e-9 and abs(fd - d) <= 1e-6]
    return out


def _touch(fa: Face, fb: Face) -> list[Vec]:
    """Where two faces lie against each other (opposite normals, the same plane): the polygon, or nothing."""
    na, da, pa = fa
    nb, db, pb = fb
    if dot(na, nb) > -1 + 1e-6 or abs(da + db) > EPS:
        return []
    c = mul(sum_(pb), 1 / len(pb))
    q = pa
    for i, p in enumerate(pb):
        o = cross(sub(pb[(i + 1) % len(pb)], p), nb)
        if dot(o, sub(c, p)) > 0:
            o = mul(o, -1)
        q = clip_poly(q, o, dot(o, p))
        if len(q) < 3:
            return []
    return q


def meet(a: list[list[Face]], b: list[list[Face]]) -> tuple[float, list[tuple[float, Vec, Vec]]]:
    """How two solids meet: the volume they share, and their face contacts as (area, normal out of a, centre)."""
    vol, contacts = 0.0, []
    for p in a:
        plo, phi = bounds(p)
        for q in b:
            qlo, qhi = bounds(q)
            if any(min(phi[k], qhi[k]) - max(plo[k], qlo[k]) < -EPS for k in range(3)):
                continue
            shared = p
            for n, d, _ in q:
                shared = clip(shared, n, d - EPS) if shared else shared
            v = volume(shared)
            if v > 1e-6:
                vol += v
                continue
            for fa in p:
                for fb in q:
                    poly = _touch(fa, fb)
                    if area(poly) > TOL:
                        contacts.append((area(poly), fa[0], mul(sum_(poly), 1 / len(poly))))
    return vol, contacts


def triangles(pieces: list[list[Face]]) -> tuple[list[Vec], list[int]]:
    """A triangle mesh of the solid, for drawing: vertices and index triples."""
    verts, idx = [], []
    for p in pieces:
        for _, _, pts in p:
            k = len(verts)
            verts += pts
            idx += [i for j in range(1, len(pts) - 1) for i in (k, k + j, k + j + 1)]
    return verts, idx
