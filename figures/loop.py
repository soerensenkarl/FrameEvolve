"""The report's overview figure, schematic: inputs, the loop, the output. Writes loop.svg, loop.pdf and loop.png
beside this file (the PDF and PNG by headless Chrome).

    uv run python figures/loop.py
"""
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 1000, 400
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CSS = """
text { font-family: Helvetica, Arial, sans-serif; fill: #1a1a1a; }
.col { font-size: 12px; font-weight: 700; letter-spacing: .12em; }
.title { font-size: 13.5px; font-weight: 700; }
.sub { font-size: 10.5px; fill: #555; }
.note { font-size: 11px; fill: #333; }
.mono { font: 10.5px Menlo, Consolas, monospace; fill: #222; }
.box { fill: #fff; stroke: #333; stroke-width: 1.1; }
.env { fill: #f3f3f1; stroke: #c8c8c4; stroke-width: 1; }
.envlabel { font-size: 10.5px; font-style: italic; fill: #666; }
.arrow { fill: none; stroke: #333; stroke-width: 1.3; }
.arrow.loop { stroke: #2f6fdf; stroke-width: 1.6; }
.label { font-size: 11px; font-style: italic; fill: #333; }
.tim { fill: #d9b98c; stroke: #8a6a3e; stroke-width: .5; }
.surf { fill: #eef2f6; stroke: #6f8399; stroke-width: 1; }
.op { fill: #fff; stroke: #6f8399; stroke-width: 1; }
.ok { fill: #2f8a4a; } .bad { fill: #c8322b; }
.hollow { fill: #fff; stroke: #333; stroke-width: 1.2; }
"""


def wall(x, y, w, h, n=7, win=(0.42, 0.66)):
    """A framed wall panel: plates, studs, and, if win is given, a window with its header, sill and cripples."""
    t = 3
    out = [f'<rect class="tim" x="{x}" y="{y}" width="{w}" height="{t}"/>',
           f'<rect class="tim" x="{x}" y="{y + h - t}" width="{w}" height="{t}"/>']
    a, b = (x + w * win[0], x + w * win[1]) if win else (0, 0)
    for i in range(n + 1):
        sx = x + (w - t) * i / n
        if not (a - t < sx < b):
            out.append(f'<rect class="tim" x="{sx:.1f}" y="{y + t}" width="{t}" height="{h - 2 * t}"/>')
    if win:
        hy, sy, mx = y + h * 0.28, y + h * 0.62, (a + b) / 2 - t / 2
        out += [f'<rect class="tim" x="{a - t:.1f}" y="{y + t}" width="{t}" height="{h - 2 * t}"/>',
                f'<rect class="tim" x="{b:.1f}" y="{y + t}" width="{t}" height="{h - 2 * t}"/>',
                f'<rect class="tim" x="{a:.1f}" y="{hy:.1f}" width="{b - a:.1f}" height="{t * 1.8}"/>',
                f'<rect class="tim" x="{a:.1f}" y="{sy:.1f}" width="{b - a:.1f}" height="{t}"/>',
                f'<rect class="tim" x="{mx:.1f}" y="{y + t}" width="{t}" height="{hy - y - t:.1f}"/>',
                f'<rect class="tim" x="{mx:.1f}" y="{sy + t:.1f}" width="{t}" height="{y + h - 2 * t - sy:.1f}"/>']
    return "".join(out)


def box(x, y, w, h, title, sub=""):
    return (f'<rect class="box" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>'
            f'<text class="title" x="{x + w / 2}" y="{y + 20}" text-anchor="middle">{title}</text>'
            + (f'<text class="sub" x="{x + w / 2}" y="{y + h - 10}" text-anchor="middle">{sub}</text>' if sub else ""))


def lines(x, y, texts, cls="mono", step=16, anchor="start"):
    return "".join(f'<text class="{cls}" x="{x}" y="{y + i * step}" text-anchor="{anchor}">{t}</text>' for i, t in enumerate(texts))


def arrow(d, loop=False, label="", lx=0, ly=0, anchor="middle"):
    return (f'<path class="arrow{" loop" if loop else ""}" d="{d}" marker-end="url(#{"head-loop" if loop else "head"})"/>'
            + (f'<text class="label" x="{lx}" y="{ly}" text-anchor="{anchor}">{label}</text>' if label else ""))


