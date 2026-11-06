// The right-hand panes about one frame: the Inspect tab (a member and its contacts, or a rule with its
// before/after demo on the toy house), the Verifier tab (the score, every check, each fault with its
// evidence), the Report tab, and the build timeline under the view (the strip of firings and stepping).
import { $, esc, ftin, inch, num, pill, PAST, st, finished, trigger, stepNo, current, stopPlay, api, dirty,
  faceName, shown3d, chosenFault, showTip, hideTip, panelOf, panelColour } from "./state.js";
import { select, renderRules } from "./app.js";
import { look3d, renderMarks, zoomTo } from "./view3d.js";
import { renderElev, renderStoreys, renderCaption, scrollElevTo, memberSvg, outlinePath, surfPath, openingRect,
  bearerPoly, teeSvg, targetShape } from "./elevations.js";
import { jumpToRule } from "./editor.js";

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

for (const pane of ["#inspect", "#faults"]) {
  $(pane).addEventListener("click", (e) => {
    const f = e.target.closest("button[data-firing]");
    if (f && st.sel?.kind === "rule") return loadRuleDemo(st.sel.id, +f.dataset.firing);
    const edit = e.target.closest("button.edit");
    if (edit) return jumpToRule(edit.dataset.rule);
    const c = e.target.closest(".chip[data-id]");
    if (c && st.byId[c.dataset.id]) return select({ kind: "member", id: c.dataset.id });
    const r = e.target.closest("[data-rule]");
    if (r) return select({ kind: "rule", id: r.dataset.rule });
  });
}

// ---------------------------------------------------------------- the verifier: its checks, and each fault with its evidence

const axisOf = (m) => { const d = [0, 1, 2].map((k) => m.hi[k] - m.lo[k]); return d.indexOf(Math.max(...d)); };
const centre = (m) => [0, 1, 2].map((k) => (m.lo[k] + m.hi[k]) / 2);

function limitText(name) {
  // a limit from the verifier's constants, in feet and inches (or the unit its comment names)
  const c = st.vinfo?.constants[name];
  if (!c) return name;
  const unit = name.startsWith("SAG_") ? (x) => `L/${x}`
    : /^(FB|FC|FC_PERP|E|E_MIN)$/.test(name) ? (x) => `${x.toLocaleString()} psi`
    : /WEIGHT/.test(name) ? (x) => `${x.toLocaleString()} lb`
    : /^(MITER|BEVEL)$/.test(name) ? (x) => `${x} degrees`
    : c.module === "analysis" || /NOTCH|SHARE|RATIO|PITCH|UNBRACED|DENSITY|SKIN|FACES|COST/.test(name) ? (x) => `${+(+x).toFixed(3)}`
    : null;
  const v = c.value, len = unit || ((x) => (x >= 12 ? ftin(x) : inch(x)));
  const sec = Object.fromEntries(Object.entries(st.vinfo.sections).map(([n, d]) => [String(d), n]));
  const key = (d) => {   // a depth, or "plies, depth" for a header table
    const p = String(d).split(", ");
    return p.length === 2 ? `${p[0]}-${sec[p[1]] || p[1]}` : sec[d] || `${d}`;
  };
  const val = (x) => typeof x === "string" ? x : Array.isArray(x) ? `${len(x[0])}${x.length > 1 ? ` (${x.slice(1).join(", ")})` : ""}`
    : typeof x === "object" ? Object.entries(x).map(([k, y]) => `${k}" o.c. ${len(y)}`).join(" / ") : len(x);
  if (Array.isArray(v)) return v.every((x) => typeof x === "number") ? `${len(Math.min(...v))} to ${len(Math.max(...v))}`
    : v.map((x) => Array.isArray(x) ? x.map((y) => typeof y === "number" ? len(y) : y).join(": ") : x).join(", ");
  if (typeof v === "object") return Object.entries(v).map(([d, x]) => `${key(d)} ${val(x)}`).join("; ");
  if (typeof v !== "number") return String(v);
  return /linear feet/.test(c.note) ? `${v} ft` : len(v);
}

