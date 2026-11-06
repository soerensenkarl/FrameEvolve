// The Surfaces tab: each wall as an elevation, each floor, ceiling and roof plane as a plan, grouped by
// storey, with the members on it, the step's target and a chosen fault's evidence; the storey filter in the
// view bar; the caption over the view while stepping. The SVG helpers here also draw the rule demo.
import { $, esc, ftin, pill, oneLine, SURF, PAST, REL, FACE, st, finished, current, trigger, stepNo, present,
  placedNow, goneNow, matchedMember, runsMode, surfaceList, isFloor, isWall, kindName, faceName, listed, isActive,
  memberColour } from "./state.js";
import { select } from "./app.js";
import { related, look3d, otherEnd, isLine, toLocal } from "./view3d.js";
import { evidence, chosenFault } from "./inspect.js";

// ---------------------------------------------------------------- pieces of a surface drawing, in its u (right) and v (up)

// a member on its surface: its outline polygons where it is cut or at an angle, else its rectangle u0..u1, v0..v1
export const memberSvg = (b, attrs, title) => (b.poly
  ? `<path ${attrs} d="${b.poly.map((p) => `M${p.map(([u, v]) => `${u} ${-v}`).join("L")}z`).join("")}"><title>${title}</title></path>`
  : `<rect ${attrs} x="${b.u0}" y="${-b.v1}" width="${b.u1 - b.u0}" height="${b.v1 - b.v0}"><title>${title}</title></rect>`);
export const outlinePath = (outline) => `M${outline.map(([u, v]) => `${u} ${-v}`).join("L")}z`;
export const holesPath = (openings) => openings.map((o) => `M${o.u0} ${-o.v1}h${o.u1 - o.u0}v${o.v1 - o.v0}h${o.u0 - o.u1}z`).join("");
// the surface's plane with its openings cut out
export const surfPath = (s, opacity, cls = "") =>
  `<path ${cls ? `class="${cls}" ` : ""}d="${outlinePath(s.outline)}${holesPath(s.openings)}" fill="${SURF}" fill-opacity="${opacity}" fill-rule="evenodd"/>`;
export const openingRect = (o) => `<rect class="op" x="${o.u0}" y="${-o.v1}" width="${o.u1 - o.u0}" height="${o.v1 - o.v0}"/>`;
// a wall under a floor (class "under", faint) or standing on it ("onit", dashed): its line and its framing depth
export function bearerPoly(b, cls, title) {
  const [sx, sy] = b.side, d = b.depth;
  const pts = [b.a, b.b, [b.b[0] + sx * d, b.b[1] + sy * d], [b.a[0] + sx * d, b.a[1] + sy * d]];
  return `<polygon class="${cls}" points="${pts.map(([u, v]) => `${u},${-v}`).join(" ")}">${title ? `<title>${title}</title>` : ""}</polygon>`;
}
// a partition meeting this wall: a line at its u, its name above the wall
export const teeSvg = (t, V, size, lift) => `<g class="tee"><title>${esc(t.wall)} meets this wall here</title>
    <line x1="${t.u}" x2="${t.u}" y1="0" y2="${-V}"/><text x="${t.u}" y="${-V - lift}" text-anchor="middle" font-size="${size}">${esc(t.wall)}</text></g>`;
// what a rule matched, as a line or a rectangle in the rule's colour
export const targetShape = (t, c, cls) => (isLine(t)
  ? `<line class="${cls}" x1="${t.u0}" x2="${t.u1}" y1="${-t.v0}" y2="${-t.v1}" stroke="${c}"/>`
  : `<rect class="${cls}" x="${t.u0}" y="${-t.v1}" width="${t.u1 - t.u0}" height="${t.v1 - t.v0}" stroke="${c}" fill="${c}"/>`);

// ---------------------------------------------------------------- one surface, with everything on it

