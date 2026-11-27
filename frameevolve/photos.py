"""Photos of a house's four sides, from Cambridge's photo mesh: the evidence a brief is written from.

The city publishes a photo mesh (an Esri I3S integrated mesh: one textured skin over everything, from aerial
photos). It is too soft to measure openings from, but good enough to count them and say roughly where they are.
For a detailed house, the mesh around it is brought into the house's coordinates and drawn square to each side
(south, east, north, west: seen from -y, +x, +y, -x), nearest surface first and nothing that stands more than 18 in. in front of the house's wall there (trees, cars,
the neighbour), with a ruler from 0 to 1 along the
side and a line at every floor: a brief gives openings by storey and place on that ruler (detail.py).

Pictures and a meta.json go to data/cambridge/evidence/<model>; mesh pieces are cached in data/cambridge/mesh.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import ssl
import struct
import urllib.request

import numpy as np
import truststore
from PIL import Image, ImageDraw
from pyproj import Transformer

from frameevolve import cambridge

MESH = "https://tiles.arcgis.com/tiles/WnzC35krSYGuYov4/arcgis/rest/services/Mesh_Cambridge_Reality_WGS1984_EGM96/SceneServer/layers/0"
CACHE = cambridge.OUT / "mesh"
EVIDENCE = cambridge.OUT / "evidence"
FOOT = 0.3048006096          # a US survey foot, metres: the building models are in feet, the mesh in metres
SIDES = {"south": (0, -1), "east": (1, 0), "north": (0, 1), "west": (-1, 0)}     # the way each side faces
PX = 1.0                     # inches a pixel
DATUM = 38.5                 # the mesh stands this much higher than the models (inches): measured at ten roofs, 3.2 ft
FRONT = 18.0                 # what stands further than this in front of the house's wall there is left out: trees, cars, the neighbour


def get(path: str) -> bytes:
    """A piece of the mesh service, kept once fetched."""
    f = CACHE / path.replace("/", "_").replace("?", "_")
    if not f.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(f"{MESH}/{path}", headers={"Accept-Encoding": "gzip"})
        data = urllib.request.urlopen(request, context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)).read()
        f.write_bytes(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)
    return f.read_bytes()


def node(i: int) -> dict:
    return json.loads(get(f"nodepages/{i // 64}?f=json"))["nodes"][i % 64]


def leaves(lat: float, lon: float, reach: float = 40.0) -> list[dict]:
    """The finest nodes of the mesh whose bounding sphere comes within `reach` metres of a point."""
    out, todo = [], [0]
    while todo:
        n = node(todo.pop())
        c, h = n["obb"]["center"], n["obb"]["halfSize"]
        if cambridge.metres(c[1], c[0], lat, lon) > math.sqrt(sum(a * a for a in h)) + reach:
            continue
        if n.get("children"):
            todo += n["children"]
        elif "mesh" in n:
            out.append(n)
    return out


def mesh_around(lat: float, lon: float):
    """The photo mesh around a point: triangles (N, 3, 3) as lon, lat, metres up; their texture coordinates
    (N, 3, 2); which texture each uses; the textures."""
    P, UV, T, textures = [], [], [], []
    for n in leaves(lat, lon):
        buf = get(f"nodes/{n['mesh']['geometry']['resource']}/geometries/0")
        count = struct.unpack_from("<I", buf, 0)[0]
        pos = np.frombuffer(buf, "<f4", count * 3, 8).reshape(-1, 3).astype(np.float64) + np.array(n["obb"]["center"])
        P.append(pos.reshape(-1, 3, 3))
        UV.append(np.frombuffer(buf, "<f4", count * 2, 8 + count * 12).reshape(-1, 3, 2))
        T += [len(textures)] * (count // 3)
        textures.append(np.asarray(Image.open(io.BytesIO(get(f"nodes/{n['mesh']['material']['resource']}/textures/0"))).convert("RGB")))
    return np.concatenate(P), np.concatenate(UV), np.array(T), textures


def in_house(P, record: dict, env, lift: float, path) -> np.ndarray:
    """Mesh points (lon, lat, metres) in a detailed house's coordinates. The model files are in state plane feet
    less a whole number of hundreds, found from the model's centre."""
    to = Transformer.from_crs(4326, 2249, always_xy=True)
    vs = np.array([list(map(float, l.split()[1:4])) for l in open(path) if l.startswith("v ")])
    cx, cy = to.transform(record["model_lon"], record["model_lat"])
    ox = 100 * round((cx - (vs[:, 0].min() + vs[:, 0].max()) / 2) / 100)
    oy = 100 * round((cy - (vs[:, 1].min() + vs[:, 1].max()) / 2) / 100)
    x, y = to.transform(P[..., 0], P[..., 1])
    x, y, z = 12 * (x - ox), 12 * (y - oy), 12 * P[..., 2] / FOOT - DATUM - env.z0
    c, s = math.cos(env.turn), math.sin(env.turn)
    dx, dy = x - env.about[0], y - env.about[1]
    return np.stack([env.about[0] + dx * c - dy * s - env.shift[0], env.about[1] + dx * s + dy * c - env.shift[1], z - lift], -1)


def extent(house, side: str) -> tuple[float, float]:
    """A house's extent along a side's ruler (left to right as seen from outside), in the ruler's coordinate."""
    d = SIDES[side]
    r = [-d[1] * p[0] + d[0] * p[1] for w in house.walls if w.role == "exterior" for p in (w.start, w.end)]
    return min(r), max(r)