const name = (x) => `${x.id} (${esc(x.role || x.rule)})`;
const limits = (ns) => ns.map((n) => `<span class="lim">${n}: ${limitText(n)}</span>`).join(" ");

// what holds a member along its long axis: [from, to, id] for each support it bears on, in order
function supportsOf(m) {
  const k = axisOf(m);
  return m.bears.filter((id) => st.byId[id]).map((id) => {
    const s = st.byId[id];
    return [Math.max(m.lo[k], s.lo[k]), Math.min(m.hi[k], s.hi[k]), id];
  }).sort((a, b) => a[0] - b[0]);
}

// what to draw and say for each check: (fault, its first member, out) -> false when it has nothing to add
const EVIDENCE = {
  span(f, m, out) {
    if (!m) return false;
    const k = axisOf(m), c = centre(m), sup = supportsOf(m);
    out.supports = sup.map((x) => x[2]);
    const at = (x) => { const p = [...c]; p[k] = x; p[2] = m.hi[2] + 4; return p; };   // a little above the member
    const lim = f.message.match(/limit (.+?)(?: for (.+))?$/);
    let reach = sup[0]?.[1], left = sup[0]?.[2];
    for (const [s0, s1, id] of sup.slice(1)) {
      if (s0 > reach && f.at[k] >= reach - 1 && f.at[k] <= s0 + 1) {
        out.dims.push({ a: at(reach), b: at(s0), text: `${ftin(s0 - reach)} clear, limit ${lim?.[1] ?? "?"}` });
        out.text = `${name(m)} carries load and spans <b>${ftin(s0 - reach)}</b> clear between ${chip(left)} and ${chip(id)}.
          The limit for ${esc(lim?.[2] || "it")} is <b>${esc(lim?.[1] || "?")}</b>.`;
        break;
      }
      if (s1 >= reach) { reach = s1; left = id; }
    }
    out.text += `<div class="lims">${limits(st.vinfo?.checks.find((x) => x.name === "span")?.limits || [])}</div>`;
  },
  overhang(f, m, out) {
    if (!m) return false;
    const k = axisOf(m), c = centre(m), sup = supportsOf(m);
    out.supports = sup.map((x) => x[2]);
    const at = (x) => { const p = [...c]; p[k] = x; p[2] = m.hi[2] + 4; return p; };
    const last = Math.max(...sup.map((x) => x[1])), first = sup[0]?.[0];
    const [a, b] = Math.abs(f.at[k] - m.lo[k]) < Math.abs(f.at[k] - m.hi[k]) ? [m.lo[k], first] : [last, m.hi[k]];
    out.dims.push({ a: at(a), b: at(b), text: `${ftin(b - a)} past its support, limit ${limitText("MAX_OVERHANG")}` });
    out.text = `${name(m)} runs <b>${ftin(b - a)}</b> past its last support; a loaded member may overhang at most <b>${limitText("MAX_OVERHANG")}</b>.`;
  },
  bearing(f, m, out) {
    if (!m) return false;
    const s = st.byId[f.members[1]], k = axisOf(m), c = centre(m);
    out.supports = s ? [s.id] : [];
    if (s) {
      const a = Math.max(m.lo[k], s.lo[k]), b = Math.min(m.hi[k], s.hi[k]);
      const at = (x) => { const p = [...c]; p[k] = x; p[2] = m.lo[2] - 2; return p; };
      out.dims.push({ a: at(a), b: at(b), text: `bears ${inch(b - a)}, minimum ${limitText("MIN_BEARING")}` });
    }
    out.text = `${esc(f.message)}. A member must sit at least <b>${limitText("MIN_BEARING")}</b> on what holds it.`;
  },
  clash(f, m, out) {
    const o = st.byId[f.members[1]];
    if (!m || !o) return false;
    const lo = [0, 1, 2].map((k) => Math.max(m.lo[k], o.lo[k])), hi = [0, 1, 2].map((k) => Math.min(m.hi[k], o.hi[k]));
    out.boxes.push({ lo, hi });
    out.text = `${name(m)} and ${name(o)} occupy the same space: the red box, ${inch(hi[0] - lo[0])} x ${inch(hi[1] - lo[1])} x ${inch(hi[2] - lo[2])}.
      Two pieces of timber cannot overlap; one must stop short, or be notched (not modelled yet).`;
  },
  backing(f, m, out) {
    const s = st.surf[f.surface], face = /inner face/.test(f.message) ? "inner" : "outer";
    const g = s?.gaps.find((x) => x.face === face && Math.abs((x.u0 + x.u1) / 2 - f.u) < 0.6 && Math.abs((x.v0 + x.v1) / 2 - f.v) < 0.6);
    if (!g) { out.text = esc(f.message); return; }
    const W = g.u1 - g.u0, H = g.v1 - g.v0;
    out.rects.push({ sid: s.id, face, ...g, text: `${ftin(W)} x ${ftin(H)}` });
    out.text = g.kind === "edge"
      ? `On the ${faceName(s, face)} of ${s.id}, a board edge runs <b>${ftin(Math.max(W, H))}</b> with nothing behind it.
         An edge needs backing at least every <b>${limitText("MAX_EDGE")}</b>, so blocking or clips will do.`
      : `On the ${faceName(s, face)} of ${s.id}, a board spans <b>${ftin(W)} by ${ftin(H)}</b> with nothing behind it.
         It needs support within <b>${limitText("MAX_CLEAR")}</b> in at least one direction (24" centres less one stud).`;
  },
  floating(f, m, out) {
    if (!m) return false;
    const list = (ids) => ids.filter((id) => st.byId[id] || id === "ground").map(chip).join("") || "nothing";
    out.text = `${name(m)} has no chain of bearing down to the ground. It bears on: ${list(m.bears)}. Beside it: ${list(m.side)}.
      None of these is held up, and it is not nailed between two held-up members at both ends.`;
  },
};

