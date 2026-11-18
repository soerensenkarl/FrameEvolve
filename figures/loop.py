"""The report's overview figure: inputs, the loop, the output, in the plain style of the report's other figures
(grey surfaces, black members, red for what matters) and drawn from the real geometry: a house as the builder
gets it with its loads, framed, its faults as the verifier finds them, and the frame as prefab panels.
Writes loop.svg, loop.pdf and loop.png beside this file (PDF and PNG by headless Chrome).

    uv run python figures/loop.py
"""
import base64
import json
import math
import struct
import zlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from frameevolve.builder import build, load_rules  # noqa: E402
from frameevolve.model import House  # noqa: E402
from frameevolve.verifier import verify  # noqa: E402

HOUSE, GRAMMAR, RUN = "h001", "advanced.py", "seed1"   # the house, the grammar that frames it, the run whose Pareto set is shown
W, H = 1100, 448
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
INK, GREY, LINE, RED, AMBER = "#1d1d1b", "#6b6b6b", "#a8a8a8", "#d8342c", "#e8930c"
CSS = f"""
text {{ font-family: Helvetica, Arial, sans-serif; fill: {INK}; }}
.col {{ font-size: 11px; font-weight: 700; letter-spacing: .12em; fill: {GREY}; }}
.title {{ font-size: 14px; font-weight: 700; }}
.sub {{ font-size: 11px; fill: {GREY}; }}
.mono {{ font: 10.5px Menlo, Consolas, monospace; fill: {INK}; }}
.box {{ fill: #fff; stroke: {LINE}; stroke-width: 1; }}
.env {{ fill: none; stroke: {LINE}; stroke-width: 1; stroke-dasharray: 4 3; }}
.envlabel {{ font-size: 11px; font-weight: 700; fill: {INK}; }}
.arrow {{ fill: none; stroke: {INK}; stroke-width: 1.1; }}
.label {{ font-size: 11px; fill: {GREY}; }}
"""

# ---------------------------------------------------------------- the view: isometric from the front right

E = (0.75, -1.0, 0.85)                          # towards the viewer
n = math.sqrt(sum(c * c for c in E))
E = tuple(c / n for c in E)
R = (-E[1], E[0], 0.0)                          # screen right: z x E
n = math.hypot(R[0], R[1])
R = (R[0] / n, R[1] / n, 0.0)
U = (E[1] * R[2] - E[2] * R[1], E[2] * R[0] - E[0] * R[2], E[0] * R[1] - E[1] * R[0])   # screen up: E x R


def proj(p):
    return (sum(p[k] * R[k] for k in range(3)), -sum(p[k] * U[k] for k in range(3)))


def depth(pts):
    return sum(sum(p[k] * E[k] for k in range(3)) for p in pts) / len(pts)


def hull(pts):
    pts = sorted(set((round(x, 2), round(y, 2)) for x, y in pts))
    if len(pts) < 3:
        return pts
    def half(ps):
        out = []
        for p in ps:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out
    lo, hi = half(pts), half(reversed(pts))
    return lo[:-1] + hi[:-1]


def drawing(shapes, x, y, w, h, arrows=()):
    """Shapes [(world points, fill, stroke, stroke width, as hull, group)] drawn far to near, fitted in w x h at x, y;
    then arrows [(world from, world to)] over them, in red: the loads."""
    # far to near by group (a panel, a wall, a roof plane), then by member within it: a long member's middle
    # alone says little about what it is in front of
    groups = {}
    for sh in shapes:
        groups.setdefault(sh[5] if len(sh) > 5 else id(sh), []).extend(sh[0])
    far = {g: depth(pts) for g, pts in groups.items()}
    shapes = sorted(shapes, key=lambda sh: (far[sh[5] if len(sh) > 5 else id(sh)], depth(sh[0])))
    flat = [[proj(p) for p in s[0]] for s in shapes]
    lines = [(proj(a), proj(b)) for a, b in arrows]
    xs = [p[0] for ps in flat for p in ps] + [p[0] for ab in lines for p in ab]
    ys = [p[1] for ps in flat for p in ps] + [p[1] for ab in lines for p in ab]
    k = min(w / (max(xs) - min(xs)), h / (max(ys) - min(ys)))
    ox = x + (w - (max(xs) - min(xs)) * k) / 2 - min(xs) * k
    oy = y + (h - (max(ys) - min(ys)) * k) / 2 - min(ys) * k
    out = []
    for (_, fill, stroke, sw, as_hull, *_), ps in zip(shapes, flat):
        ps = hull(ps) if as_hull else ps
        d = "M" + "L".join(f"{ox + px * k:.1f} {oy + py * k:.1f}" for px, py in ps) + "Z"
        out.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"/>')
    for (ax, ay), (bx, by) in lines:
        out.append(f'<path d="M{ox + ax * k:.1f} {oy + ay * k:.1f}L{ox + bx * k:.1f} {oy + by * k:.1f}" '
                   f'stroke="{RED}" stroke-width="1.2" marker-end="url(#load)"/>')
    return "".join(out)


