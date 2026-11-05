"""Procedural houses: two or three storeys of platform framing on a rectangular plan.

Every storey has four exterior walls and a partition down the middle (the spine), with cross partitions from
the front or back wall to the spine. A floor sits on every storey but the top one. The house gives only
surfaces and openings: which walls bear, and how, is the grammar's business. Inches.
"""
from __future__ import annotations

import random

from frameevolve.model import Floor, House, Opening, Wall

HEAD = 82.5     # rough-opening head height of every door and window: 6'-10 1/2"
LEVEL = 120.0   # floor to floor: a wall under a floor reaches up to the floor's top


def ring(house: House, storey: int, width: float, depth: float, base: float, height: float) -> list[Wall]:
    """Four exterior walls around the footprint, counter-clockwise so they frame inward."""
    pts = [(0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)]
    walls = [Wall(f"{storey}w{i}", pts[i], pts[(i + 1) % 4], height, base) for i in range(4)]
    house.walls += walls
    return walls


def partition(house: House, id: str, start, end, base: float, height: float) -> Wall:
    """An interior wall drawn from one wall's surface to another's; the grammar decides where framing stops."""
    w = Wall(id, start, end, height, base, role="interior")
    house.walls.append(w)
    return w


def add_opening(wall: Wall, kind: str, u0: float, width: float, height: float) -> Opening:
    v0 = 0.0 if kind == "door" else HEAD - height
    o = Opening(f"{wall.id}o{len(wall.openings)}", kind, float(u0), float(u0 + width), v0, HEAD)
    wall.openings.append(o)
    wall.openings.sort(key=lambda o: o.u0)
    return o


def place(rng: random.Random, wall: Wall, kind: str, width: float, height: float, keep: list = ()) -> bool:
    """An opening somewhere on the wall, 12" clear of its ends, its other openings and the u-ranges in keep."""
    taken = [(o.u0, o.u1) for o in wall.openings] + list(keep)
    hi = int(wall.length - 12 - width)
    for _ in range(50):
        if hi < 12:
            return False
        u0 = rng.randrange(12, hi + 1, 2)
        if all(u0 + width + 12 <= a or u0 >= b + 12 for a, b in taken):
            add_opening(wall, kind, u0, width, height)
            return True
    return False


def generate(seed: int) -> House:
    """A random house, 24 to 40 ft by 22 to 32 ft, two or three storeys of 10 ft floor to floor; the top
    storey's walls are 8 or 9 ft (plate heights for 92 5/8" and 104 5/8" precut studs)."""
    rng = random.Random(seed)
    width, depth = float(rng.randrange(288, 481, 12)), float(rng.randrange(264, 385, 12))
    storeys, top = rng.choice([2, 3]), rng.choice([97.125, 109.125])
    spine_y = 2 * round(depth / 4)
    house = House(f"h{seed:03d}", [])
    for k in range(1, storeys + 1):
        base, height = (k - 1) * LEVEL, LEVEL if k < storeys else top
        front, right, back, left = ring(house, k, width, depth, base, height)
        spine_end = {right.id: [(spine_y - 24, spine_y + 24)], left.id: [(depth - spine_y - 24, depth - spine_y + 24)]}
        for w in (front, right, back, left):
            for _ in range(rng.randint(1, max(1, int(w.length // 96)))):
                place(rng, w, "window", rng.choice([24, 30, 36, 48, 60, 72]), rng.choice([24, 36, 48, 60]),
                      spine_end.get(w.id, []))
        if k == 1:
            place(rng, front, "door", rng.choice([34, 38]), HEAD)
        spine = partition(house, f"{k}s", (0.0, spine_y), (width, spine_y), base, height)
        if rng.random() < 0.6:
            place(rng, spine, "door", 34, HEAD)
        cross(rng, house, k, front, back, spine, base, height)
    for k in range(2, storeys + 1):
        house.floors.append(Floor(f"f{k}", (0.0, 0.0), width, depth, (k - 1) * LEVEL))
    house.link()
    return house


def cross(rng, house, k, front, back, spine, base, height) -> None:
    """Up to two partitions from the front or back wall to the spine, clear of openings and of each other."""
    width, spine_y = front.length, spine.start[1]
    xs: list[float] = []
    for n in range(rng.randint(0, 2)):
        for _ in range(50):
            x = float(rng.randrange(72, int(width) - 71, 2))
            to_front = rng.random() < 0.5
            host_u = [(front, x), (spine, x)] if to_front else [(spine, x), (back, width - x)]
            if any(abs(x - y) < 72 for y in xs) or any(o.u0 - 24 < u < o.u1 + 24 for w, u in host_u for o in w.openings):
                continue
            a, b = ((x, 0.0), (x, spine_y)) if to_front else ((x, spine_y), (x, back.start[1]))
            p = partition(house, f"{k}p{n}", a, b, base, height)
            if rng.random() < 0.5:
                place(rng, p, "door", 34, HEAD)
            xs.append(x)
            break


def toy() -> House:
    """A small two-storey house for showing what a rule does: 14 x 10 ft, a window and a door in the front wall
    and a spine below, a floor, and a window upstairs."""
    house = House("toy", [])
    front, *_ = ring(house, 1, 168.0, 120.0, 0.0, LEVEL)
    add_opening(front, "window", 24, 36, 48)
    add_opening(front, "door", 96, 38, HEAD)
    partition(house, "1s", (0.0, 60.0), (168.0, 60.0), 0.0, LEVEL)
    upstairs, *_ = ring(house, 2, 168.0, 120.0, LEVEL, 97.125)
    add_opening(upstairs, "window", 60, 48, 48)
    house.floors.append(Floor("f2", (0.0, 0.0), 168.0, 120.0, LEVEL))
    house.link()
    return house
