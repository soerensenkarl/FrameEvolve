// The right-hand panes about one frame: the Inspect tab (a member and its contacts, a rule with its
// before/after demo on the toy house, or a panel), the Report tab, and the timeline under the view (the strip
// of build steps, or of the assembly, and stepping). The Verifier is a tab of its own, in verifier.js.
import { $, esc, ftin, inch, pill, PAST, st, finished, trigger, stepNo, current, stopPlay, api, dirty,
  showTip, hideTip, panelOf, panelColour } from "./state.js";
import { select, renderRules } from "./app.js";
import { look3d } from "./view3d.js";
import { renderElev, renderCaption, scrollElevTo, memberSvg, outlinePath, surfPath, openingRect,
  bearerPoly, teeSvg, targetShape } from "./elevations.js";
import { jumpToRule } from "./editor.js";
import { asmTrack, panelHtml, choosePanel, asmGo, setView } from "./views.js";

export function chip(id) {
  if (id === "ground") return `<span class="chip"><i style="background:#8a877e"></i>ground</span>`;
  const m = st.byId[id];
  return `<span class="chip" data-id="${id}" title="${esc(m.rule)}"><i style="background:${st.colors[m.rule]}"></i>${id} ${esc(m.role || m.rule)}</span>`;
}

function ruleSource(name) {
  const r = st.data.rules.find((x) => x.name === name);
  if (!r) return "";
  const lines = $("#src").value.split("\n");
  return lines.slice(Math.max(0, r.line - 2), r.end).join("\n");
}

// ---------------------------------------------------------------- inspector

export function renderInspect() {
  const el = $("#inspect");
  const sel = st.sel;
  if (!sel) {
    el.innerHTML = `<p class="empty">Click a member in the 3D view or an elevation to see what it touches,
      or a rule on the left to see what it does.</p>
      <p class="empty">A selected member shows what it bears on (blue), what it carries (green), and what touches it
      from the side (purple). Everything else fades.</p>`;
    return;
  }
  if (sel.kind === "panel") { el.innerHTML = panelHtml(sel.id); return; }
  if (sel.kind === "rule") {
    const r = st.data.rules.find((x) => x.name === sel.id) || { name: sel.id };
    el.innerHTML = `<div class="title"><span class="sw" style="background:${st.colors[r.name]}"></span>${esc(r.name)}</div>
      <div id="ruleDemo"><p class="empty">Showing it on the toy house...</p></div>
      <p class="doc">${esc(r.doc || "No docstring.")}</p>
      <table class="kv"><tr><td>matches</td><td>every ${esc(r.match || "?")}${r.when ? ` where <code>${esc(r.when)}</code>` : ""}</td></tr>
      <tr><td>priority</td><td>${r.priority ?? "-"} <span class="muted">(lower fires first)</span></td></tr>
      <tr><td>members</td><td>${st.counts[r.name] || 0} on ${esc(st.data.house)}</td></tr>
      <tr><td>in faults</td><td>${st.data.members.filter((m) => m.rule === r.name && !m.removed && st.faulty.has(m.id)).length} members in hard faults</td></tr></table>
      <h4>Source <button class="edit" data-rule="${esc(r.name)}">edit</button></h4>
      <pre class="code">${esc(ruleSource(r.name))}</pre>`;
    loadRuleDemo(r.name);
    return;
  }
  const m = st.byId[sel.id];
  const [lo, hi] = m.local || [[0, 0, 0], [0, 0, 0]];
  const mine = st.data.faults.filter((f) => f.members.includes(m.id));
  el.innerHTML = `<div class="title"><span class="sw" style="background:${st.colors[m.rule]}"></span>${m.id} ${esc(m.role)}</div>
    ${mine.map((f) => `<p class="${f.hard ? "bad" : ""}"><span class="tag ${f.hard ? "" : "soft"}">${esc(f.check)}</span> ${esc(f.message)}</p>`).join("")}
    ${m.removed ? `<p class="empty">Removed later in the build.</p>` : ""}
    <table class="kv">
      <tr><td>rule</td><td><span class="chip" data-rule="${esc(m.rule)}"><i style="background:${st.colors[m.rule]}"></i>${esc(m.rule)}</span></td></tr>
      <tr><td>panel</td><td>${panelOf(m) ? `<span class="chip"><i style="background:${panelColour(panelOf(m))}"></i>${esc(panelOf(m))}</span> <span class="muted">${st.data.members.filter((x) => x.panel === m.panel && !x.removed).length} members</span>` : "built on site"}</td></tr>
      <tr><td>section</td><td>${esc(m.section)}</td></tr>
      <tr><td>length</td><td>${ftin(m.length)}</td></tr>
      <tr><td>surface</td><td>${m.surface ?? "-"}${st.surf[m.surface] ? `, storey ${st.level[m.surface]}` : ""}</td></tr>
      <tr><td>along (u)</td><td>${ftin(lo[0])} to ${ftin(hi[0])}</td></tr>
      <tr><td>up (v)</td><td>${ftin(lo[1])} to ${ftin(hi[1])}</td></tr>
      <tr><td>in (w)</td><td>${inch(lo[2])} to ${inch(hi[2])}</td></tr>
    </table>
    <h4 class="rel-bears">Bears on</h4><div class="rel-bears">${m.bears.map(chip).join("") || '<span class="empty">nothing</span>'}</div>
    <h4 class="rel-carries">Carries</h4><div class="rel-carries">${m.carries.map(chip).join("") || '<span class="empty">nothing</span>'}</div>
    <h4 class="rel-side">Beside</h4><div class="rel-side">${m.side.map(chip).join("") || '<span class="empty">nothing</span>'}</div>
    <h4>Placed by <button class="edit" data-rule="${esc(m.rule)}">edit rule</button></h4>
    <pre class="code">${esc(ruleSource(m.rule))}</pre>`;
}