def colour(hexa):
    """A colour #rgb or #rrggbb as [r, g, b]."""
    hexa = hexa.lstrip("#")
    hexa = "".join(c * 2 for c in hexa) if len(hexa) == 3 else hexa
    return [int(hexa[i:i + 2], 16) for i in (0, 2, 4)]


def png(rgb) -> bytes:
    """An RGB array (height, width, 3) of bytes as a PNG file."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\0" + rgb[i].tobytes() for i in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def render(shapes, x, y, w, h, px=5, ss=3):
    """Faces [(world quad, fill, line colour, ...)] drawn with a depth buffer, as a renderer does: at every pixel
    the face nearest the viewer wins, and a line runs where one face meets another or the background. Painting
    faces back to front cannot get crossing members right; this can. Returns an image px pixels a unit, fitted
    in w x h at x, y (drawn ss times larger and averaged down, for smooth lines)."""
    flat = [[proj(p) for p in sh[0]] for sh in shapes]
    xs = [p[0] for ps in flat for p in ps]
    ys = [p[1] for ps in flat for p in ps]
    k = min(w / (max(xs) - min(xs)), h / (max(ys) - min(ys)))
    ox = (w - (max(xs) - min(xs)) * k) / 2 - min(xs) * k
    oy = (h - (max(ys) - min(ys)) * k) / 2 - min(ys) * k
    S = px * ss
    W_, H_ = int(w * S), int(h * S)
    zbuf = np.full((H_, W_), -np.inf)
    ids = np.full((H_, W_), -1, dtype=np.int32)
    for i, (sh, ps) in enumerate(zip(shapes, flat)):
        q = [((ox + a * k) * S, (oy + b * k) * S) for a, b in ps]
        z = [sum(p[c] * E[c] for c in range(3)) for p in sh[0]]
        for t in ((0, 1, 2), (0, 2, 3)):
            (x0, y0), (x1, y1), (x2, y2) = (q[j] for j in t)
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-9:
                continue
            c0, c1 = max(int(min(x0, x1, x2)), 0), min(int(max(x0, x1, x2)) + 1, W_)
            r0, r1 = max(int(min(y0, y1, y2)), 0), min(int(max(y0, y1, y2)) + 1, H_)
            if c0 >= c1 or r0 >= r1:
                continue
            gx, gy = np.meshgrid(np.arange(c0, c1) + .5, np.arange(r0, r1) + .5)
            l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
            l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
            l2 = 1 - l0 - l1
            inside = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
            d = l0 * z[t[0]] + l1 * z[t[1]] + l2 * z[t[2]]
            zb, ib = zbuf[r0:r1, c0:c1], ids[r0:r1, c0:c1]
            win = inside & (d > zb)
            zb[win], ib[win] = d[win], i
    fills = np.array([colour(sh[1]) for sh in shapes] + [[255, 255, 255]], dtype=np.float64)
    lines = np.array([colour(sh[2]) for sh in shapes] + [[255, 255, 255]], dtype=np.float64)
    img = fills[ids]                     # -1 indexes the white at the end
    edge = np.zeros_like(ids, dtype=bool)
    edge[:, :-1] |= ids[:, :-1] != ids[:, 1:]
    edge[:-1, :] |= ids[:-1, :] != ids[1:, :]
    # the line takes the colour of the nearer face on it; widened to ss pixels, one pixel once averaged down
    near = ids.copy()
    near[:, :-1] = np.where(zbuf[:, 1:] > zbuf[:, :-1], ids[:, 1:], near[:, :-1])
    near[:-1, :] = np.where(zbuf[1:, :] > zbuf[:-1, :], ids[1:, :], near[:-1, :])
    wide = edge.copy()
    for _ in range(ss - 1):
        wide[1:, :] |= wide[:-1, :]
        wide[:, 1:] |= wide[:, :-1]
    img[wide] = lines[near[wide]]
    img = img.reshape(H_ // ss, ss, W_ // ss, ss, 3).mean(axis=(1, 3)) if H_ % ss == 0 and W_ % ss == 0 else \
        img[: H_ // ss * ss, : W_ // ss * ss].reshape(H_ // ss, ss, W_ // ss, ss, 3).mean(axis=(1, 3))
    data = base64.b64encode(png(np.clip(img, 0, 255).astype(np.uint8))).decode()
    return f'<image x="{x}" y="{y}" width="{img.shape[1] / px:.2f}" height="{img.shape[0] / px:.2f}" href="data:image/png;base64,{data}"/>'


def surfaces(house):
    """The house as the builder gets it: walls and roof planes, openings cut out as white."""
    out = []
    for x in [*house.walls, *house.roofs]:
        if x.role not in ("exterior", "roof"):
            continue
        out.append(([x.world(u, v, 0) for u, v in x.outline_uv], "#ececea", "#7d7d7a", 0.8, False))
        for o in x.openings:
            pts = [x.world(u, v, -0.5) for u, v in ((o.u0, o.v0), (o.u1, o.v0), (o.u1, o.v1), (o.u0, o.v1))]
            out.append((pts, "#fff", "#7d7d7a", 0.6, False))
    return out


def loads(house):
    """Arrows for the loads: gravity down onto each roof plane, the wind against the front walls."""
    out = []
    for r in house.roofs:
        if -r.ew[0] * E[0] - r.ew[1] * E[1] <= 0:
            continue          # a plane facing away: its arrows would show through the plane in front
        U, V = r.size
        for fu in (0.2, 0.5, 0.8):
            for fv in (0.3, 0.65):
                p = r.world(U * fu, V * fv, 0)
                out.append(((p[0], p[1], p[2] + 60), (p[0], p[1], p[2] + 3)))
    y0 = min(w.start[1] for w in house.walls)
    for w in house.walls:
        if w.role == "exterior" and abs(w.start[1] - y0) < 1 and abs(w.end[1] - y0) < 1:
            for fu in (0.25, 0.75):
                x = w.start[0] + (w.end[0] - w.start[0]) * fu
                z = w.base + w.height * 0.5
                out.append(((x, y0 - 70, z), (x, y0 - 3, z)))
    return out


def facing(house):
    """The exterior walls and roof planes that face the viewer."""
    xs = [p[0] for w in house.walls for p in (w.start, w.end)]
    ys = [p[1] for w in house.walls for p in (w.start, w.end)]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    out = set()
    for w in house.walls:
        mx, my = (w.start[0] + w.end[0]) / 2 - cx, (w.start[1] + w.end[1]) / 2 - cy
        n = w.normal if w.normal[0] * mx + w.normal[1] * my > 0 else (-w.normal[0], -w.normal[1])
        if w.role == "exterior" and n[0] * E[0] + n[1] * E[1] > 0:
            out.add(w.id)
    return out | {r.id for r in house.roofs if -r.ew[0] * E[0] - r.ew[1] * E[1] > 0}


def faces(m, pts=None):
    """A member as the faces of its box that look towards the viewer: the box round its points (moved, if given)
    in its own axes, so a cut member keeps about its cut length."""
    pts = pts or m.points
    a = [m.end[k] - m.start[k] for k in range(3)]
    n = math.sqrt(sum(c * c for c in a))
    a = [c / n for c in a]
    u = list(m.up)
    v = [a[1] * u[2] - a[2] * u[1], a[2] * u[0] - a[0] * u[2], a[0] * u[1] - a[1] * u[0]]
    axes = (a, u, v)
    dot = lambda p, d: sum(p[k] * d[k] for k in range(3))
    lo = [min(dot(p, d) for p in pts) for d in axes]
    hi = [max(dot(p, d) for p in pts) for d in axes]
    corner = lambda i, j, k: tuple((lo[0], hi[0])[i] * a[c] + (lo[1], hi[1])[j] * u[c] + (lo[2], hi[2])[k] * v[c] for c in range(3))
    out = []
    for axis, d in enumerate(axes):
        for side, sign in ((0, -1), (1, 1)):
            if sign * dot(d, E) <= 0:
                continue             # facing away
            quad = []
            for i, j in ((0, 0), (1, 0), (1, 1), (0, 1)):
                idx = [i, j]
                idx.insert(axis, side)
                quad.append(corner(*idx))
            out.append(quad)
    return out


def members(house, frame, colour):
    """The members of the exterior walls and the roof, without the clutter inside: those facing the viewer as
    colour gives them, the far ones faint. A member colour marks (red or amber) shows wherever it is."""
    shell = {w.id for w in house.walls if w.role == "exterior"} | {r.id for r in house.roofs}
    near = facing(house)
    out = []
    for m in frame.members:
        if m.surface in shell or colour(m)[0] in (RED, AMBER):
            look = colour(m) if m.surface in near or colour(m)[0] in (RED, AMBER) else ("#fff", "#d4d4d0", 0.25)
            out += [(f, *look, False, m.panel or m.surface) for f in faces(m)]
    return out


# ---------------------------------------------------------------- pieces

def box(x, y, w, h, title, sub=""):
    return (f'<rect class="box" x="{x}" y="{y}" width="{w}" height="{h}"/>'
            f'<text class="title" x="{x + 12}" y="{y + h - (26 if sub else 12)}">{title}</text>'
            + (f'<text class="sub" x="{x + 12}" y="{y + h - 10}">{sub}</text>' if sub else ""))


def arrow(d, label="", lx=0, ly=0, anchor="middle"):
    return (f'<path class="arrow" d="{d}" marker-end="url(#head)"/>'
            + (f'<text class="label" x="{lx}" y="{ly}" text-anchor="{anchor}">{label}</text>' if label else ""))


def rule_cards(x, y, w, rules):
    """The grammar as cards, as in the report's rule figure: rules 1, 2, 3, then the dots, then the last (n), each
    with its number, its name and what it matches."""
    ch, gap, out = 26, 4, []
    shown = [(i + 1, r) for i, r in enumerate(rules[:3])] + [None, ("n", rules[-1])]
    cy = y
    for item in shown:
        if item is None:       # the rules between
            out += [f'<circle cx="{x + 14}" cy="{cy + 3 + k * 6}" r="1.4" fill="{GREY}"/>' for k in range(3)]
            cy += 16
            continue
        n, r = item
        what = "the house" if r.match == "house" else f"every {r.match}"
        out.append(f'<rect x="{x}" y="{cy}" width="{w}" height="{ch}" rx="3" fill="#fff" stroke="{LINE}"/>'
                   f'<circle cx="{x + 14}" cy="{cy + ch / 2}" r="8" fill="{INK}"/>'
                   f'<text x="{x + 14}" y="{cy + ch / 2 + 3.5}" text-anchor="middle" style="font-size:9.5px;font-weight:700;fill:#fff">{n}</text>'
                   f'<text x="{x + 28}" y="{cy + 12}" style="font-size:11.5px;font-weight:700">{r.__name__}</text>'
                   f'<text x="{x + 28}" y="{cy + 23}" style="font-size:9.5px"><tspan fill="{RED}">match</tspan>'
                   f'<tspan fill="{GREY}"> {what}</tspan></text>')
        cy += ch + gap
    return "".join(out)


def tone(quad):
    """A face's grey, by which way it faces: light on top, darker on the sides, as timber looks in daylight."""
    a = [quad[1][k] - quad[0][k] for k in range(3)]
    b = [quad[3][k] - quad[0][k] for k in range(3)]
    n = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    up = abs(n[2]) / (math.sqrt(sum(c * c for c in n)) or 1)
    side = abs(n[0]) / (math.sqrt(sum(c * c for c in n)) or 1)
    return "#e4e2dd" if up > 0.7 else "#cdcac3" if side > 0.5 else "#d8d5cf"