def side_photo(house, side: str, P, UV, T, textures) -> Image.Image:
    """The photo mesh seen square to one side of a house, the nearest surface showing, with the ruler and the
    floor lines drawn on."""
    d = np.array([*SIDES[side], 0.0])
    right = np.array([-d[1], d[0], 0.0])
    r0, r1 = extent(house, side)
    walls = [w for w in house.walls if w.role == "exterior"]
    top = max(w.base + max(v for _, v in w.outline_uv) for w in walls) + 60
    low = -house.foundation - 24
    depth = [p[0] * d[0] + p[1] * d[1] for w in walls for p in (w.start, w.end)]
    m = 12.0
    W, H = int((r1 - r0 + 2 * m) / PX), int((top - low) / PX)
    pu, pv, pd = (P @ right - r0 + m) / PX, (P[..., 2] - low) / PX, P @ d
    limit = np.full(W, -1e9)                          # for each column of the picture, how near the viewer a surface may be
    for w in walls:
        a, b = sorted(((w.start[0] * right[0] + w.start[1] * right[1]) - r0 + m, (w.end[0] * right[0] + w.end[1] * right[1]) - r0 + m))
        x0, x1 = max(0, int(a / PX) - 2), min(W, int(b / PX) + 3)
        if x1 > x0:
            limit[x0:x1] = np.maximum(limit[x0:x1], max(w.start[0] * d[0] + w.start[1] * d[1], w.end[0] * d[0] + w.end[1] * d[1]) + FRONT)
    limit[limit < -1e8] = min(depth)                  # beside the house: nothing
    ok = (pu.max(1) > 0) & (pu.min(1) < W) & (pv.max(1) > 0) & (pv.min(1) < H) & (pd.min(1) > min(depth) - 12) & (pd.min(1) < max(depth) + FRONT)
    img = np.full((H, W, 3), 235, np.uint8)
    near = np.full((H, W), -1e9)
    for k in np.nonzero(ok)[0]:
        a, b = pu[k], pv[k]
        x0, x1, y0, y1 = max(0, int(a.min())), min(W, int(a.max()) + 1), max(0, int(b.min())), min(H, int(b.max()) + 1)
        den = (b[1] - b[2]) * (a[0] - a[2]) + (a[2] - a[1]) * (b[0] - b[2])
        if x0 >= x1 or y0 >= y1 or abs(den) < 1e-9:
            continue
        X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        l0 = ((b[1] - b[2]) * (X - a[2]) + (a[2] - a[1]) * (Y - b[2])) / den
        l1 = ((b[2] - b[0]) * (X - a[2]) + (a[0] - a[2]) * (Y - b[2])) / den
        l2 = 1 - l0 - l1
        z = l0 * pd[k, 0] + l1 * pd[k, 1] + l2 * pd[k, 2]
        hit = (l0 >= -1e-3) & (l1 >= -1e-3) & (l2 >= -1e-3) & (z > near[y0:y1, x0:x1]) & (z < limit[None, x0:x1])
        if not hit.any():
            continue
        tex = textures[T[k]]
        th, tw = tex.shape[:2]
        tu = l0 * UV[k, 0, 0] + l1 * UV[k, 1, 0] + l2 * UV[k, 2, 0]
        tv = l0 * UV[k, 0, 1] + l1 * UV[k, 1, 1] + l2 * UV[k, 2, 1]
        img[y0:y1, x0:x1][hit] = tex[np.clip((tv * th).astype(int), 0, th - 1)[hit], np.clip((tu * tw).astype(int), 0, tw - 1)[hit]]
        near[y0:y1, x0:x1][hit] = z[hit]
    picture = Image.fromarray(img[::-1])
    draw = ImageDraw.Draw(picture)
    y_of = lambda z: H - (z - low) / PX
    for k, base in enumerate(sorted({w.base for w in walls})):
        draw.line([(0, y_of(base)), (W, y_of(base))], fill=(255, 220, 0), width=1)
        draw.text((W - 150, y_of(base) - 12), f"guessed floor of storey {k + 1}", fill=(255, 220, 0))
    for feet in range(0, int((top + house.foundation) / 12) + 1, 5):      # heights over the ground, on the left
        y = y_of(feet * 12 - house.foundation)
        draw.line([(0, y), (10, y)], fill=(0, 255, 255), width=2)
        draw.text((12, y - 5), f"{feet} ft", fill=(0, 255, 255))
    for i in range(11):                               # the ruler: 0 at the house's left end, 1 at its right
        x = (m + (r1 - r0) * i / 10) / PX
        draw.line([(x, H - 14), (x, H)], fill=(255, 0, 0), width=2)
        draw.line([(x, 0), (x, 8)], fill=(255, 0, 0), width=2)
        draw.text((x + 2, H - 13), f"{i / 10:.1f}", fill=(255, 0, 0))
    return picture


def evidence(house, record: dict, env, path) -> dict:
    """Draw and save the four side photos of a detailed house; returns what was saved (meta.json)."""
    out = EVIDENCE / record["model"]
    out.mkdir(parents=True, exist_ok=True)
    P, UV, T, textures = mesh_around(record["model_lat"], record["model_lon"])
    Q = in_house(P, record, env, house.foundation, path)
    meta = {"model": record["model"], "address": record["address"], "storeys": len({w.base for w in house.walls}), "sides": {}}
    for side in SIDES:
        side_photo(house, side, Q, UV, T, textures).save(out / f"{side}.jpg", quality=88)
        r0, r1 = extent(house, side)
        meta["sides"][side] = {"width_in": round(r1 - r0)}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta
