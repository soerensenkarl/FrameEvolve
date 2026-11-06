"""Pictures of a frame: one elevation per wall, and an axonometric view. Members are coloured by rule."""
from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch, Polygon, Rectangle  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

from frameevolve import surface  # noqa: E402
from frameevolve.geometry import EPS  # noqa: E402
from frameevolve.model import Frame, House  # noqa: E402
from frameevolve.units import ftin  # noqa: E402


def colours(frame: Frame) -> dict:
    rules = sorted({m.rule for m in frame.members})
    cmap = plt.get_cmap("tab10" if len(rules) <= 10 else "tab20")
    return {r: cmap(i % cmap.N) for i, r in enumerate(rules)}


def elevations(house: House, frame: Frame, path, marks: list[tuple[str, float, float, str]] = ()) -> None:
    """Each wall seen from outside, and each roof plane from above, in its own u, v coordinates. Red hatching:
    sheathing without backing. marks: (surface id, u, v, label) drawn as red crosses, for faults."""
    col = colours(frame)
    sides = [*house.walls, *house.roofs]
    walls = {w.id: w for w in house.walls}
    span = max(x.size[0] for x in sides)
    rows = [14 * (x.size[1] + 12) / (span + 12) + 0.5 for x in sides]
    fig, axes = plt.subplots(len(sides), 1, figsize=(14, sum(rows) + 0.6),
                             gridspec_kw={"height_ratios": rows})
    for ax, x in zip(axes, sides):
        L, H = x.size
        ax.add_patch(Polygon(x.outline_uv, closed=True, fill=False, ec="0.75", lw=0.6))
        for m in frame.members:
            b = x.local_box(m)
            if m.surface == x.id:
                for poly in surface.outlines(x, m):
                    ax.add_patch(Polygon(poly, closed=True, fc=col[m.rule], ec="k", lw=0.3))
            elif abs(b.lo[2]) <= EPS and b.hi[0] > EPS and b.lo[0] < L - EPS and x.square(m):
                ax.add_patch(Rectangle((b.lo[0], b.lo[1]), b.hi[0] - b.lo[0], b.hi[1] - b.lo[1],
                                       fc="0.85", ec="0.5", lw=0.3))
        for o in x.openings:
            ax.add_patch(Rectangle((o.u0, o.v0), o.width, o.height, fill=False, ec="0.3", ls="--", lw=0.8))
            ax.text((o.u0 + o.u1) / 2, (o.v0 + o.v1) / 2, o.id, ha="center", va="center", fontsize=7, color="0.3")
        for g in surface.gaps(x, frame.members, walls=walls):
            ax.add_patch(Rectangle((g.u0, g.v0), g.u1 - g.u0, g.v1 - g.v0, fill=False, ec="red",
                                   hatch="////", lw=0.6))
        for sid, u, v, label in marks:
            if sid == x.id:
                ax.plot(u, v, "x", color="red", ms=8, mew=2)
                ax.text(u, v + 2.5, label, color="red", fontsize=7, ha="center")
        ax.set_xlim(-6, span + 6)
        ax.set_ylim(-6, H + 6)
        ax.set_aspect("equal")
        seen = "from above, eave at the bottom" if x in house.roofs else "from outside, start on the left"
        ax.set_title(f"{x.id}  {ftin(L)} x {ftin(H)}  (seen {seen}; axes in inches)", loc="left", fontsize=9)
        ax.tick_params(labelsize=7)
    axes[0].legend(handles=[Patch(fc=c, ec="k", label=r) for r, c in col.items()], fontsize=7,
                   loc="lower left", bbox_to_anchor=(0, 1.15), ncol=min(len(col), 6), frameon=False)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def axonometric(house: House, frame: Frame, path, elev: float = 28, azim: float = -58,
                marks: list[tuple[float, float, float, str]] = (), views: list[tuple[float, float]] = ()) -> None:
    """The whole frame in 3D, coloured by rule. marks: (x, y, z, label) world points drawn as red crosses, for
    faults. views: (elevation, azimuth) pairs drawn side by side; one view from (elev, azim) if none given."""
    col = colours(frame)
    views = list(views) or [(elev, azim)]
    fig = plt.figure(figsize=(10 * len(views), 8))
    faces, colors = [], []
    for m in frame.members:
        for piece in m.pieces:
            for _, _, pts in piece:
                if all(math.isfinite(c) for p in pts for c in p):
                    faces.append(pts)
                    colors.append(col[m.rule])
    ok = [m for m in frame.members if all(math.isfinite(c) for c in (*m.box.lo, *m.box.hi))]
    lo = [min(m.box.lo[k] for m in ok) for k in range(3)] if ok else [0, 0, 0]
    hi = [max(m.box.hi[k] for m in ok) for k in range(3)] if ok else [1, 1, 1]
    for i, (e, a) in enumerate(views):
        ax = fig.add_subplot(1, len(views), i + 1, projection="3d")
        ax.computed_zorder = False           # fault crosses stay on top of the framing that hides them
        ax.add_collection3d(Poly3DCollection(faces, facecolors=colors, edgecolors="k", linewidths=0.1), autolim=False)
        if marks:
            xs, ys, zs, _ = zip(*marks)
            ax.scatter(xs, ys, zs, marker="x", s=160, linewidths=3, c="red", depthshade=False, zorder=10)
        ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_zlim(lo[2], hi[2])
        ax.set_box_aspect([max(hi[k] - lo[k], 1) for k in range(3)])
        ax.view_init(e, a)
        ax.set_axis_off()
    handles = [Patch(fc=c, ec="k", label=r) for r, c in col.items()]
    if len(views) == 1:
        fig.axes[0].legend(handles=handles, fontsize=8, loc="upper left")
    else:
        fig.legend(handles=handles, fontsize=9, loc="lower center", ncol=min(len(handles), 7), frameon=False)
    fig.savefig(path, dpi=110 if len(views) == 1 else 80, bbox_inches="tight")
    plt.close(fig)