// ---- the rule as a before -> after diagram, on the toy house

async function loadRuleDemo(name, firing) {
  const src = $("#src").value;
  if (st.demoFor !== src) { st.demo = new Map(); st.demoFor = src; }
  const key = `${name}|${firing ?? ""}`;
  if (!st.demo.has(key)) {
    const body = { grammar: $("#grammar").value, rule: name };
    if (dirty()) body.source = src;
    if (firing != null) body.firing = firing;
    st.demo.set(key, api("POST", "/api/rule_demo", body));
  }
  let d;
  try {
    d = await st.demo.get(key);
  } catch (e) {
    st.demo.delete(key);
    const box = $("#ruleDemo");
    if (box) box.innerHTML = `<p class="bad">Could not show it on the toy house: ${esc(e.message)}</p>`;
    return;
  }
  if (st.sel?.kind !== "rule" || st.sel.id !== name || !$("#ruleDemo")) return;
  $("#ruleDemo").innerHTML = demoHtml(d);
}

function demoSvg(d, after) {
  // every toy surface at one scale, in a frame fitted to the largest, so stepping between firings keeps still
  const w = d.surface, [L, H] = w.size, [SL, SH] = d.span;
  const pad = Math.max(SL, SH) / 50;
  const c = st.colors[d.rule] || "#888";
  const box = (b, cls, fillc) => memberSvg(b, `class="${cls}" fill="${fillc}"`, `${esc(b.id)} ${esc(b.role || b.rule)}`);
  const removed = new Set(d.removed.map((b) => b.id));
  const before = d.before.filter((b) => !after || !removed.has(b.id));
  const t = d.target;
  return `<svg class="demo-svg" viewBox="${-pad - (SL - L) / 2} ${-(SH + pad)} ${SL + 2 * pad} ${SH + 2 * pad}">
    ${surfPath(w, 0.18)}
    <path class="outline" d="${outlinePath(w.outline)}"/>
    ${w.bearers.map((b) => bearerPoly(b, "under")).join("")}
    ${d.neighbours.map((b) => box(b, "nb", "#e4e2dd")).join("")}
    ${before.map((b) => (t?.member === b.id ? box(b, `m now${after ? "" : " hit"}`, c) : box(b, "m", PAST))).join("")}
    ${after ? [...d.placed, ...d.shaped].map((b) => box(b, "m now", c)).join("") : d.removed.map((b) => box(b, "m gone", "none")).join("")}
    ${w.openings.map(openingRect).join("")}
    ${w.tees.map((tee) => teeSvg(tee, H, pad * 0.9, pad / 4)).join("")}
    ${t && t.kind !== "member" ? targetShape(t, c, `target ${after ? "out" : "trig"}`) : ""}
  </svg>`;
}

