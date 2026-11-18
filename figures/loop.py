"""The report's overview figure: inputs, the loop, the output, in the plain style of the report's other figures
(grey surfaces, black members, red for what matters) and drawn from the real geometry: a house as the builder
gets it with its loads, framed, its faults as the verifier finds them, and the frame as prefab panels.
Writes loop.svg, loop.pdf and loop.png beside this file (PDF and PNG by headless Chrome).

    uv run python figures/loop.py
"""
import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from frameevolve.builder import build, load_rules  # noqa: E402
from frameevolve.model import House  # noqa: E402
from frameevolve.verifier import verify  # noqa: E402

HOUSE, GRAMMAR, RUN = "h001", "advanced.py", "seed1"   # the house, the grammar that frames it, the run whose curve is shown
W, H = 1100, 436
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
INK, GREY, LINE, RED = "#1d1d1b", "#6b6b6b", "#a8a8a8", "#d8342c"
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


def members(house, frame, colour):
    """The members of the exterior walls and the roof, without the clutter inside: those facing the viewer as
    colour gives them, the far ones faint."""
    shell = {w.id for w in house.walls if w.role == "exterior"} | {r.id for r in house.roofs}
    near = facing(house)
    return [(m.points, *(colour(m) if m.surface in near or colour(m)[0] == RED else ("#fff", "#d4d4d0", 0.25)), True,
             m.panel or m.surface) for m in frame.members if m.surface in shell]


# ---------------------------------------------------------------- pieces

def box(x, y, w, h, title, sub=""):
    return (f'<rect class="box" x="{x}" y="{y}" width="{w}" height="{h}"/>'
            f'<text class="title" x="{x + 12}" y="{y + h - (26 if sub else 12)}">{title}</text>'
            + (f'<text class="sub" x="{x + 12}" y="{y + h - 10}">{sub}</text>' if sub else ""))


def arrow(d, label="", lx=0, ly=0, anchor="middle"):
    return (f'<path class="arrow" d="{d}" marker-end="url(#head)"/>'
            + (f'<text class="label" x="{lx}" y="{ly}" text-anchor="{anchor}">{label}</text>' if label else ""))


def progress(run):
    val = [Path(h).stem for h in json.loads((run / "config.json").read_text())["val"]]
    best, out = math.inf, []
    for line in (run / "candidates.jsonl").read_text().splitlines():
        best = min(best, sum(json.loads(line)["scores"][h][0] for h in val))
        out.append(best)
    return out


def rule_list(x, y, rules, n):
    return "".join(f'<text class="mono" x="{x}" y="{y + i * 14}">{r.__name__}<tspan fill="{GREY}"> {r.match}</tspan></text>'
                   for i, r in enumerate(rules[:n])) + (f'<text class="sub" x="{x}" y="{y + n * 14}">+ {len(rules) - n} more</text>'
                                                         if len(rules) > n else "")


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


def figure():
    house = House.load(ROOT / "data" / "houses" / f"{HOUSE}.json")
    framed = build(ROOT / "grammars" / GRAMMAR, house)
    report = verify(house, framed)
    faulty = {mid for f in report.faults for mid in f.members}
    curve = progress(ROOT / "runs" / RUN)
    rules = load_rules(ROOT / "grammars" / GRAMMAR)
    shell = {w.id for w in house.walls if w.role == "exterior"} | {r.id for r in house.roofs}
    near = facing(house)

    # a grid: house and output as full-height columns; the proposer and the search above the grammar, frame
    # and verifier
    top, row, bottom = 34, 216, 410             # the top row's top, the bottom row's top, both rows' bottom
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
    o.append(box(gx, top, fx + fw - gx, 140, "Proposer", "LLM"))
    diff = [(" @rule(62, match=\"opening\")", INK), (" def header(s, o):", INK), ("-   s.place(\"2x8\", ...)", RED),
            ("+   n = 3 if s.load(o.u0, o.u1).sum > 4000 else 2", "#2f8a4a"),
            ("+   for i in range(n):", "#2f8a4a"), ("+       s.place(\"2x10\", ...)", "#2f8a4a")]
    o += [f'<text class="mono" x="{gx + 12}" y="{top + 20 + i * 14}" xml:space="preserve" style="fill:{c};white-space:pre">{t}</text>'
          for i, (t, c) in enumerate(diff)]
    o.append(box(vx, top, vw, 140, "Search", "keeps improvements"))
    cx, cy, cw, ch = vx + 44, top + 14, vw - 58, 66
    lo, hi = math.log10(min(curve)), math.log10(curve[0])
    px = lambda i: cx + cw * i / (len(curve) - 1)
    py = lambda v: cy + ch * (hi - math.log10(v)) / (hi - lo)
    o += [f'<path d="M{cx} {cy}V{cy + ch}H{cx + cw}" fill="none" stroke="{LINE}"/>',
          f'<text class="sub" x="{cx - 4}" y="{cy + 8}" text-anchor="end">{curve[0]:,}</text>',
          f'<text class="sub" x="{cx - 4}" y="{cy + ch}" text-anchor="end">{curve[-1]:,}</text>',
          f'<text class="sub" x="{cx}" y="{cy + ch + 12}">hard faults</text>',
          f'<path d="{"".join(("L" if i else "M") + f"{px(i):.1f} {py(v):.1f}" for i, v in enumerate(curve))}" fill="none" stroke="{INK}" stroke-width="1.4"/>']

    rh = bottom - row
    o += [box(gx, row, gw, rh, "Grammar", "match → action"), rule_list(gx + 12, row + 20, rules, 8),
          box(fx, row, fw, rh, "Frame", f"{len(framed.members):,} members"),
          drawing(members(house, framed, lambda m: ("#fff", "#4a4a47", 0.25)), fx + 10, row + 10, fw - 20, 118),
          box(vx, row, vw, rh, "Verifier", f"{len(report.faults)} faults"),
          drawing(members(house, framed, lambda m: (RED, "#7a1a15", 0.5) if m.id in faulty else ("#f4f4f2", "#b8b8b5", 0.3)),
                  vx + 10, row + 10, vw - 20, 118)]

    # output: the frame as the prefab panels it is built in, pulled apart
    panel_shapes = [(pts, "#fff", "#4a4a47" if m.surface in near else "#c4c4c0", 0.25, True, m.panel or m.surface)
                    for m, pts in exploded(framed, lambda m: m.surface in shell)]
    o += [box(ox, top, ow, bottom - top, "Evolved grammar", "frames as prefab panels"),
          drawing(panel_shapes, ox + 10, top + 60, ow - 20, 220)]

    # arrows: none cross
    o += [arrow(f"M{hx + hw} {mid}H{gx}"),
          arrow(f"M{gx + gw} {mid}H{fx}", "build", (gx + gw + fx) / 2, mid - 8),
          arrow(f"M{fx + fw} {mid}H{vx}"),
          arrow(f"M{vx + vw} {mid}H{ox}"),
          arrow(f"M{vx + vw / 2} {row}V{top + 140}", "score", vx + vw / 2 + 6, row - 30, "start"),
          arrow(f"M{vx} {top + 70}H{fx + fw}", "parent", (vx + fx + fw) / 2, top + 62),
          arrow(f"M{gx + gw / 2} {top + 140}V{row}", "edit", gx + gw / 2 + 6, row - 30, "start"),
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