export function evidence(f) {
  // what to draw and say for one fault: members that hold it (supports), dimension lines, boxes, face rectangles
  const out = { supports: [], dims: [], boxes: [], rects: [], text: "" };
  const m = st.byId[f.members[0]];
  if (EVIDENCE[f.check]?.(f, m, out) === false || !EVIDENCE[f.check]) out.text = `${esc(f.message)}.`;
  return out;
}
export { chosenFault };

export function renderVerifier() {
  const el = $("#faults");
  const d = st.data, vi = st.vinfo;
  if (!d || !vi) { el.innerHTML = `<p class="empty">Loading the verifier...</p>`; return; }
  const s = d.stats, k = (n) => vi.constants[n]?.value ?? 0;
  const cost = k("PIECE_COST"), siteCost = k("SITE_PIECE_COST") || cost, lift = k("LIFT_COST");
  const site = s.site_pieces ?? 0, shop = s.members - site, panels = s.panels ?? 0;
  const rows = Object.entries(s.by_section || {}).map(([sec, x]) => {
    const w = (vi.sections[sec] || 3.5) / 3.5;
    return `<tr><td>${esc(sec)}</td><td>${x.pieces}</td><td>${num(x.bought_ft)} ft</td><td>x ${w.toFixed(2)}</td><td>${num(x.bought_ft * w)} ft</td></tr>`;
  }).join("");
  const byCheck = {};
  d.faults.forEach((f, i) => (byCheck[f.check] ||= []).push(i));
  const checks = vi.checks.map((c) => {
    const idx = byCheck[c.name] || [];
    const open = st.openChecks.has(c.name);
    const list = open ? idx.slice(0, 60).map((i) => {
      const f = d.faults[i], sel = st.fault === i;
      return `<div class="fault ${sel ? "sel" : ""}" data-fault="${i}">${esc(f.message)}
        ${sel ? `<div class="explain-f">${evidence(f).text} ${f.at ? `<button class="zoomto" title="Bring the 3D view close to it">zoom to it</button>` : ""}
          <div>${f.members.filter((id) => st.byId[id]).map(chip).join("")}${f.rules.map((r) =>
            `<span class="chip" data-rule="${esc(r)}"><i style="background:${st.colors[r] || "#999"}"></i>${esc(r)}</span>`).join("") || (f.members.length ? "" : `<span class="muted">nothing was placed here, so no rule to blame</span>`)}</div></div>` : ""}</div>`;
    }).join("") + (idx.length > 60 ? `<p class="muted">... and ${idx.length - 60} more</p>` : "") : "";
    return `<div class="check ${idx.length ? "has" : ""} ${open ? "open" : ""}">
      <div class="ch-head" data-check="${esc(c.name)}"><span class="tag ${c.hard ? "" : "soft"}">${c.hard ? "hard" : "soft"}</span>
        <b>${esc(c.name)}</b><span class="count ${idx.length ? "bad" : "good"}">${idx.length || "none"}</span>
        ${idx.length ? `<button class="only ${st.only === c.name ? "on" : ""}" data-only="${esc(c.name)}" title="show only these faults in 3D and on the surfaces">only</button>` : ""}</div>
      <div class="ch-body">${esc(c.meaning)}.
        ${c.limits.length ? `<div class="lims">${c.limits.map((n) => `<span class="lim" title="${esc(vi.constants[n]?.note || "")}">${esc(vi.constants[n]?.note.split(":")[0] || n)}: <b>${limitText(n)}</b></span>`).join("")}</div>` : ""}
        ${c.code.length ? `<div class="code-ref">approximates ${c.code.map(esc).join(", ")}</div>` : ""}</div>
      ${list}</div>`;
  }).join("");
  el.innerHTML = `<div class="score">
      <h4>The score</h4>
      <div class="scoreline"><span class="${s.hard ? "bad" : "good"}"><b>${s.hard}</b> hard</span>, <b>${s.soft}</b> soft, cost <b>${num(s.cost)} ft</b></div>
      <p class="hint">Grammars are compared by hard faults first (unbuildable), then soft faults (code or practice), then cost.
        A cheaper frame never beats one with fewer faults.</p>
      <details><summary>How the cost is worked out</summary>
        <p class="hint">Each section's pieces are cut from stock lengths of ${limitText("STOCK")}, longest first, with a ${limitText("KERF")} saw kerf.
          The lumber bought counts in proportion to its depth, as linear feet of 2x4. A piece built into a panel in the shop adds ${cost} ft
          for cutting, handling and nailing, one cut and nailed on site ${siteCost} ft, and each panel ${lift} ft to truck and lift it in.</p>
        <table class="costs"><tr><th>section</th><th>pieces</th><th>bought</th><th>depth</th><th>as 2x4</th></tr>${rows}
          <tr><td colspan="4">${shop} pieces in panels x ${cost} ft</td><td>${num(shop * cost)} ft</td></tr>
          <tr><td colspan="4">${site} pieces built on site x ${siteCost} ft</td><td>${num(site * siteCost)} ft</td></tr>
          <tr><td colspan="4">${panels} panels lifted x ${lift} ft</td><td>${num(panels * lift)} ft</td></tr>
          <tr class="tot"><td colspan="4">cost</td><td>${num(s.cost)} ft</td></tr></table></details>
    </div>
    <h4>Checks <small>click one to list its faults; click a fault to see its evidence</small></h4>
    ${st.only ? `<p class="hint">Showing only <b>${esc(st.only)}</b> faults. <a href="#" data-only="${esc(st.only)}">Show all</a></p>` : ""}
    ${checks}`;
}

