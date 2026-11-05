"""Exact geometry for framing members, in inches with z up.

A member is an oriented box: a centreline from start to end, a section of width x depth, and an up
vector giving the direction its depth faces. Contacts are computed on axis-aligned boxes, which are
exact for every member of an orthogonal plan.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1 / 32  # inches: faces closer than this touch

Vec = tuple[float, float, float]


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a: Vec) -> Vec:
    n = math.sqrt(dot(a, a))
    if n == 0:
        raise ValueError("zero-length vector")
    return mul(a, 1 / n)


def axis_aligned(v: Vec, tol: float = 1e-9) -> bool:
    return sum(1 for c in v if abs(c) > tol) == 1


@dataclass(frozen=True)
class Box:
    """An axis-aligned box from corner lo to corner hi."""
    lo: Vec
    hi: Vec

    @property
    def size(self) -> Vec:
        return sub(self.hi, self.lo)

    @staticmethod
    def around(points) -> "Box":
        xs, ys, zs = zip(*points)
        return Box((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def corners(start: Vec, end: Vec, up: Vec, width: float, depth: float) -> list[Vec]:
    """The eight corners of an oriented box around the centreline start to end."""
    a = unit(sub(end, start))
    d = unit(up)
    if abs(dot(a, d)) > 1e-6:
        raise ValueError("up must be perpendicular to the member axis")
    w = cross(a, d)
    return [add(p, add(mul(w, sw * width), mul(d, sd * depth)))
            for p in (start, end) for sw in (-0.5, 0.5) for sd in (-0.5, 0.5)]


def overlaps(a: Box, b: Box) -> Vec:
    """Overlap of two boxes along each axis: positive overlaps, about zero touches, negative is a gap."""
    return tuple(min(a.hi[k], b.hi[k]) - max(a.lo[k], b.lo[k]) for k in range(3))
