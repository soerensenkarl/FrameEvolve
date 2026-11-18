"""The report's overview figure: inputs, the loop, the output, in the plain style of the report's other figures
(grey surfaces, black members, red for what matters) and drawn from the real geometry: a house as the builder
gets it, framed by a grammar early in a run, its faults as the verifier finds them, and framed by the run's best.
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

HOUSE, RUN, EARLY = "h008", "seed1", "c001"   # the house; the run; its grammar shown mid-loop
W, H = 1140, 460
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
    """Shapes [(world points, fill, stroke, stroke width, as hull)] drawn far to near, fitted in w x h at x, y;
    then arrows [(world from, world to)] over them, in red: the loads."""
    shapes = sorted(shapes, key=lambda s: depth(s[0]))
    flat = [[proj(p) for p in s[0]] for s in shapes]
    lines = [(proj(a), proj(b)) for a, b in arrows]
    xs = [p[0] for ps in flat for p in ps] + [p[0] for ab in lines for p in ab]
    ys = [p[1] for ps in flat for p in ps] + [p[1] for ab in lines for p in ab]
    k = min(w / (max(xs) - min(xs)), h / (max(ys) - min(ys)))
    ox = x + (w - (max(xs) - min(xs)) * k) / 2 - min(xs) * k
    oy = y + (h - (max(ys) - min(ys)) * k) / 2 - min(ys) * k
    out = []
    for (_, fill, stroke, sw, as_hull), ps in zip(shapes, flat):
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
    return [(m.points, *(colour(m) if m.surface in near or colour(m)[0] == RED else ("#fff", "#d4d4d0", 0.25)), True)
            for m in frame.members if m.surface in shell]


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


def best_grammar(run):
    val = [Path(h).stem for h in json.loads((run / "config.json").read_text())["val"]]
    cands = [json.loads(line) for line in (run / "candidates.jsonl").read_text().splitlines()]
    best = min(cands, key=lambda c: tuple(sum(c["scores"][h][k] for h in val) for k in range(3)))
    return run / "grammars" / f"{best['id']}.py"


# ---------------------------------------------------------------- the figure

def rule_list(x, y, rules, n):
    return "".join(f'<text class="mono" x="{x}" y="{y + i * 14}">{r.__name__}<tspan fill="{GREY}"> {r.match}</tspan></text>'
                   for i, r in enumerate(rules[:n])) + (f'<text class="sub" x="{x}" y="{y + n * 14}">+ {len(rules) - n} more</text>'
                                                         if len(rules) > n else "")


def figure():
    house = House.load(ROOT / "data" / "houses" / f"{HOUSE}.json")
    run = ROOT / "runs" / RUN
    seed, early, best = ROOT / "grammars" / "seed.py", run / "grammars" / f"{EARLY}.py", best_grammar(run)
    framed = build(early, house)
    report = verify(house, framed)
    faulty = {mid for f in report.faults for mid in f.members}
    evolved = build(best, house)
    final = verify(house, evolved)
    curve = progress(run)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">', f"<style>{CSS}</style>",
         f'<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" '
         f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{INK}"/></marker>'
         f'<marker id="load" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" '
         f'orient="auto"><path d="M0 0L10 5L0 10z" fill="{RED}"/></marker></defs>',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         '<text class="col" x="20" y="18">INPUTS</text>', '<text class="col" x="236" y="18">LOOP</text>',
         '<text class="col" x="960" y="18">OUTPUT</text>']

    # inputs: the seed grammar above, the house below
    seed_rules = load_rules(seed)
    o += [box(20, 28, 186, 180, "Seed grammar", f"{len(seed_rules)} rules"), rule_list(32, 48, seed_rules, 8)]
    o += [box(20, 226, 186, 210, "House", "surfaces and loads"), drawing(surfaces(house), 34, 236, 158, 122, loads(house))]

    # the loop: proposer and search above, the deterministic part below
    o += ['<rect class="env" x="236" y="226" width="704" height="224"/>',
          '<text class="envlabel" x="930" y="242" text-anchor="end">Deterministic</text>']
    o.append(box(320, 28, 336, 160, "Proposer", "LLM"))
    diff = [(" @rule(62, match=\"opening\")", INK), (" def header(s, o):", INK), ("-   s.place(\"2x8\", ...)", RED),
            ("+   n = 3 if s.load(o.u0, o.u1).sum > 4000 else 2", "#2f8a4a"),
            ("+   for i in range(n):", "#2f8a4a"), ("+       s.place(\"2x10\", ...)", "#2f8a4a")]
    o += [f'<text class="mono" x="332" y="{50 + i * 15}" xml:space="preserve" style="fill:{c};white-space:pre">{t}</text>'
          for i, (t, c) in enumerate(diff)]

    o.append(box(710, 28, 230, 160, "Search", "keeps improvements"))
    cx, cy, cw, ch = 752, 42, 172, 86
    lo, hi = math.log10(min(curve)), math.log10(curve[0])
    px = lambda i: cx + cw * i / (len(curve) - 1)
    py = lambda v: cy + ch * (hi - math.log10(v)) / (hi - lo)
    o += [f'<path d="M{cx} {cy}V{cy + ch}H{cx + cw}" fill="none" stroke="{LINE}"/>',
          f'<text class="sub" x="{cx - 4}" y="{cy + 8}" text-anchor="end">{curve[0]:,}</text>',
          f'<text class="sub" x="{cx - 4}" y="{cy + ch}" text-anchor="end">{curve[-1]:,}</text>',
          f'<text class="sub" x="{cx}" y="{cy + ch + 13}">hard faults</text>',
          f'<path d="{"".join(("L" if i else "M") + f"{px(i):.1f} {py(v):.1f}" for i, v in enumerate(curve))}" fill="none" stroke="{INK}" stroke-width="1.4"/>']

    gy, gh = 252, 162
    rules = load_rules(early)
    o += [box(250, gy, 190, gh, "Grammar", "match → action"), rule_list(262, gy + 18, rules, 7)]
    o += [box(482, gy, 200, gh, "Frame", f"{len(framed.members):,} members"),
          drawing(members(house, framed, lambda m: ("#fff", "#4a4a47", 0.25)), 494, gy + 8, 176, 104),
          box(724, gy, 200, gh, "Verifier", f"{len(report.faults)} faults"),
          drawing(members(house, framed, lambda m: (RED, "#7a1a15", 0.5) if m.id in faulty else ("#f4f4f2", "#b8b8b5", 0.3)),
                  736, gy + 8, 176, 104)]

    # arrows: none cross
    o += [arrow(f"M206 118H290V{gy}"),
          arrow(f"M440 {gy + 60}H482", "build", 461, gy + 52),
          arrow(f"M682 {gy + 60}H724"),
          arrow(f"M824 {gy}V188", "score", 830, 216, "start"),
          arrow("M710 100H656", "parent", 683, 92),
                    arrow(f"M400 188V{gy}", "edit", 406, 216, "start"),
          arrow(f"M206 400H222V{gy + gh + 22}H582V{gy + gh}", "surfaces", 452, gy + gh + 17, "start")]

    # output
    o += [arrow(f"M940 {gy + 60}H955"),
          box(955, 28, 170, 422, "Evolved grammar", "unseen houses"),
          f'<text class="sub" x="967" y="48">{len(load_rules(best))} rules</text>',
          drawing(members(house, evolved, lambda m: ("#fff", "#4a4a47", 0.25)), 965, 90, 150, 200),
                    f'<text class="sub" x="967" y="320">{len(evolved.panels())} panels</text>',
          f'<text class="sub" x="967" y="334">{final.hard} hard faults</text>',
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