$("#faults").addEventListener("click", (e) => {
  const only = e.target.closest("[data-only]");
  if (only) {
    e.preventDefault();
    st.only = st.only === only.dataset.only ? null : only.dataset.only;
    st.openChecks.add(only.dataset.only);
    renderMarks();
    look3d();
    renderElev();
    return renderVerifier();
  }
  if (e.target.closest("button.zoomto")) return zoomTo(chosenFault().at);
  if (e.target.closest(".chip, button")) return;
  const fi = e.target.closest("[data-fault]");
  if (fi) return chooseFault(+fi.dataset.fault);
  const head = e.target.closest("[data-check]");
  if (head) {
    const n = head.dataset.check;
    st.openChecks.has(n) ? st.openChecks.delete(n) : st.openChecks.add(n);
    renderVerifier();
  }
});

export function chooseFault(i) {
  st.fault = st.fault === i ? null : i;
  st.sel = null;
  const f = chosenFault();
  if (f && st.storey && !shown3d(f.surface)) st.storey = 0;
  renderStoreys();
  look3d();
  renderElev();
  renderInspect();
  renderVerifier();
  scrollElevTo(f?.surface, { block: "center", behavior: "smooth" });
}

// ---------------------------------------------------------------- report

export function renderReport() {
  $("#reportText").textContent = st.data.report;
}