def exploded(frame, keep, gap=0.22):
    """The members `keep` takes, moved apart from the house's middle by panel (by surface for members built on
    site), each group as one piece: the frame as it is delivered. Returns [(member, its moved points)]."""
    ms = [m for m in frame.members if keep(m)]
    pts = [p for m in ms for p in m.points]
    mid = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
    groups = {}
    for m in ms:
        groups.setdefault(m.panel or m.surface, []).append(m)
    out = []
    for g in groups.values():
        c = [sum(p[k] for m in g for p in m.points) / sum(len(m.points) for m in g) for k in range(3)]
        d = [(c[k] - mid[k]) * gap * (2.4 if k == 2 else 1) for k in range(3)]   # lifted more than spread
        out += [(m, [tuple(p[k] + d[k] for k in range(3)) for p in m.points]) for m in g]
    return out


TOP = 150    # the top row's height


def example_faults(report):
    """Three faults for the report box: two hard of different checks, one soft."""
    out, seen = [], set()
    for want in (True, True, False):
        f = next((f for f in report.faults if f.hard == want and f.check not in seen), None)
        if f:
            out.append(f)
            seen.add(f.check)
    return out


def wrap(text, width, lines):
    words, out = text.split(), [""]
    for w in words:
        if len(out[-1]) + len(w) + 1 > width:
            if len(out) == lines:
                out[-1] = out[-1].rstrip() + "…"
                return out
            out.append("")
        out[-1] += ("" if not out[-1] else " ") + w
    return out


