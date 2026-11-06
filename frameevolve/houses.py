"""Procedural houses: complete houses of varying complexity, built from rectangular blocks.

A house is a main block (two or three storeys) with up to two wings: a box, an L, a T, a colonial ell (a
lower wing to one side) or a U. Each storey's exterior walls trace the outline of the blocks that reach it,
split where one block meets the next; where two blocks meet inside, a junction wall carries the floors. A block
too deep for one joist span gets a spine partition down its middle; the main block gets cross partitions; a
stair opening goes through every floor. Doors and windows go in last, clear of every junction. A box house gets
a gable roof: two roof planes, gable end walls up to them, and a ceiling on the top storey's walls. (Roofs over
L, T, ell and U houses, where roofs meet in valleys, come next.)

The house gives only surfaces and openings: which walls bear, and how, is the grammar's business. Inches.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from frameevolve.model import Floor, House, Opening, Roof, Wall

HEAD = 82.5      # rough-opening head height of every door and window: 6'-10 1/2"
LEVEL = 120.0    # floor to floor: a wall under a floor reaches up to the floor's top
SPAN = 192.0     # a block deeper than 16 ft gets a spine
KINDS = {"box": 3, "L": 3, "T": 2, "ell": 2, "U": 1}   # how often each kind of house comes up
PITCHES = (6, 7, 8, 9, 10, 12)   # roof pitch, inches of rise per 12 of run
HEEL = 9.0       # the roof plane's height over the top of the eave walls, at their outside face
EAVE = 12.0      # eave overhang, level
LONGEST = 236.0  # a rafter must come out of 20 ft stock


@dataclass
class Block:
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    storeys: int

    def holds(self, x: float, y: float) -> bool:
        return self.x0 < x < self.x1 and self.y0 < y < self.y1


def blocks_for(rng: random.Random, kind: str) -> list[Block]:
    """The main block and its wings, by kind of house."""
    W, D = float(rng.randrange(288, 481, 24)), float(rng.randrange(312, 385, 24))
    n = rng.choice([2, 3])
    main = [Block("main", 0.0, 0.0, W, D, n)]
    ww, wd = float(rng.randrange(144, 241, 24)), float(rng.randrange(144, 193, 24))
    wn = rng.randint(1, n)
    if kind == "L":
        return main + [Block("wing", W - ww, D, W, D + wd, wn)]
    if kind == "T":
        x0 = 24 * round((W - ww) / 48)
        return main + [Block("wing", x0, D, x0 + ww, D + wd, wn)]
    if kind == "ell":
        return main + [Block("ell", W, 0.0, W + wd, min(ww, D), rng.randint(1, n - 1))]
    if kind == "U":
        return main + [Block("left", 0.0, D, ww, D + wd, wn), Block("right", W - ww, D, W, D + wd, rng.randint(1, n))]
    return main


def grid(blocks: list[Block]):
    """The cells between every block edge, each with the block it belongs to."""
    xs = sorted({b.x0 for b in blocks} | {b.x1 for b in blocks})
    ys = sorted({b.y0 for b in blocks} | {b.y1 for b in blocks})

    def owner(i: int, j: int) -> Block | None:
        if not (0 <= i < len(xs) - 1 and 0 <= j < len(ys) - 1):
            return None
        cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
        return next((b for b in blocks if b.holds(cx, cy)), None)
    return xs, ys, owner


def edges(blocks: list[Block]):
    """Boundary edges (counter-clockwise, interior on the left) and shared edges between two blocks."""
    xs, ys, owner = grid(blocks)
    outer, shared = [], []
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            o = owner(i, j)
            if o is None:
                continue
            sides = [((i, j - 1), (xs[i], ys[j]), (xs[i + 1], ys[j])), ((i + 1, j), (xs[i + 1], ys[j]), (xs[i + 1], ys[j + 1])),
                     ((i, j + 1), (xs[i + 1], ys[j + 1]), (xs[i], ys[j + 1])), ((i - 1, j), (xs[i], ys[j + 1]), (xs[i], ys[j]))]
            for (ni, nj), a, b in sides:
                n = owner(ni, nj)
                if n is None:
                    outer.append((a, b, o))
                elif n is not o and (ni, nj) > (i, j):
                    shared.append((min(a, b), max(a, b), o, n))
    return outer, shared


def chain(outer):
    """Boundary edges joined into loops, collinear runs on the same block merged into one wall."""
    starts = {a: (a, b, o) for a, b, o in outer}
    loops, seen = [], set()
    for first in sorted(starts):
        if first in seen:
            continue
        loop, p = [], first
        while p not in seen:
            seen.add(p)
            a, b, o = starts[p]
            if loop and loop[-1][2] is o and _collinear(loop[-1][0], loop[-1][1], b):
                loop[-1] = (loop[-1][0], b, o)
            else:
                loop.append((a, b, o))
            p = b
        if len(loop) > 1 and loop[-1][2] is loop[0][2] and _collinear(loop[-1][0], loop[-1][1], loop[0][1]):
            loop[0] = (loop[-1][0], loop[0][1], loop[0][2])
            loop.pop()
        loops.append(loop)
    return loops


def _collinear(a, b, c) -> bool:
    return abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) < 1e-6


def outline(blocks: list[Block]) -> list[tuple[float, float]]:
    """The plan shape of the blocks: the corners of their boundary, counter-clockwise."""
    loop = chain(edges(blocks)[0])[0]
    pts = [a for a, _, _ in loop]
    return [p for k, p in enumerate(pts) if not _collinear(pts[k - 1], p, pts[(k + 1) % len(pts)])]


def add_opening(wall, kind: str, u0: float, width: float, height: float) -> Opening:
    v0 = 0.0 if kind == "door" else HEAD - height
    o = Opening(f"{wall.id}o{len(wall.openings)}", kind, float(u0), float(u0 + width), v0, HEAD)
    wall.openings.append(o)
    wall.openings.sort(key=lambda o: o.u0)
    return o


def place(rng: random.Random, wall: Wall, kind: str, width: float, height: float) -> bool:
    """An opening somewhere on the wall, 12" clear of its ends and other openings, 24" clear of junctions."""
    taken = [(o.u0, o.u1) for o in wall.openings] + [(t.u - 24, t.u + 24) for t in wall.tees]
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
    """A random complete house: a box, L, T, ell or U of two or three storeys, 10 ft floor to floor, the top
    storey's walls 8 or 9 ft (plate heights for 92 5/8" and 104 5/8" precut studs)."""
    rng = random.Random(seed)
    kind = rng.choices(list(KINDS), weights=list(KINDS.values()))[0]
    blocks = blocks_for(rng, kind)
    top = rng.choice([97.125, 109.125])
    house = House(f"h{seed:03d}", [], kind=kind)
    for k in range(1, max(b.storeys for b in blocks) + 1):
        storey(rng, house, k, [b for b in blocks if b.storeys >= k], top)
    for k in range(2, max(b.storeys for b in blocks) + 1):
        house.floors.append(Floor(f"f{k}", outline([b for b in blocks if b.storeys >= k]), (k - 1) * LEVEL))
    house.link()
    stairs(rng, house, blocks[0])
    for w in house.walls:
        openings(rng, w)
    if kind == "box":
        gable(rng, house, blocks[0], top)
    house.link()
    return house


def gable(rng, house: House, b: Block, top: float, pitch: float | None = None) -> None:
    """A gable roof over a block: ridge along x, eaves front and back, the end walls of its top storey made
    gable walls reaching up to the roof planes, and a ceiling on the top storey's walls."""
    k = b.storeys
    base = (k - 1) * LEVEL
    W, D = b.x1 - b.x0, b.y1 - b.y0
    run = D / 2 + EAVE
    if pitch is None:
        pitch = rng.choice([p for p in PITCHES if run * math.hypot(1, p / 12) <= LONGEST] or [PITCHES[0]])
    s = pitch / 12
    z, V = base + top + HEEL - EAVE * s, run * math.hypot(1, s)
    plane = [(0.0, 0.0), (W, 0.0), (W, V), (0.0, V)]
    house.roofs += [Roof("r1", (b.x0, b.y0 - EAVE), (b.x1, b.y0 - EAVE), z, pitch, plane),
                    Roof("r2", (b.x1, b.y1 + EAVE), (b.x0, b.y1 + EAVE), z, pitch, list(plane))]
    for w in house.walls:
        if w.base == base and w.role == "exterior" and w.start[0] == w.end[0] in (b.x0, b.x1):
            L, H = w.length, top + HEEL
            w.height, w.outline = H, [(0.0, 0.0), (L, 0.0), (L, H), (L / 2, H + s * L / 2), (0.0, H)]
    house.floors.append(Floor("c", [(b.x0, b.y0), (b.x1, b.y0), (b.x1, b.y1), (b.x0, b.y1)], base + top, role="ceiling"))


def storey(rng, house: House, k: int, here: list[Block], top: float) -> None:
    """The walls of storey k: exterior walls around the blocks that reach it, junction walls where two meet,
    a spine in each deep block, and cross partitions in the main block."""
    base = (k - 1) * LEVEL
    height = lambda *bs: LEVEL if any(b.storeys > k for b in bs) else top
    outer, shared = edges(here)
    n = 0
    for loop in chain(outer):
        for a, b, o in loop:
            house.walls.append(Wall(f"{k}w{n}", a, b, height(o), base))
            n += 1
    for j, (a, b, o1, o2) in enumerate(_merge(shared)):
        house.walls.append(Wall(f"{k}j{j}", a, b, height(o1, o2), base, role="interior"))
    for b in here:
        if b.y1 - b.y0 > SPAN:
            y = 2 * round((b.y0 + b.y1) / 4)
            house.walls.append(Wall(f"{k}s{'' if b.name == 'main' else b.name[0]}", (b.x0, y), (b.x1, y), height(b), base,
                                    role="interior"))
    cross(rng, house, k, here[0], base, height(here[0]))


def _merge(shared):
    """Shared edges joined into straight runs between the same two blocks."""
    out = []
    for a, b, o1, o2 in sorted(shared, key=lambda e: (e[0][1] == e[1][1], e[0], e[1])):
        if out and out[-1][2:] == (o1, o2) and out[-1][1] == a and _collinear(out[-1][0], a, b):
            out[-1] = (out[-1][0], b, o1, o2)
        else:
            out.append((a, b, o1, o2))
    return out


def cross(rng, house: House, k: int, main: Block, base: float, height: float) -> None:
    """Up to two partitions in the main block, from its front to its spine or from its spine to its back."""
    spine = next((w for w in house.walls if w.id == f"{k}s"), None)
    mid = spine.start[1] if spine else None
    xs: list[float] = []
    for n in range(rng.randint(0, 2)):
        for _ in range(50):
            x = float(rng.randrange(int(main.x0) + 72, int(main.x1) - 71, 2))
            if all(abs(x - y) >= 72 for y in xs):
                a, b = ((x, main.y0), (x, mid or main.y1)) if rng.random() < 0.5 else ((x, mid or main.y0), (x, main.y1))
                house.walls.append(Wall(f"{k}p{n}", a, b, height, base, role="interior"))
                xs.append(x)
                break


def stairs(rng, house: House, main: Block) -> None:
    """A 3 ft by 10 ft stair opening, the same in every floor, in the main block clear of partitions."""
    walls_x = [w.start[0] for w in house.walls if w.role == "interior" and w.start[0] == w.end[0]]
    spine = next((w.start[1] for w in house.walls if w.id == "1s"), main.y1)
    for _ in range(50):
        x = float(rng.randrange(int(main.x0) + 48, int(main.x1) - 84, 2))
        y = main.y0 + 24
        if all(not (x - 30 < wx < x + 66) for wx in walls_x) and y + 120 <= spine - 12:
            for f in house.floors:
                cx, cy = f.corner
                f.openings.append(Opening(f"{f.id}o0", "stair", x - cx, x + 36 - cx, y - cy, y + 120 - cy))
            return


def openings(rng, w: Wall) -> None:
    """Windows in exterior walls, a front door on the ground floor, doors in partitions."""
    if w.role == "exterior":
        for _ in range(rng.randint(1, max(1, int(w.length // 96)))):
            place(rng, w, "window", rng.choice([24, 30, 36, 48, 60, 72]), rng.choice([24, 36, 48, 60]))
        if w.base == 0 and w.start[1] == w.end[1] == 0 and not any(o.kind == "door" for o in w.openings):
            place(rng, w, "door", rng.choice([34, 38]), HEAD)
    elif rng.random() < 0.6 and w.length >= 72:
        place(rng, w, "door", 34, HEAD)


def toy() -> House:
    """A small two-storey house for showing what a rule does: 14 x 10 ft, a window and a door in the front wall
    and a spine below, a floor with a stair, and a window upstairs."""
    house = House("toy", [])
    blocks = [Block("main", 0.0, 0.0, 168.0, 120.0, 2)]
    for k in (1, 2):
        storey(random.Random(0), house, k, blocks, 97.125)
    house.walls = [w for w in house.walls if w.role == "exterior"]
    house.walls.append(Wall("1s", (0.0, 60.0), (168.0, 60.0), LEVEL, 0.0, role="interior"))
    house.floors.append(Floor("f2", outline(blocks), LEVEL, openings=[Opening("f2o0", "stair", 120, 156, 66, 114)]))
    house.link()
    add_opening(house.wall("1w0"), "window", 24, 36, 48)
    add_opening(house.wall("1w0"), "door", 70, 38, HEAD)
    add_opening(house.wall("2w0"), "window", 60, 48, 48)
    gable(None, house, blocks[0], 97.125, pitch=8)
    house.link()
    return house