function demoHtml(d) {
  if (!d.surface) {
    return `<p class="empty demo-none">${esc(d.message || "This rule did nothing on the toy house.")}</p>
      ${d.errors?.length ? `<p class="bad">${esc(d.errors[0])}</p>` : ""}`;
  }
  const c = st.colors[d.rule] || "#888";
  const w = d.surface;
  const n = d.placed.length, r = d.removed.length, k = d.shaped.length;
  const what = [n ? `placed ${n} member${n === 1 ? "" : "s"}` : "", k ? `cut ${k}` : "", r ? `removed ${r}` : ""]
    .filter(Boolean).join(", ") || "changed nothing visible";
  const many = d.firings.length > 1;
  const nav = many ? `<span class="dnav" title="other firings of this rule on the toy house"><button data-firing="${d.firing - 1}" ${d.firing === 0 ? "disabled" : ""} title="previous firing">&#x2039;</button>
      firing ${d.firing + 1} of ${d.firings.length}
      <button data-firing="${d.firing + 1}" ${d.firing >= d.firings.length - 1 ? "disabled" : ""} title="next firing">&#x203A;</button></span>` : "";
  return `<div class="demo">
    <div class="dlab">Trigger: matched ${esc(d.match || "")} ${nav}</div>${demoSvg(d, false)}
    <div class="darrow">&#x2193; ${pill(d.rule, c)}</div>
    <div class="dlab">Output</div>${demoSvg(d, true)}
    <p class="dcap">On the toy house, ${w.kind === "roof" ? "roof plane" : w.role === "ceiling" ? "ceiling" : w.kind} ${esc(w.id)}${w.kind !== "wall" ? (w.role === "ceiling" ? " seen from below" : " seen from above") : ""}${d.target?.other ? ` where it meets ${esc(d.target.other)}` : ""}${d.target?.face === "inner" ? `, ${w.kind === "floor" ? "ceiling" : "inside face"}` : ""},
      pass ${d.pass}: ${what}.${many ? "" : " It fires once there."}</p>
  </div>`;
}

$("#inspect").addEventListener("click", (e) => {
  const f = e.target.closest("button[data-firing]");
  if (f && st.sel?.kind === "rule") return loadRuleDemo(st.sel.id, +f.dataset.firing);
  const edit = e.target.closest("button.edit");
  if (edit) return jumpToRule(edit.dataset.rule);
  const c = e.target.closest(".chip[data-id]");
  if (c && st.byId[c.dataset.id]) return select({ kind: "member", id: c.dataset.id });
  const p = e.target.closest("[data-panel]");
  if (p) return choosePanel(p.dataset.panel, true);
  const a = e.target.closest("button[data-asm]");
  if (a) { setView("assembly"); return asmGo(+a.dataset.asm); }
  const r = e.target.closest("[data-rule]");
  if (r) return select({ kind: "rule", id: r.dataset.rule });
});

// ---------------------------------------------------------------- report

export function renderReport() {
  $("#reportText").textContent = st.data.report;
}

// ---------------------------------------------------------------- the timeline: a strip of steps, and stepping

// The strip is a canvas showing a track: the build's half-steps 0..2n (each step's trigger, a tint or hollow when
// there is room, then its output in the rule's colour), or in the assembly view the erection order (views.js).
// With room the segments keep small gaps and a wider one at a break (a new pass, a new storey); a track of
// thousands packs them edge to edge, a pixel or less each.
const STRIP_H = 18;
let lay = null;   // where each segment starts and how wide it is, for the track and width last drawn