def pareto(run, x, y, w, h):
    """The run's grammars against its validation houses: a black square where a grammar is the best on that house.
    Grammars with a square form the Pareto set the search picks parents from."""
    val = [Path(v).stem for v in json.loads((run / "config.json").read_text())["val"]]
    cands = [json.loads(line) for line in (run / "candidates.jsonl").read_text().splitlines()][-7:]
    best = {v: min(tuple(c["scores"][v]) for c in cands) for v in val}
    cw, rh, lab = (w - 30) / len(val), h / len(cands), 30
    out = []
    for i, c in enumerate(cands):
        wins = [tuple(c["scores"][v]) == best[v] for v in val]
        out.append(f'<text class="sub" x="{x}" y="{y + i * rh + rh - 1.5}" style="font-size:8.5px;{"" if any(wins) else "fill:#c0c0bc"}">{c["id"]}</text>')
        for j, win in enumerate(wins):
            cx = x + lab + j * cw
            out.append(f'<rect x="{cx + 1:.1f}" y="{y + i * rh + 1:.1f}" width="{cw - 2:.1f}" height="{rh - 2:.1f}" '
                       f'fill="{INK if win else "#ececea"}"/>')
    out.append(f'<text class="sub" x="{x + lab}" y="{y + h + 11}" style="font-size:8.5px">houses →</text>')
    return "".join(out)