function surfaceSvg(s, span, rel) {
  // one surface drawn in its own u (right) and v (up): an elevation of a wall, a plan of a floor from above
  const [U, V] = s.size;
  const k = span / 1000;   // drawing unit: sizes below scale with the drawing
  const pad = 20 * k;
  const done = finished();
  const showFaults = $("#showFaults").checked && done && st.fault == null;
  const surfOp = st.at === 0 ? 0.42 : done ? 0.12 : 0.2;
  const own = st.data.members.filter((m) => m.surface === s.id && !st.hidden.has(m.rule) && (present(m.id) || goneNow(m.id)));
  const rects = own.map((m) => {
    const [lo, hi] = m.local;
    const r = rel?.get(m.id);
    const gone = goneNow(m.id);
    const isNow = placedNow(m.id);
    const hit = matchedMember(m.id);
    const cls = ["m", rel && !r ? "dim" : "", r === "self" ? "sel" : "", showFaults && st.faulty.has(m.id) ? "fault" : "",
      isNow || (hit && trigger()) ? "now" : "", gone ? "gone" : ""].join(" ");
    return memberSvg({ u0: lo[0], v0: lo[1], u1: hi[0], v1: hi[1], poly: m.poly }, `class="${cls}" data-id="${m.id}" fill="${memberColour(m, r, "none")}"`,
      `${m.id} ${esc(m.role || "")}, ${esc(m.rule)}, ${esc(m.section)}${gone ? ", removed at this step" : ""}`);
  }).join("");
  // around it: other walls' members at a wall's face; the walls under a floor (faint) and on it (dashed)
  const nbs = isFloor(s) ? ["bearers", "loads"].map((key) => s[key].map((b) =>
    bearerPoly(b, key === "bearers" ? "under" : "onit", `${esc(b.wall)} ${key === "bearers" ? "under" : "on"} this floor`)).join("")).join("")
    : isWall(s) ? s.neighbours.filter((b) => present(b.id)).map((b) =>
    `<rect class="nb" data-id="${b.id}" x="${b.lo[0]}" y="${-b.hi[1]}" width="${b.hi[0] - b.lo[0]}" height="${b.hi[1] - b.lo[1]}"><title>${b.id}, on another wall</title></rect>`).join("")
    : "";   // a roof plane: nothing around it
  const surf = $("#showSurfaces").checked ? surfPath(s, surfOp, "surf") : "";
  const ops = s.openings.map((o) => openingRect(o) +
    `<text x="${(o.u0 + o.u1) / 2}" y="${-(o.v0 + o.v1) / 2}" text-anchor="middle" font-size="${17 * k}">${esc(o.id)} ${esc(o.kind)}</text>` +
    `<text x="${(o.u0 + o.u1) / 2}" y="${-(o.v0 + o.v1) / 2 + 20 * k}" text-anchor="middle" font-size="${15 * k}">${ftin(o.u1 - o.u0)} x ${ftin(o.v1 - o.v0)}</text>`).join("");
  const a = 7 * k;
  const only = st.only;
  const marks = showFaults ? st.data.faults.filter((f) => f.surface === s.id && f.u != null && f.check !== "backing" && (!only || f.check === only)).map((f) =>
    `<g class="mark ${f.hard ? "" : "soft"}"><title>${esc(f.message)}</title>
      <line x1="${f.u - a}" y1="${-f.v - a}" x2="${f.u + a}" y2="${-f.v + a}"/><line x1="${f.u - a}" y1="${-f.v + a}" x2="${f.u + a}" y2="${-f.v - a}"/></g>`).join("") : "";
  const gaps = showFaults && (!only || only === "backing") ? s.gaps.map((g) =>
    `<rect class="gap" x="${g.u0}" y="${-g.v1}" width="${g.u1 - g.u0}" height="${g.v1 - g.v0}" stroke="${FACE[g.face]}" fill="url(#hatch-${g.face}-${s.id})"><title>${faceName(s, g.face)}: ${g.kind === "edge" ? "a board edge" : "a board"} ${ftin(g.u1 - g.u0)} by ${ftin(g.v1 - g.v0)} with nothing behind it</title></rect>`).join("") : "";
  const tees = isWall(s) ? s.tees.map((t) => teeSvg(t, V, 16 * k, 5 * k)).join("") : "";
  const hatch = (face, angle) => `<pattern id="hatch-${face}-${s.id}" patternUnits="userSpaceOnUse" width="${8 * k}" height="${8 * k}" patternTransform="rotate(${angle})">
      <line x1="0" y1="0" x2="0" y2="${8 * k}" stroke="${FACE[face]}" stroke-width="${1.4 * k}"/></pattern>`;
  return `<svg viewBox="${-pad} ${-(V + pad)} ${Math.max(span, U) + 2 * pad} ${V + 2 * pad}">
      <defs>${hatch("outer", 45)}${hatch("inner", -45)}</defs>
      ${surf}<path class="outline" d="${outlinePath(s.outline)}"/>
      ${nbs}${rects}${tees}${ops}${gaps}${marks}${isActive(s.id) ? targetSvg(s, k) : ""}${evidenceSvg(s, k)}
    </svg>`;
}

function surfaceCaption(s) {
  const [U, V] = s.size;
  if (s.kind === "roof") {
    return `<b>${s.id}</b> roof plane over storey ${s.storey}, ${ftin(U)} along the eave, ${ftin(V)} up the slope,
      pitch ${s.pitch} in 12; seen from above, eave at the bottom.`;
  }
  if (isFloor(s)) {
    return `<b>${s.id}</b> ${kindName(s)} of storey ${s.storey}, ${ftin(U)} by ${ftin(V)}, seen from above, x to the right.
      On ${s.bearers.length} walls below (faint)${s.loads.length ? `; ${s.loads.length} walls stand on it (dashed)` : ""}.`;
  }
  const gable = V > s.height + 0.01 ? ` (${ftin(V)} at the gable peak)` : "";
  return `<b>${s.id}</b> ${s.role === "interior" ? "partition, " : ""}${ftin(U)} long, ${ftin(s.height)} high${gable},
    seen from ${s.role === "interior" ? "its face side" : "outside"}, its start on the left.
    Meets ${s.start_meets ?? "nothing"} at its start, ${s.end_meets ?? "nothing"} at its end.`;
}

export function renderElev() {
  const el = $("#elev");
  if (!st.data) return;
  const list = surfaceList().filter((s) => listed(s.id));
  if (!list.length) {
    el.innerHTML = `<p class="empty">Nothing on this storey.</p>`;
    return;
  }
  const keep = el.scrollTop;
  const rel = related();
  const span = Math.max(...surfaceList().map((s) => s.size[0]));
  const cur = current();
  const levels = [...new Set(list.map((s) => s.storey))].sort();
  const rank = (s) => (s.role === "ceiling" ? 2 : { floor: 0, wall: 1, roof: 3 }[s.kind]);   // floor, walls, ceiling, roof
  el.innerHTML = levels.map((n) => `<h3 class="storey">Storey ${n}</h3>` + list.filter((s) => s.storey === n)
    .sort((a, b) => rank(a) - rank(b)).map((s) => {
      const active = isActive(s.id);
      const tag = !active ? "" : `<span class="steptag">${pill(cur.rule, st.colors[cur.rule])} ${cur.surface !== s.id ? `matched ${esc(cur.match)} on ${esc(cur.surface)}, which meets this one`
        : trigger() ? `matched ${esc(cur.match)}` : `placed ${cur.placed.length} here`} at step ${stepNo()}</span>`;
      return `<div class="surface ${isWall(s) ? "" : s.kind} ${active ? "active" : ""} ${cur && !active ? "rest" : ""}" id="surface-${s.id}">
        <div class="cap">${surfaceCaption(s)} ${tag}</div>${surfaceSvg(s, span, rel)}</div>`;
    }).join("")).join("") + `<div class="legend"><span style="--c:${SURF}">surface (the input)</span>
     <span style="--c:${PAST}">placed by earlier steps</span>
     <span style="--c:${REL.bears}">the selection bears on it</span>
     <span style="--c:${REL.carries}">it bears on the selection</span><span style="--c:${REL.side}">beside the selection</span>
     <span style="--c:#e4e2dd">member of another surface</span>
     <span style="--c:${FACE.outer}">no backing: outside face, subfloor, ceiling, roof</span><span style="--c:${FACE.inner}">no backing: inside face, ceiling under a floor</span></div>`;
  el.scrollTop = keep;
}

function targetSvg(s, k) {
  // what the current step's rule matched on this surface: filled at the trigger, outlined at the output
  const cur = current(), t = cur.target;
  if (!t || t.kind === "member") return "";
  const c = st.colors[cur.rule], cls = `target ${trigger() ? "trig" : "out"}`;
  const at = t.surface === s.id ? t : otherEnd(t)?.surface === s.id ? otherEnd(t) : null;
  if (!at) return "";
  const face = !isLine(at) && t.face === "inner" ? `<text x="${(at.u0 + at.u1) / 2}" y="${-at.v1 - 4 * k}" text-anchor="middle" font-size="${15 * k}">${faceName(s, "inner")}</text>` : "";
  return targetShape(at, c, cls) + face;
}

function evidenceSvg(s, k) {
  const f = chosenFault();
  if (!f || f.surface !== s.id) return "";
  const ev = evidence(f);
  let out = "";
  for (const d of ev.dims) {
    const [a, b] = [toLocal(s, d.a), toLocal(s, d.b)];
    out += `<g class="ev"><line x1="${a[0]}" y1="${-a[1]}" x2="${b[0]}" y2="${-b[1]}"/>
      <text x="${(a[0] + b[0]) / 2}" y="${-(a[1] + b[1]) / 2 - 5 * k}" text-anchor="middle" font-size="${17 * k}">${esc(d.text)}</text></g>`;
  }
  for (const bx of ev.boxes) {
    const pts = [0, 1].flatMap((i) => [0, 1].flatMap((j) => [0, 1].map((l) => toLocal(s, [i ? bx.hi[0] : bx.lo[0], j ? bx.hi[1] : bx.lo[1], l ? bx.hi[2] : bx.lo[2]]))));
    const [u0, u1, v0, v1] = [Math.min(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[0])), Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[1]))];
    out += `<rect class="ev box" x="${u0}" y="${-v1}" width="${Math.max(u1 - u0, k)}" height="${Math.max(v1 - v0, k)}"/>`;
  }
  for (const r of ev.rects) {
    out += `<g class="ev"><rect x="${r.u0}" y="${-r.v1}" width="${r.u1 - r.u0}" height="${r.v1 - r.v0}"/>
      <text x="${(r.u0 + r.u1) / 2}" y="${-(r.v0 + r.v1) / 2}" text-anchor="middle" font-size="${18 * k}">${esc(r.text)}</text></g>`;
  }
  if (!out && f.u != null) out = `<circle class="ev" cx="${f.u}" cy="${-f.v}" r="${12 * k}"/>`;
  return out;
}

$("#elev").addEventListener("click", (e) => {
  const r = e.target.closest("[data-id]");
  select(r && st.byId[r.dataset.id] ? { kind: "member", id: r.dataset.id } : null);
});

export function scrollElevTo(sid, opts) {
  // bring a surface's drawing into view in the Surfaces tab, when that tab is showing
  if (sid && $("#elev").classList.contains("on")) document.getElementById(`surface-${sid}`)?.scrollIntoView(opts);
}

// ---------------------------------------------------------------- the storey filter in the view bar: All, 1, 2, 3

export function renderStoreys() {
  const n = Math.max(1, ...Object.values(st.level));
  if (st.storey > n) st.storey = 0;
  $("#storeys").innerHTML = n < 2 ? "" : ["All", ...Array.from({ length: n }, (_, i) => i + 1)].map((x, i) =>
    `<button data-storey="${i}" class="${st.storey === i ? "on" : ""}" title="${i ? `storey ${i}${i > 1 ? " and its floor" : ""}; in 3D, with the storeys below` : "every storey"}">${x}</button>`).join("");
}

$("#storeys").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-storey]");
  if (!b) return;
  st.storey = +b.dataset.storey;
  renderStoreys();
  look3d();
  renderElev();
});

// ---------------------------------------------------------------- the caption on the view while stepping

export function renderCaption() {
  const el = $("#caption");
  const d = st.data;
  const stepping = d && !finished() && !runsMode();
  $("#center").classList.toggle("stepping", !!stepping);
  if (!stepping) { el.hidden = true; return; }
  el.hidden = false;
  const n = d.steps.length;
  if (st.at === 0) {
    const ops = surfaceList().reduce((a, w) => a + w.openings.length, 0);
    const parts = d.walls.filter((w) => w.role === "interior").length;
    const ceilings = d.floors.filter((f) => f.role === "ceiling").length, roofs = d.roofs.length;
    const levels = Math.max(...d.walls.map((w) => w.storey));
    const plural = (k, word) => `${k} ${word}${k === 1 ? "" : "s"}`;
    const bits = [plural(levels, "storey"), plural(d.walls.length - parts, "wall"), plural(parts, "partition"),
      plural(d.floors.length - ceilings, "floor"), ceilings && plural(ceilings, "ceiling"), roofs && plural(roofs, "roof plane")].filter(Boolean);
    el.innerHTML = `<div class="c-top">step 0 of ${n}</div>
      <div class="c-main">The bare house: ${bits.slice(0, -1).join(", ")} and ${bits.at(-1)}, with ${plural(ops, "opening")}; no timber yet.</div>
      <div class="c-doc">Each wall, floor and roof plane is a surface: the plane of its framing's face. Press &#x2192; to fire the first rule.</div>`;
    return;
  }
  const s = current();
  const r = d.rules.find((x) => x.name === s.rule);
  const c = st.colors[s.rule];
  const what = [`placed ${s.placed.length} member${s.placed.length === 1 ? "" : "s"}`];
  if (s.removed.length) what.push(`removed ${s.removed.length}`);
  const main = trigger() ? `trigger: ${pill(s.rule, c)} matched <b>${esc(s.match)}</b>`
    : `output: ${pill(s.rule, c)} ${what.join(", ")} on <b>${esc(s.surface)}</b>`;
  el.innerHTML = `<div class="c-top">step ${stepNo()} of ${n}, ${trigger() ? "trigger" : "output"}, pass ${s.pass}</div>
    <div class="c-main">${main}</div>
    ${r?.doc ? `<div class="c-doc">${esc(oneLine(r.doc))}</div>` : ""}
    ${trigger() && r?.when ? `<div class="c-doc">when <code>${esc(r.when)}</code></div>` : ""}`;
}
