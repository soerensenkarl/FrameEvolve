"""Pictures of a frame: elevations of the surfaces with the most faults, and an axonometric view. Members are
coloured by rule; prefab panels are outlined and named."""
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


SITE = "built on site"
FAULTS = {"hard fault": (0.85, 0.2, 0.17, 1.0), "soft fault": (0.9, 0.55, 0.0, 1.0), "no fault": (0.75, 0.75, 0.75, 0.07)}


def key(m, by: str, faults: dict | None = None) -> str:
    """What a member is coloured by: its rule, its prefab panel, or whether it is in a fault (faults: member id ->
    True for a hard fault, False for a soft one)."""
    if by == "faults":
        f = (faults or {}).get(m.id)
        return "hard fault" if f is True else "soft fault" if f is False else "no fault"
    return (m.panel or SITE) if by == "panel" else m.rule


def colours(frame: Frame, by: str = "rule", faults: dict | None = None) -> dict:
    """A colour for each rule (or each panel, members built on site in grey; or each kind of fault, the members in
    none a faint ghost)."""
    if by == "faults":
        used = {key(m, by, faults) for m in frame.members}
        return {k: c for k, c in FAULTS.items() if k in used}
    names = sorted({key(m, by) for m in frame.members} - {SITE})
    cmap = plt.get_cmap("tab10" if len(names) <= 10 else "tab20")
    out = {r: cmap(i % cmap.N) for i, r in enumerate(names)}
    if any(key(m, by) == SITE for m in frame.members):
        out[SITE] = (0.82, 0.82, 0.82, 1.0)
    return out


SHOWN = 6   # surfaces in one picture: more, and each is too small to read once the picture is scaled to send


def elevations(house: House, frame: Frame, path, marks: list[tuple[str, float, float, str]] = (),
               only: list[str] = (), by: str = "rule", faults: dict | None = None) -> None:
    """The surfaces with the most faults (up to SHOWN, the rest in house order), two to a row: a wall seen from
    outside, a floor or roof plane from above, each in its own u, v. Red hatching: boards without backing.
    marks: (surface id, u, v, label) drawn as red crosses, for faults. Dashed blue: prefab panels. only: these
    surfaces instead. by: colour by "rule" or "panel"."""
    col = colours(frame, by, faults)
    every = [*house.walls, *[f for f in house.floors if f.role == "floor"], *house.roofs]
    count = {x.id: sum(1 for sid, *_ in marks if sid == x.id) for x in every}
    sides = [x for sid in only for x in every if x.id == sid][:SHOWN] or sorted(every, key=lambda x: -count[x.id])[:SHOWN]
    walls = {w.id: w for w in house.walls}
    rows = (len(sides) + 1) // 2
    fig, grid = plt.subplots(rows, 2, figsize=(16, 4.6 * rows), squeeze=False)
    axes = grid.flatten()
    for ax in axes[len(sides):]:
        ax.set_axis_off()
    for ax, x in zip(axes, sides):
        L, H = x.size
        ax.add_patch(Polygon(x.outline_uv, closed=True, fill=False, ec="0.75", lw=0.6))
        for m in frame.members:
            b = x.local_box(m)
            if m.surface == x.id:
                for poly in surface.outlines(x, m):
                    ax.add_patch(Polygon(poly, closed=True, fc=col[key(m, by, faults)], ec="k", lw=0.3))
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
        for name, ms in frame.panels().items():
            bs = [x.local_box(m) for m in ms if m.surface == x.id]
            if bs:
                u0, v0 = min(b.lo[0] for b in bs), min(b.lo[1] for b in bs)
                u1, v1 = max(b.hi[0] for b in bs), max(b.hi[1] for b in bs)
                ax.add_patch(Rectangle((u0, v0), u1 - u0, v1 - v0, fill=False, ec="#1f5fbf", ls="--", lw=1.2))
                ax.text(u0 + 2, v1 + 2, name, color="#1f5fbf", fontsize=7)
        ax.set_xlim(-6, L + 6)
        ax.set_ylim(-6, H + 10)
        ax.set_aspect("equal")
        seen = "from outside, start on the left" if x.id in walls else "from above"
        ax.set_title(f"{x.id}  {ftin(L)} x {ftin(H)}, {count[x.id]} faults marked (seen {seen}; inches)", loc="left",
                     fontsize=9)
        ax.tick_params(labelsize=7)
    fig.legend(handles=[Patch(fc=c, ec="k", label=r) for r, c in col.items()], fontsize=7,
               loc="lower center", ncol=min(len(col), 7), frameon=False)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def axonometric(house: House, frame: Frame, path, elev: float = 28, azim: float = -58,
                marks: list[tuple[float, float, float, str]] = (), views: list[tuple[float, float]] = (),
                by: str = "rule", faults: dict | None = None) -> None:
    """The whole frame in 3D, coloured by rule (or panel, or fault: see key). marks: (x, y, z, label) world points
    drawn as red crosses, for faults. views: (elevation, azimuth) pairs drawn side by side; one view from (elev,
    azim) if none given."""
    col = colours(frame, by, faults)
    views = list(views) or [(elev, azim)]
    fig = plt.figure(figsize=(10 * len(views), 8))
    faces, colors, edges = [], [], []
    for m in frame.members:
        k = key(m, by, faults)
        for piece in m.pieces:
            for _, _, pts in piece:
                if all(math.isfinite(c) for p in pts for c in p):
                    faces.append(pts)
                    colors.append(col[k])
                    edges.append((0.4, 0.4, 0.4, 0.12) if k == "no fault" else (0, 0, 0, 1))
    ok = [m for m in frame.members if all(math.isfinite(c) for c in (*m.box.lo, *m.box.hi))]
    lo = [min(m.box.lo[k] for m in ok) for k in range(3)] if ok else [0, 0, 0]
    hi = [max(m.box.hi[k] for m in ok) for k in range(3)] if ok else [1, 1, 1]
    for i, (e, a) in enumerate(views):
        ax = fig.add_subplot(1, len(views), i + 1, projection="3d")
        ax.computed_zorder = False           # fault crosses stay on top of the framing that hides them
        ax.add_collection3d(Poly3DCollection(faces, facecolors=colors, edgecolors=edges, linewidths=0.1), autolim=False)
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
