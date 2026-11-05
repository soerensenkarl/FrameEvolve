"""Procedural houses. MVP: one storey, rectangular plan, exterior walls with doors and windows."""
from __future__ import annotations

import random

from frameevolve.model import House, Opening, Wall

HEAD = 82.5  # rough-opening head height of every door and window: 6'-10 1/2"


def rectangle(id: str, width: float, depth: float, height: float) -> House:
    """Four exterior walls around a width x depth footprint, counter-clockwise so they frame inward."""
    pts = [(0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)]
    return House(id, [Wall(f"w{i}", pts[i], pts[(i + 1) % 4], height) for i in range(4)])


def add_partition(house: House, start: tuple[float, float], end: tuple[float, float]) -> Wall:
    """An interior wall from one exterior wall's outer face to another's; the grammar decides where framing stops."""
    w = Wall(f"p{sum(x.role == 'interior' for x in house.walls)}", start, end, house.walls[0].height, role="interior")
    house.walls.append(w)
    house.link()
    return w


def add_opening(wall: Wall, kind: str, u0: float, width: float, height: float) -> Opening:
    v0 = 0.0 if kind == "door" else HEAD - height
    o = Opening(f"{wall.id}o{len(wall.openings)}", kind, float(u0), float(u0 + width), v0, HEAD)
    wall.openings.append(o)
    return o


def generate(seed: int) -> House:
    """A random rectangular house, 20 to 46 ft by 16 to 33 ft, with 8 or 9 ft walls (plate heights for
    92 5/8" and 104 5/8" precut studs). Rough openings keep 12" from wall ends and from each other."""
    rng = random.Random(seed)
    house = rectangle(f"h{seed:03d}", float(rng.randrange(240, 553, 12)), float(rng.randrange(192, 397, 12)),
                      rng.choice([97.125, 109.125]))
    widths = [24, 30, 36, 48, 60, 72] + ([96] if house.walls[0].height >= 109 else [])
    for i, wall in enumerate(house.walls):
        wanted = []
        if i == 0 or (i == 2 and rng.random() < 0.5):
            wanted.append(("door", rng.choice([34, 38]), HEAD))
        for _ in range(rng.randint(0, int(wall.length // 96))):
            wanted.append(("window", rng.choice(widths), rng.choice([24, 36, 48, 60])))
        taken: list[tuple[float, float]] = []
        for kind, width, height in wanted:
            hi = int(wall.length - 12 - width)
            for _ in range(50):
                if hi < 12:
                    break
                u0 = rng.randrange(12, hi + 1, 2)
                if all(u0 + width + 12 <= a or u0 >= b + 12 for a, b in taken):
                    taken.append((u0, u0 + width))
                    add_opening(wall, kind, u0, width, height)
                    break
        wall.openings.sort(key=lambda o: o.u0)
        for k, o in enumerate(wall.openings):
            o.id = f"{wall.id}o{k}"
    add_partitions(house, rng)
    return house


def add_partitions(house: House, rng: random.Random) -> None:
    """One or two partitions across the short way, from the front wall to the back wall, clear of openings
    and of each other by at least 6 ft, half of them with a door."""
    front, back = house.walls[0], house.walls[2]
    W, D = front.length, house.walls[1].length

    def clear(x: float) -> bool:
        for wall, u in ((front, x), (back, W - x)):
            if any(o.u0 - 24 < u < o.u1 + 24 for o in wall.openings):
                return False
        return all(abs(x - p.start[0]) >= 72 for p in house.walls if p.role == "interior")

    for _ in range(rng.choice([1, 1, 2])):
        for _ in range(50):
            x = float(rng.randrange(72, int(W) - 71, 2))
            if clear(x):
                p = add_partition(house, (x, 0.0), (x, D))
                if rng.random() < 0.5 and D >= 120:
                    add_opening(p, "door", rng.randrange(24, int(D - 24 - 34) + 1, 2), 34, HEAD)
                    p.openings[0].id = f"{p.id}o0"
                break


def toy() -> House:
    """A 14 x 10 ft house for showing what a rule does: wall w0 has a window and a door, and a partition runs
    from the right wall to the left wall."""
    house = rectangle("toy", 168.0, 120.0, 97.125)
    w0 = house.walls[0]
    add_opening(w0, "window", 24, 36, 48)
    add_opening(w0, "door", 96, 38, HEAD)
    add_partition(house, (168.0, 60.0), (0.0, 60.0))
    return house
