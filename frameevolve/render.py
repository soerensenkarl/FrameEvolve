"""Pictures of a frame: one elevation per wall, and an axonometric view. Members are coloured by rule."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402
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
    """Each wall seen from outside, in its own u, v coordinates. Red hatching: sheathing without backing.
    marks: (wall id, u, v, label) drawn as red crosses, for faults."""
    col = colours(frame)
    span = max(w.length for w in house.walls)
    rows = [14 * (w.height + 12) / (span + 12) + 0.5 for w in house.walls]
    fig, axes = plt.subplots(len(house.walls), 1, figsize=(14, sum(rows) + 0.6),
                             gridspec_kw={"height_ratios": rows})
    for ax, wall in zip(axes, house.walls):
        L, H = wall.length, wall.height
        ax.add_patch(Rectangle((0, 0), L, H, fill=False, ec="0.75", lw=0.6))
        for m in frame.members:
            b = wall.local_box(m.box)
            if m.surface == wall.id:
                ax.add_patch(Rectangle((b.lo[0], b.lo[1]), b.hi[0] - b.lo[0], b.hi[1] - b.lo[1],
                                       fc=col[m.rule], ec="k", lw=0.3))
            elif abs(b.lo[2]) <= EPS and b.hi[0] > EPS and b.lo[0] < L - EPS:
                ax.add_patch(Rectangle((b.lo[0], b.lo[1]), b.hi[0] - b.lo[0], b.hi[1] - b.lo[1],
                                       fc="0.85", ec="0.5", lw=0.3))
        for o in wall.openings:
            ax.add_patch(Rectangle((o.u0, o.v0), o.width, o.height, fill=False, ec="0.3", ls="--", lw=0.8))
            ax.text((o.u0 + o.u1) / 2, (o.v0 + o.v1) / 2, o.id, ha="center", va="center", fontsize=7, color="0.3")
        for g in surface.gaps(wall, frame.members):
            ax.add_patch(Rectangle((g.u0, g.v0), g.u1 - g.u0, g.v1 - g.v0, fill=False, ec="red",
                                   hatch="////", lw=0.6))
        for wid, u, v, label in marks:
            if wid == wall.id:
                ax.plot(u, v, "x", color="red", ms=8, mew=2)
                ax.text(u, v + 2.5, label, color="red", fontsize=7, ha="center")
        ax.set_xlim(-6, span + 6)
        ax.set_ylim(-6, H + 6)
        ax.set_aspect("equal")
        ax.set_title(f"{wall.id}  {ftin(L)} x {ftin(H)}  (seen from outside, start on the left; axes in inches)",
                     loc="left", fontsize=9)
        ax.tick_params(labelsize=7)
    axes[0].legend(handles=[Patch(fc=c, ec="k", label=r) for r, c in col.items()], fontsize=7,
                   loc="lower left", bbox_to_anchor=(0, 1.15), ncol=min(len(col), 6), frameon=False)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def axonometric(house: House, frame: Frame, path, elev: float = 28, azim: float = -58) -> None:
    col = colours(frame)
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(projection="3d")
    faces, colors = [], []
    for m in frame.members:
        (x0, y0, z0), (x1, y1, z1) = m.box.lo, m.box.hi
        c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        for f in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4)):
            faces.append([c[i] for i in f])
            colors.append(col[m.rule])
    ax.add_collection3d(Poly3DCollection(faces, facecolors=colors, edgecolors="k", linewidths=0.1))
    lo = [min(m.box.lo[k] for m in frame.members) for k in range(3)] if frame.members else [0, 0, 0]
    hi = [max(m.box.hi[k] for m in frame.members) for k in range(3)] if frame.members else [1, 1, 1]
    ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect([max(hi[k] - lo[k], 1) for k in range(3)])
    ax.view_init(elev, azim)
    ax.set_axis_off()
    ax.legend(handles=[Patch(fc=c, ec="k", label=r) for r, c in col.items()], fontsize=8, loc="upper left")
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