def figure() -> str:
    head = lambda i, c, s: (f'<marker id="{i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="{s}" markerHeight="{s}" '
                            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{c}"/></marker>')
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">', f"<style>{CSS}</style>",
         f'<defs>{head("head", "#333", 7)}{head("head-loop", "#2f6fdf", 6.5)}</defs>', f'<rect width="{W}" height="{H}" fill="#fff"/>',
         '<text class="col" x="95" y="22" text-anchor="middle">INPUTS</text>',
         '<text class="col" x="495" y="22" text-anchor="middle">THE LOOP</text>',
         '<text class="col" x="910" y="22" text-anchor="middle">OUTPUT</text>']

    # inputs: a seed grammar of a few obvious rules, and a house as surfaces
    o += [box(20, 44, 150, 126, "Seed grammar", "a few obvious rules"),
          lines(36, 84, ["wall   → studs", "window → header", "floor  → joists", "roof   → rafters"])]
    o.append(box(20, 206, 150, 150, "House", "surfaces only, no timber"))
    hx, hy = 52, 236
    o += [f'<path class="surf" d="M{hx} {hy + 40}L{hx + 43} {hy + 8}L{hx + 86} {hy + 40}V{hy + 92}H{hx}Z"/>',
          f'<path class="surf" d="M{hx} {hy + 40}H{hx + 86}"/>',
          f'<rect class="op" x="{hx + 12}" y="{hy + 52}" width="16" height="16"/><rect class="op" x="{hx + 58}" y="{hy + 52}" width="16" height="16"/>',
          f'<rect class="op" x="{hx + 36}" y="{hy + 66}" width="14" height="26"/><rect class="op" x="{hx + 37}" y="{hy + 20}" width="12" height="12"/>']

    # the loop: proposer and search above, the deterministic part below
    o += ['<rect class="env" x="200" y="180" width="590" height="196" rx="10"/>',
          '<text class="envlabel" x="778" y="368" text-anchor="end">deterministic</text>',
          box(330, 44, 210, 100, "Proposer (LLM)", "the only LLM in the loop"),
          lines(435, 82, ["reads the faults, looks at the", "frames, tries variations, and", "edits the rules"], "note", 15, "middle"),
          box(600, 44, 170, 100, "Search", "keeps what improves")]
    pts = [(626, 70), (650, 94), (674, 102), (698, 107), (722, 110), (746, 111)]
    o += ['<path d="M620 66V118H752" fill="none" stroke="#999" stroke-width=".8"/>',
          f'<path d="{"".join(("L" if i else "M") + f"{x} {y}" for i, (x, y) in enumerate(pts))}" fill="none" stroke="#2f8a4a" stroke-width="1.6"/>']
    o += [f'<circle cx="{x}" cy="{y}" r="2.3" class="ok"/>' for x, y in pts]

    gy, bh = 214, 128
    o += [box(220, gy, 150, bh, "Grammar", "rules: match → action"),
          lines(236, gy + 46, ["wall   → studs", "window → header", "corner → studs", "load   → post"]),
          box(420, gy, 150, bh, "Frame", "members in prefab panels"), wall(438, gy + 34, 114, 70),
          box(620, gy, 150, bh, "Verifier", "score: (hard, soft, cost)")]
    for i, (q, ok) in enumerate([("can it stand?", True), ("will it hold?", True), ("does it meet code?", False),
                                 ("can it go up as panels?", True)]):
        y = gy + 46 + i * 17
        o.append(f'<circle cx="636" cy="{y - 4}" r="4.5" class="{"ok" if ok else "bad"}"/>'
                 f'<text x="636" y="{y - 1.5}" text-anchor="middle" style="font-size:8px;font-weight:700;fill:#fff">{"✓" if ok else "✕"}</text>'
                 f'<text class="note" x="646" y="{y}">{q}</text>')

    # arrows: the inputs in black, the loop in blue; none cross
    o += [arrow("M170 107H260V214"),
          arrow(f"M170 330H200V362H495V{gy + bh}", label="surfaces + loads", lx=300, ly=356),
          arrow(f"M370 {gy + 64}H420", True, "build", 395, gy + 56),
          arrow(f"M570 {gy + 64}H620", True),
          arrow(f"M695 {gy}V144", True, "the score", 701, 168, "start"),
          arrow("M600 94H540", True, "a parent", 570, 86),
          '<text class="label" x="570" y="110" text-anchor="middle">+ faults</text>',
          arrow(f"M350 144V{gy}", True, "an edit", 356, 168, "start")]

    # output: the evolved grammar, framing houses it never saw as prefab panels
    o += ['<path class="hollow" d="M797 270h18v-10l16 18-16 18v-10h-18z"/>',
          box(840, 180, 140, 196, "Evolved grammar", "on unseen houses"),
          lines(855, 216, ["wall   → studs", "window → header", "load   → post", "+ many more"], step=15),
          wall(854, 280, 54, 54, n=4, win=(0.3, 0.75)), wall(912, 280, 54, 54, n=4, win=None),
          '<text class="sub" x="910" y="350" text-anchor="middle">as prefab panels,</text>', "</svg>"]
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