def figure():
    house = House.load(ROOT / "data" / "houses" / f"{HOUSE}.json")
    framed = build(ROOT / "grammars" / GRAMMAR, house)
    report = verify(house, framed)
    # a member in a soft fault shows amber even when it is in a hard one too, so the soft ones are seen
    soft = {mid for f in report.faults if not f.hard for mid in f.members}
    hard = {mid for f in report.faults if f.hard for mid in f.members} - soft
    rules = load_rules(ROOT / "grammars" / GRAMMAR)
    shell = {w.id for w in house.walls if w.role == "exterior"} | {r.id for r in house.roofs}
    near = facing(house)

    # a grid: house and output as full-height columns; the proposer and the search above the grammar, frame
    # and verifier
    top, row, bottom = 34, 228, 422             # the top row's top, the bottom row's top, both rows' bottom
    cols = [(20, 180), (240, 180), (460, 180), (680, 180), (900, 180)]   # house, grammar, frame, verifier, output
    (hx, hw), (gx, gw), (fx, fw), (vx, vw), (ox, ow) = cols
    mid = row + 90                              # where the arrows along the bottom row run

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">', f"<style>{CSS}</style>",
         f'<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" '
         f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{INK}"/></marker>'
         f'<marker id="load" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" '
         f'orient="auto"><path d="M0 0L10 5L0 10z" fill="{RED}"/></marker></defs>',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text class="col" x="{hx}" y="22">INPUT</text>', f'<text class="col" x="{gx}" y="22">LOOP</text>',
         f'<text class="col" x="{ox}" y="22">OUTPUT</text>']

    # input
    o += [box(hx, top, hw, bottom - top, "House", "surfaces and loads"),
          drawing(surfaces(house), hx + 10, top + 60, hw - 20, 200, loads(house))]

    # the loop
    o += [f'<rect class="env" x="{gx - 16}" y="{row - 16}" width="{vx + vw - gx + 32}" height="{bottom - row + 32}"/>',
          f'<text class="envlabel" x="{vx + vw + 10}" y="{bottom + 11}" text-anchor="end">Deterministic</text>']
    # above: the proposer edits, the report says what is wrong, the search keeps the best grammar for each house
    o.append(box(gx, top, gw, TOP, "Proposer", "LLM edits a rule"))
    diff = [(" def header(s, o):", INK), ("-  s.place(\"2x8\", ...)", RED), ("+  n = plies(s.load(o))", "#2f8a4a"),
            ("+  for i in range(n):", "#2f8a4a"), ("+    s.place(\"2x10\", ...)", "#2f8a4a")]
    o += [f'<text class="mono" x="{gx + 12}" y="{top + 26 + i * 16}" xml:space="preserve" style="fill:{c};white-space:pre">{t}</text>'
          for i, (t, c) in enumerate(diff)]

    o.append(box(fx, top, fw, TOP, "Report", "faults in words"))
    for i, f in enumerate(example_faults(report)):
        y = top + 22 + i * 32
        o.append(f'<rect x="{fx + 12}" y="{y - 8}" width="8" height="8" fill="{RED if f.hard else AMBER}"/>'
                 f'<text x="{fx + 25}" y="{y}" style="font-size:10.5px;font-weight:700">{f.check}</text>')
        o += [f'<text class="sub" x="{fx + 25}" y="{y + 12 + j * 11}" style="font-size:9.5px">{t}</text>'
              for j, t in enumerate(wrap(f.message, 31, 1))]

    o.append(box(vx, top, vw, TOP, "Search", "Pareto set: best per house"))
    o.append(pareto(ROOT / "runs" / RUN, vx + 12, top + 12, vw - 24, 80))

    rh = bottom - row
    o += [box(gx, row, gw, rh, "Grammar", "rules: match → action"), rule_cards(gx + 12, row + 10, gw - 24, rules),
          box(fx, row, fw, rh, "Frame", f"{len(framed.members):,} members"),
          render(members(house, framed, lambda m: ("#fff", "#4a4a47", 0.25)), fx + 10, row + 10, fw - 20, 118),
          box(vx, row, vw, rh, "Verifier", " "),
          f'<rect x="{vx + 12}" y="{row + rh - 19}" width="9" height="9" fill="{RED}"/>'
          f'<text class="sub" x="{vx + 25}" y="{row + rh - 10}">hard</text>'
          f'<rect x="{vx + 62}" y="{row + rh - 19}" width="9" height="9" fill="{AMBER}"/>'
          f'<text class="sub" x="{vx + 75}" y="{row + rh - 10}">soft faults</text>',
          render(members(house, framed, lambda m: (RED, "#7a1a15", 0.5) if m.id in hard else
                          (AMBER, "#8a5506", 0.5) if m.id in soft else ("#f4f4f2", "#b8b8b5", 0.3)),
                  vx + 10, row + 10, vw - 20, 118)]

    # output: the frame as the prefab panels it is built in, pulled apart
    panel_shapes = [(f, tone(f) if m.surface in near else "#f6f6f4", "#4a4a47" if m.surface in near else "#c4c4c0",
                     0.25, False, m.panel or m.surface)
                    for m, pts in exploded(framed, lambda m: m.surface in shell) for f in faces(m, pts)]
    o += [box(ox, top, ow, bottom - top, "Evolved grammar", "frames as prefab panels"),
          render(panel_shapes, ox + 10, top + 60, ow - 20, 220)]

    # arrows: none cross
    o += [arrow(f"M{hx + hw} {mid}H{gx}"),
          arrow(f"M{gx + gw} {mid}H{fx}", "build", (gx + gw + fx) / 2, mid - 8),
          arrow(f"M{fx + fw} {mid}H{vx}"),
          arrow(f"M{vx + vw} {mid}H{ox}"),
          arrow(f"M{vx + vw / 2} {row}V{top + TOP}", "score", vx + vw / 2 + 6, top + TOP + 17, "start"),
          arrow(f"M{vx} {top + TOP / 2}H{fx + fw}", "parent", (vx + fx + fw) / 2, top + TOP / 2 - 8),
          arrow(f"M{fx} {top + TOP / 2}H{gx + gw}"),
          arrow(f"M{gx + gw / 2} {top + TOP}V{row}", "edit", gx + gw / 2 + 6, top + TOP + 17, "start"),
          "</svg>"]
    return "\n".join(o)


if __name__ == "__main__":
    svg = HERE / "loop.svg"
    svg.write_text(figure())
    html = HERE / "loop.html"
    html.write_text(f"<!doctype html><style>@page {{ size: {W}px {H}px; margin: 0 }} html, body {{ margin: 0 }}</style>{svg.read_text()}")
    run = lambda *a: subprocess.run([CHROME, "--headless", "--disable-gpu", *a, html.as_uri()], check=True, capture_output=True)
    run("--no-pdf-header-footer", f"--print-to-pdf={HERE / 'loop.pdf'}")
    run("--hide-scrollbars", f"--window-size={W},{H}", "--force-device-scale-factor=3", f"--screenshot={HERE / 'loop.png'}")
    html.unlink()