const buildTrack = {
  get key() { return st.data.steps; },
  get count() { return 2 * st.data.steps.length + 1; },
  zero: true,   // segment 0, the bare house, is a fixed small square
  brk(i) {
    const steps = st.data.steps, k = (i - 1) / 2;
    return i === 1 ? 2 : i % 2 === 0 ? 0 : steps[k].pass !== steps[k - 1].pass ? 2 : 1;
  },
  look(i, L) {
    if (!i) return ["#f0efeb", "#8fb0cf"];
    const c = st.colors[st.data.steps[Math.ceil(i / 2) - 1].rule] || "#999";
    if (i % 2 === 0) return [c, null];
    return L.roomy ? ["#ffffff", c] : [L.seg * (window.devicePixelRatio || 1) >= 1 ? tint(c) : c, null];
  },
  at: () => st.at,
  get max() { return 2 * st.data.steps.length; },
  cursor: () => (finished() ? null : st.at),
  go: (i) => goto(i),
  tip: (i) => stepTip(i),
  label() {
    const n = st.data.steps.length;
    return finished() ? `<b>finished</b>, ${n} steps` : st.at === 0 ? `<b>step 0</b> of ${n}`
      : `<b>step ${stepNo()}</b> of ${n}, ${trigger() ? "trigger" : "output"}`;
  },
};
const track = () => (st.view === "assembly" ? asmTrack : buildTrack);

function stripLayout(W, t) {
  if (lay && lay.key === t.key && lay.W === W) return lay;
  const n = t.count, fixed = t.zero ? 1 : 0, b = new Uint8Array(n);
  let c1 = 0, c2 = 0;
  for (let i = 1; i < n; i++) { b[i] = t.brk(i); if (b[i] === 1) c1++; else if (b[i] === 2) c2++; }
  const fit = (g) => (W - fixed * g.zero - g.g1 * c1 - g.g2 * c2) / Math.max(1, n - fixed);
  let g = { zero: 14, g1: 1, g2: 4 }, seg = fit(g);
  const roomy = seg >= 4;
  if (!roomy) { g = { zero: 6, g1: 0, g2: c2 * 2 < W / 10 ? 2 : 0 }; seg = Math.max(0, fit(g)); }
  const x = new Float64Array(n);
  let at = 0;
  for (let i = 0; i < n; i++) {
    at += b[i] === 1 ? g.g1 : b[i] === 2 ? g.g2 : 0;
    x[i] = at;
    at += fixed && !i ? g.zero : seg;
  }
  lay = { key: t.key, W, n, x, seg, roomy, w: (i) => (fixed && !i ? g.zero : seg) };
  return lay;
}

function tint(hex, t = 0.55) {
  // a colour mixed with white
  const c = parseInt(hex.slice(1), 16), mix = (v) => Math.round(v + (255 - v) * t);
  return `rgb(${mix(c >> 16)},${mix((c >> 8) & 255)},${mix(c & 255)})`;
}

function drawStrip() {
  const cv = $("#strip"), W = $("#stripWrap").clientWidth, t = track();
  if (!st.data || !W) return;
  const L = stripLayout(W, t), dpr = window.devicePixelRatio || 1;
  const cw = Math.round(W * dpr), ch = Math.round(STRIP_H * dpr);
  if (cv.width !== cw || cv.height !== ch) { cv.width = cw; cv.height = ch; }
  const ctx = cv.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cw, ch);
  const px = (v) => Math.round(v * dpr);
  const span = (i) => { const a = px(L.x[i]); return [a, Math.max(a + 1, px(L.x[i] + L.w(i)))]; };
  const shape = (i, y0, y1, [fill, stroke]) => {
    // a segment: rounded when there is room, else a crisp column of whole device pixels
    const [a, b] = span(i);
    ctx.beginPath();
    if (L.roomy || (t.zero && !i)) ctx.roundRect ? ctx.roundRect(a, y0, b - a, y1 - y0, 2 * dpr) : ctx.rect(a, y0, b - a, y1 - y0);
    else ctx.rect(a, y0, b - a, y1 - y0);
    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) {
      ctx.save();
      ctx.clip();   // an inside border, as an inset shadow would draw it
      ctx.lineWidth = 3 * dpr;
      ctx.strokeStyle = stroke;
      ctx.stroke();
      ctx.restore();
    }
  };
  const y0 = px(3), y1 = ch - px(3), at = t.at();
  for (let i = 0; i < L.n; i++) {
    ctx.globalAlpha = i > at ? 0.28 : 1;
    shape(i, y0, y1, t.look(i, L));
  }
  ctx.globalAlpha = 1;
  const i = t.cursor();   // the cursor: the segment shown, raised and outlined, or a dark line when it is thin
  if (i == null || i >= L.n) return;
  const zero = t.zero && !i;
  if (L.roomy || zero) {
    shape(i, zero ? y0 : 0, zero ? y1 : ch, t.look(i, L));
    const [a, b] = span(i), o = (zero ? 2 : 1.5) * dpr, top = zero ? y0 : 0, bot = zero ? y1 : ch;
    ctx.lineWidth = o;
    ctx.strokeStyle = "#1d1d1b";
    ctx.strokeRect(a - o / 2, top + (zero ? -o / 2 : o / 2), b - a + o, bot - top + (zero ? o : -o));
  } else {
    const m = px(L.x[i] + L.seg / 2);
    ctx.fillStyle = "#1d1d1b";
    ctx.fillRect(m - px(1), 0, px(2), ch);
  }
}