// ---------------------------------------------------------------- build timeline: a strip of rule firings

function renderStrip() {
  const strip = $("#strip");
  if (strip.dataset.build === String(st.builds)) return;
  strip.dataset.build = String(st.builds);
  const steps = st.data.steps;
  // each firing is a pair: a hollow trigger, then the filled output, in the rule's colour
  strip.innerHTML = `<div class="seg zero" data-i="0"></div>` + steps.map((s, i) =>
    `<div class="pair ${i && s.pass !== steps[i - 1].pass ? "pass" : ""}" style="--c:${st.colors[s.rule]}">` +
    `<div class="seg trig" data-i="${2 * i + 1}"></div><div class="seg out" data-i="${2 * i + 2}"></div></div>`).join("");
}

export function renderTimeline() {
  if (!st.data) return;
  renderStrip();
  const n = st.data.steps.length;
  for (const seg of $("#strip").querySelectorAll(".seg")) {
    const i = +seg.dataset.i;
    seg.classList.toggle("ahead", i > st.at);
    seg.classList.toggle("cur", i === st.at && !finished());
  }
  $("#tlLabel").innerHTML = finished() ? `<b>finished</b>, ${n} steps` : st.at === 0 ? `<b>step 0</b> of ${n}`
    : `<b>step ${stepNo()}</b> of ${n}, ${trigger() ? "trigger" : "output"}`;
  $("#tlPlay").innerHTML = st.playing ? "&#x23F8;" : "&#x25B6;";
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
  const segAt = (e) => {
    const r = strip.getBoundingClientRect();
    return document.elementFromPoint(Math.max(r.left + 1, Math.min(r.right - 1, e.clientX)), r.top + r.height / 2)?.closest(".seg");
  };
  strip.addEventListener("pointerdown", (e) => {
    const seg = segAt(e);
    if (!seg) return;
    dragging = true;
    strip.setPointerCapture(e.pointerId);
    stopPlay();
    goto(+seg.dataset.i);
  });
  strip.addEventListener("pointermove", (e) => {
    const seg = segAt(e);
    if (seg) showTip(stepTip(+seg.dataset.i), seg.getBoundingClientRect(), "above");
    if (dragging && seg && +seg.dataset.i !== st.at) goto(+seg.dataset.i);
  });
  strip.addEventListener("pointerup", () => { dragging = false; });
  strip.addEventListener("pointerleave", hideTip);
}

$("#tlStart").addEventListener("click", () => { stopPlay(); goto(0); });
$("#tlEnd").addEventListener("click", () => { stopPlay(); goto(Infinity); });
$("#tlPrev").addEventListener("click", () => { stopPlay(); goto(st.at - 1); });
$("#tlNext").addEventListener("click", () => { stopPlay(); goto(st.at + 1); });
$("#tlPlay").addEventListener("click", () => {
  if (st.playing) { stopPlay(); renderTimeline(); return; }
  if (finished()) st.at = 0;
  st.playing = setInterval(() => {
    if (finished()) { stopPlay(); renderTimeline(); return; }
    goto(st.at + 1);
  }, 380);
  goto(st.at);
});