function stripAt(clientX) {
  // the segment under a point of the strip, or the nearer one in a gap
  const L = lay;
  if (!L || !L.n) return 0;
  const x = clientX - $("#strip").getBoundingClientRect().left, last = L.n - 1;
  let lo = 0, hi = last;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (L.x[m] <= x) lo = m; else hi = m - 1; }
  const end = L.x[lo] + L.w(lo);
  return lo < last && x > end && x - end > L.x[lo + 1] - x ? lo + 1 : lo;
}

export function renderTimeline() {
  if (!st.data) return;
  drawStrip();
  $("#tlLabel").innerHTML = track().label();
  $("#tlPlay").innerHTML = st.playing ? "&#x23F8;" : "&#x25B6;";
}

export function stepBy(d) {
  // the arrow keys and the step buttons: one step along the timeline shown
  stopPlay();
  const t = track();
  t.go(t.at() + d);
}

function stepTip(i) {
  if (i === 0) return "step 0: the bare house";
  const s = st.data.steps[Math.ceil(i / 2) - 1];
  return i % 2 ? `step ${Math.ceil(i / 2)}, trigger: ${esc(s.rule)} matched ${esc(s.match)}`
    : `step ${i / 2}, output: ${esc(s.rule)} placed ${s.placed.length}${s.removed.length ? `, removed ${s.removed.length}` : ""} on ${esc(s.surface)}`;
}

export function goto(at) {
  if (!st.data) return;
  st.at = Math.max(0, Math.min(2 * st.data.steps.length, at));
  renderTimeline();
  renderRules();
  renderCaption();
  look3d();
  renderElev();
  scrollElevTo(current()?.surface, { block: "nearest", behavior: st.playing ? "auto" : "smooth" });
}

{
  const strip = $("#strip");
  let dragging = false;
  strip.addEventListener("pointerdown", (e) => {
    if (!lay) return;
    dragging = true;
    strip.setPointerCapture(e.pointerId);
    stopPlay();
    track().go(stripAt(e.clientX));
  });
  strip.addEventListener("pointermove", (e) => {
    if (!lay) return;
    const i = stripAt(e.clientX), r = strip.getBoundingClientRect(), t = track();
    showTip(t.tip(i), { left: e.clientX, width: 0, top: r.top, bottom: r.bottom }, "above");
    if (dragging && i !== t.at()) t.go(i);
  });
  strip.addEventListener("pointerup", () => { dragging = false; });
  strip.addEventListener("pointerleave", hideTip);
  new ResizeObserver(drawStrip).observe($("#stripWrap"));
}

$("#tlStart").addEventListener("click", () => { stopPlay(); track().go(0); });
$("#tlEnd").addEventListener("click", () => { stopPlay(); track().go(Infinity); });
$("#tlPrev").addEventListener("click", () => stepBy(-1));
$("#tlNext").addEventListener("click", () => stepBy(1));
$("#tlPlay").addEventListener("click", () => {
  if (st.playing) { stopPlay(); renderTimeline(); return; }
  const t = track();
  if (t.at() >= t.max) t.go(0);
  st.playing = setInterval(() => {
    const t = track();
    if (t.at() >= t.max) { stopPlay(); renderTimeline(); return; }
    t.go(t.at() + 1);
  }, 380);
  renderTimeline();
});
