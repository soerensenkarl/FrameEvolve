// The Verifier tab: what the verifier asks of a frame and what it found. The score on top, then every check in
// one table, under the question its module asks, filtered to all, faulted, hard or soft checks; a chosen
// question shows its module's description, a chosen check its limits, the
// code it cites and its faults by surface, and a chosen fault its evidence, which the 3D view and the
// surfaces draw too. Also here: `evidence(f)`, what to draw and say for one fault, and `limitText`.
import { $, esc, ftin, inch, num, st, finished, chosenFault, shown3d, listed, faceName, kindName } from "./state.js";
import { select, showTab } from "./app.js";
import { look3d, renderMarks, zoomTo } from "./view3d.js";
import { renderElev, renderStoreys, scrollElevTo } from "./elevations.js";
import { chip, renderInspect, goto } from "./inspect.js";
import { setView, renderSide } from "./views.js";

// ---------------------------------------------------------------- limits and evidence

const axisOf = (m) => { const d = [0, 1, 2].map((k) => m.hi[k] - m.lo[k]); return d.indexOf(Math.max(...d)); };
const centre = (m) => [0, 1, 2].map((k) => (m.lo[k] + m.hi[k]) / 2);

export function limitText(name) {
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

// ---------------------------------------------------------------- the tab

const WIDE = 1100;  // from this width a chosen check opens in a column beside the modules, else under its row
const PAGE = 80;    // faults listed at first, and how many more "show more" adds

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

// the frame's faults by check, worked out once per frame
let ix = { data: null, by: {} };
function byCheck() {
  if (ix.data !== st.data) {
    const by = {};
    st.data.faults.forEach((f, i) => (by[f.check] ||= []).push(i));
    ix = { data: st.data, by };
  }
  return ix.by;
}

function modules() {
  // the verifier's modules in order, each with its checks; checks no module lists, and faults from a check
  // the verifier did not describe, go under "Other checks" so nothing is out of reach
  const vi = st.vinfo, by = byCheck();
  const known = new Map(vi.checks.map((c) => [c.name, c]));
  const list = vi.modules || [...new Set(vi.checks.map((c) => c.module || "other"))].map((n) =>
    ({ name: n, question: n, doc: "", checks: vi.checks.filter((c) => (c.module || "other") === n).map((c) => c.name) }));
  const mods = list.map((m) => ({ ...m, checks: m.checks.map((n) => known.get(n)).filter(Boolean) }));
  const placed = new Set(mods.flatMap((m) => m.checks.map((c) => c.name)));
  const other = [...vi.checks.filter((c) => !placed.has(c.name)),
    ...Object.keys(by).filter((n) => !known.has(n)).map((n) => ({ name: n, meaning: "", hard: st.data.faults[by[n][0]].hard, limits: [], code: [] }))];
  if (other.length) mods.push({ name: "other", question: "Other checks", doc: "", checks: other });
  return mods.filter((m) => m.checks.length);
}

function tally(idx) {
  let hard = 0;
  for (const i of idx) if (st.data.faults[i].hard) hard++;
  return { n: idx.length, hard, soft: idx.length - hard };
}

function docHtml(paras) {
  // docstring paragraphs as HTML: lines joined, "- " lines as a list, a numbered paragraph's title in bold
  const j = (ls) => esc(ls.join(" ")).replace(/`([^`]+)`/g, "<code>$1</code>");
  return paras.map((p) => {
    const lead = [], items = [];
    for (const line of p.split("\n")) {
      const m = line.match(/^\s*- (.*)/);
      if (m) items.push([m[1]]);
      else if (items.length) items.at(-1).push(line.trim());
      else lead.push(line.trim());
    }
    const head = j(lead).replace(/^(\d+\. .+?\.)(?=\s|$)/, "<b>$1</b>");
    return (lead.length ? `<p>${head}</p>` : "") +
      (items.length ? `<ul>${items.map((x) => `<li>${j(x).replace(/^([a-z][a-z ]*):/, "<b>$1</b>:")}</li>`).join("")}</ul>` : "");
  }).join("");
}
const paragraphs = (doc) => (doc || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);

function costHtml() {
  const s = st.data.stats, vi = st.vinfo, k = (n) => vi.constants[n]?.value ?? 0;
  const cost = k("PIECE_COST"), siteCost = k("SITE_PIECE_COST") || cost, lift = k("LIFT_COST");
  const site = s.site_pieces ?? 0, shop = s.members - site, panels = s.panels ?? 0;
  const rows = Object.entries(s.by_section || {}).map(([sec, x]) => {
    const w = (vi.sections[sec] || 3.5) / 3.5;
    return `<tr><td>${esc(sec)}</td><td>${x.pieces}</td><td>${num(x.bought_ft)} ft</td><td>x ${w.toFixed(2)}</td><td>${num(x.bought_ft * w)} ft</td></tr>`;
  }).join("");
  return `<details data-key="d:cost" ${st.vOpen.has("d:cost") ? "open" : ""}><summary>How the cost is worked out</summary>
    <p class="vf-p">Each section's pieces are cut from stock lengths of ${limitText("STOCK")}, longest first, with a ${limitText("KERF")} saw kerf.
      The lumber bought counts in proportion to its depth, as linear feet of 2x4. A piece built into a panel in the shop adds ${cost} ft
      for cutting, handling and nailing, one cut and nailed on site ${siteCost} ft, and each panel ${lift} ft to truck and lift it in.</p>
    <table class="costs"><tr><th>section</th><th>pieces</th><th>bought</th><th>depth</th><th>as 2x4</th></tr>${rows}
      <tr><td colspan="4">${shop} pieces in panels x ${cost} ft</td><td>${num(shop * cost)} ft</td></tr>
      <tr><td colspan="4">${site} pieces built on site x ${siteCost} ft</td><td>${num(site * siteCost)} ft</td></tr>
      <tr><td colspan="4">${panels} panels lifted x ${lift} ft</td><td>${num(panels * lift)} ft</td></tr>
      <tr class="tot"><td colspan="4">cost</td><td>${num(s.cost)} ft</td></tr></table></details>`;
}

function headHtml() {
  const s = st.data.stats;
  return `<div class="vf-head">
    <div class="vf-score">
      <div class="${s.hard ? "bad" : "good"}"><b>${s.hard}</b><span>hard ${s.hard === 1 ? "fault" : "faults"}</span></div>
      <div class="${s.soft ? "warn" : "good"}"><b>${s.soft}</b><span>soft ${s.soft === 1 ? "fault" : "faults"}</span></div>
      <div><b>${Math.round(s.cost).toLocaleString()}</b><span>ft of 2x4, the cost</span></div>
    </div>
    <p class="vf-p muted">Frames are compared by hard faults first (unbuildable or unsafe), then soft faults (details a good grammar
      also gets right), then cost: a cheaper frame never beats one with fewer faults.</p>
    ${costHtml()}
    ${st.only ? `<p class="vf-only">The 3D faults view and the surfaces show only <b>${esc(st.only)}</b> faults. <a href="#" data-only="${esc(st.only)}">Show all</a></p>` : ""}
  </div>`;
}

// which checks the table lists
const SHOW = { all: ["All", () => true], faults: ["With faults", (c, n) => n > 0], hard: ["Hard", (c) => c.hard], soft: ["Soft", (c) => !c.hard] };

function citesHtml(c) {
  // the code sections a check cites, the first in full and the rest on hover
  const refs = c.code.map((x) => x.trim());
  if (!refs.length) return `<span class="muted">-</span>`;
  return `<span title="${esc(refs.join("\n"))}">${esc(refs[0])}${refs.length > 1 ? ` <span class="muted">+${refs.length - 1}</span>` : ""}</span>`;
}

function limitHtml(c) {
  // one limit's value in full; several as a count, read in the check's detail
  if (!c.limits.length) return `<span class="muted">-</span>`;
  if (c.limits.length === 1) {
    const t = limitText(c.limits[0]);
    return `<span title="${esc(c.limits[0])}: ${esc(t)}">${esc(t.length > 26 ? t.slice(0, 25) + "..." : t)}</span>`;
  }
  return `<span class="muted" title="${esc(c.limits.join(", "))}">${c.limits.length} limits</span>`;
}

function rowHtml(c, wide, most) {
  const t = tally(byCheck()[c.name] || []), sel = st.check === c.name;
  const w = t.n ? Math.max(2, Math.round(100 * t.n / most)) : 0;
  return `<tr class="vf-row ${sel ? "sel" : ""} ${t.n ? "has" : ""}" data-check="${esc(c.name)}">
      <td><span class="tag ${c.hard ? "" : "soft"}">${c.hard ? "hard" : "soft"}</span></td>
      <td class="vf-cname">${esc(c.name)}${st.only === c.name ? ` <span class="vf-onlytag" title="the 3D faults view and the surfaces show only these">only</span>` : ""}</td>
      <td class="vf-meaning">${esc(cap(c.meaning))}</td>
      <td class="vf-limit">${limitHtml(c)}</td>
      <td class="vf-cites">${citesHtml(c)}</td>
      <td class="vf-n"><span class="vf-bar"><i class="${t.hard ? "bad" : "warn"}" style="width:${w}%"></i></span>
        <span class="vf-count ${t.n ? (t.hard ? "bad" : "warn") : "good"}">${t.n || "none"}</span></td>
    </tr>${sel && !wide ? `<tr class="vf-inrow"><td colspan="6"><div class="vf-inline">${detailHtml(c)}</div></td></tr>` : ""}`;
}

function tableHtml(mods, wide) {
  // every check in one table, under the question its module asks
  const by = byCheck(), all = mods.flatMap((m) => m.checks);
  const most = Math.max(1, ...all.map((c) => (by[c.name] || []).length));
  const keep = (c) => SHOW[st.vShow][1](c, (by[c.name] || []).length);
  const filter = Object.entries(SHOW).map(([k, [label, f]]) => {
    const n = all.filter((c) => f(c, (by[c.name] || []).length)).length;
    return `<button class="vf-by-b ${st.vShow === k ? "on" : ""}" data-show="${k}">${label} <span>${n}</span></button>`;
  }).join("");
  const groups = mods.map((m) => {
    const cs = m.checks.filter(keep);
    if (!cs.length) return "";
    const t = tally(m.checks.flatMap((c) => by[c.name] || []));
    const sum = t.n ? [t.hard && `<span class="bad">${t.hard} hard</span>`, t.soft && `<span class="warn">${t.soft} soft</span>`].filter(Boolean).join(", ")
      : `<span class="good">all clear</span>`;
    return `<tbody><tr class="vf-group ${st.vMod === m.name ? "sel" : ""}" data-mod="${esc(m.name)}" title="What this module asks and how">
        <th colspan="5"><span class="vf-q">${esc(m.question)}</span> <span class="vf-file">${m.name === "other" ? "" : `${esc(m.name)}.py`}</span>
          <span class="muted">${plural(m.checks.length, "check")}</span></th><th class="vf-msum">${sum}</th></tr>
      ${cs.map((c) => rowHtml(c, wide, most)).join("")}</tbody>`;
  }).join("");
  return `<div class="vf-tools"><span class="lab">Checks</span>${filter}</div>
    <table class="vf-table"><colgroup><col class="c-kind"><col class="c-name"><col><col class="c-limit"><col class="c-cites"><col class="c-n"></colgroup>
      <thead><tr><th></th><th>check</th><th>what it finds</th><th>limit</th><th>cites</th><th>on this frame</th></tr></thead>
      ${groups || `<tbody><tr><td colspan="6" class="muted">No checks of this kind.</td></tr></tbody>`}</table>`;
}

function moduleDetailHtml(m) {
  // one module: the question it asks, its description in full, and its checks
  const by = byCheck();
  return `<div class="vf-detail">
    <div class="vf-dhead"><h3>${esc(m.question)}</h3><span class="vf-file">${esc(m.name)}.py</span><span class="spacer"></span>
      <button class="vf-close" data-close title="Close">&#x2715;</button></div>
    <div class="vf-doc">${docHtml(paragraphs(m.doc))}</div>
    ${m.checks.length ? `<h4>Its checks</h4>${m.checks.map((c) => `<div class="vf-check ${by[c.name] ? "has" : ""}" data-check="${esc(c.name)}">
      <span class="tag ${c.hard ? "" : "soft"}">${c.hard ? "hard" : "soft"}</span><span class="vf-cname">${esc(c.name)}</span>
      <span class="vf-count ${by[c.name] ? (c.hard ? "bad" : "warn") : "good"}">${by[c.name]?.length || "none"}</span>
      <span class="vf-meaning">${esc(cap(c.meaning))}</span></div>`).join("")}` : ""}
  </div>`;
}

function faultHtml(c, i) {
  const f = st.data.faults[i], sel = st.fault === i;
  const other = f.hard !== c.hard ? `<span class="tag ${f.hard ? "" : "soft"}">${f.hard ? "hard" : "soft"}</span> ` : "";
  if (!sel) return `<div class="vf-fault" data-fault="${i}">${other}${esc(f.message)}</div>`;
  const members = f.members.filter((id) => st.byId[id]).map(chip).join("");
  const rules = f.rules.map((r) => `<span class="chip" data-rule="${esc(r)}"><i style="background:${st.colors[r] || "#999"}"></i>${esc(r)}</span>`).join("");
  const s = f.surface && st.surf[f.surface], ev = evidence(f).text;
  return `<div class="vf-fault sel" data-fault="${i}">${other}${esc(f.message)}
    <div class="vf-explain">
      ${ev !== `${esc(f.message)}.` ? `<div class="vf-ev">${ev}</div>` : ""}
      <div class="vf-chips">${members}${rules || (f.members.length ? "" : `<span class="muted">nothing was placed here, so no rule to blame</span>`)}</div>
      <div class="vf-acts">
        ${f.at ? `<button class="primary" data-act="3d" title="The 3D view, close to it, in the faults view">Show in 3D</button>` : ""}
        ${s ? `<button data-act="surface" title="Its ${esc(kindName(s))} in the Surfaces tab, with the evidence drawn">Show on ${esc(f.surface)}</button>` : ""}
      </div>
    </div></div>`;
}

function faultsHtml(c) {
  const idx = byCheck()[c.name] || [];
  if (!idx.length) return `<p class="good">None on this frame.</p>`;
  const fs = st.data.faults;
  const count = (key) => {
    const n = new Map();
    for (const i of idx) for (const k of key(fs[i])) n.set(k, (n.get(k) || 0) + 1);
    return [...n].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]), undefined, { numeric: true }));
  };
  const ruleKeys = (f) => (f.rules.length ? f.rules : [""]);
  const rules = count(ruleKeys), surfs = count((f) => [f.surface || ""]);
  const { rule, surface } = st.vFilter;
  const shown = idx.filter((i) => (rule == null || ruleKeys(fs[i]).includes(rule)) && (surface == null || (fs[i].surface || "") === surface));
  const surfName = (sid) => (sid ? sid : "the whole frame");
  const chips = (list, attr, on) => list.map(([k, n]) => `<button class="vf-by-b ${on === k ? "on" : ""}" data-${attr}="${esc(k)}">${attr === "frule" && k ? `<i style="background:${st.colors[k] || "#999"}"></i>` : ""}${esc(k || (attr === "frule" ? "no rule" : "whole frame"))} <span>${n}</span></button>`).join("");
  // grouped by surface, the largest group first, listing at most st.vCap faults
  const groups = new Map();
  for (const [sid] of surfs) groups.set(sid, []);
  for (const i of shown) groups.get(fs[i].surface || "").push(i);
  let left = st.vCap, out = "";
  for (const [sid, list] of groups) {
    if (!list.length || left <= 0) continue;
    const s = st.surf[sid];
    out += `<div class="vf-surf"><b>${esc(surfName(sid))}</b>${s ? ` <span class="muted">${esc(kindName(s))}${st.level[sid] ? `, storey ${st.level[sid]}` : ""}</span>` : ""}<span class="n">${list.length}</span></div>`;
    out += list.slice(0, left).map((i) => faultHtml(c, i)).join("");
    left -= list.length;
  }
  const more = shown.length - st.vCap;
  return `<p class="vf-p">${plural(idx.length, "fault")} on ${plural(surfs.filter(([k]) => k).length, "surface")}${rules.some(([k]) => k) ? `, from ${plural(rules.filter(([k]) => k).length, "rule")}` : ""}.
      <span class="muted">Click a fault for its evidence.</span></p>
    ${rules.length > 1 || rule != null ? `<div class="vf-by"><span class="lab">by rule</span>${chips(rules, "frule", rule)}</div>` : ""}
    ${surfs.length > 1 || surface != null ? `<div class="vf-by"><span class="lab">by surface</span>${chips(surfs, "fsurf", surface)}</div>` : ""}
    ${rule != null || surface != null ? `<p class="vf-p muted">${shown.length} of ${idx.length} shown. <a href="#" data-unfilter>Show all</a></p>` : ""}
    <div class="vf-faults">${out}</div>
    ${more > 0 ? `<button class="vf-showmore" data-more>Show ${Math.min(more, 2 * PAGE)} more <span class="muted">of ${more}</span></button>` : ""}`;
}

function detailHtml(c) {
  const vi = st.vinfo, idx = byCheck()[c.name] || [];
  const mod = modules().find((m) => m.checks.includes(c));
  const lims = c.limits.map((n) => {
    const k = vi.constants[n];
    return `<div class="vf-lim"><code>${esc(n)}</code><b>${esc(limitText(n))}</b>${k?.note ? `<span>${esc(k.note)}</span>` : ""}</div>`;
  });
  const limHtml = lims.slice(0, 4).join("") + (lims.length > 4 ? `<details data-key="d:lims" ${st.vOpen.has("d:lims") ? "open" : ""}>
    <summary>${lims.length - 4} more</summary><div class="vf-lims">${lims.slice(4).join("")}</div></details>` : "");
  return `<div class="vf-detail">
    <div class="vf-dhead"><span class="tag ${c.hard ? "" : "soft"}">${c.hard ? "hard" : "soft"}</span><h3>${esc(c.name)}</h3>
      <span class="vf-count ${idx.length ? (c.hard ? "bad" : "warn") : "good"}">${idx.length ? plural(idx.length, "fault") : "none"}</span>
      <span class="spacer"></span>
      ${idx.length ? `<button class="only ${st.only === c.name ? "on" : ""}" data-only="${esc(c.name)}" title="Show only this check's faults in the 3D faults view and on the surfaces">${st.only === c.name ? "showing only these" : "only these"}</button>` : ""}
      <button class="vf-close" data-close title="Close">&#x2715;</button></div>
    <p class="vf-big">${esc(cap(c.meaning || "a check the verifier does not describe"))}.</p>
    <p class="vf-p muted">${mod && mod.name !== "other" ? `Asked under <i>${esc(mod.question)}</i> (${esc(mod.name)}.py). ` : ""}${c.hard
      ? "Hard: a fault here makes the frame unbuildable or unsafe."
      : "Soft: a detail a good grammar also gets right; it weighs less than any hard fault, more than any cost."}</p>
    ${lims.length ? `<h4>Limits</h4><div class="vf-lims">${limHtml}</div>` : ""}
    ${c.code.length ? `<p class="code-ref">Approximates ${c.code.map((x) => esc(x.trim())).join(", ")}.</p>` : ""}
    <h4>On this frame</h4>
    ${faultsHtml(c)}
  </div>`;
}

function asideHtml() {
  // the side column with nothing chosen: what the verifier is, in its own words
  return `<div class="vf-detail vf-none">
    <p class="vf-p muted">Choose a check for its limits, the code it cites and its faults on this frame, or a question for what
      its module asks and how.</p>
    <h4>The verifier</h4><div class="vf-doc">${docHtml(paragraphs(st.vinfo.about).filter((p) => !/\.py\s{2,}|:$/.test(p)))}</div>
  </div>`;
}

export function renderVerifier() {
  const el = $("#verifier");
  if (!st.data || !st.vinfo) { el.innerHTML = `<p class="empty vf-wait">Loading the verifier...</p>`; return; }
  const mods = modules();
  const c = st.check && mods.flatMap((m) => m.checks).find((x) => x.name === st.check);
  if (!c) st.check = null;
  const mod = !c && st.vMod && mods.find((m) => m.name === st.vMod);
  if (!mod) st.vMod = null;
  const wide = el.clientWidth >= WIDE;
  // keep where the reader is: each column's scroll, except a newly chosen check's column starts at its top
  const tops = [...el.querySelectorAll(".vf-col")].map((x) => x.scrollTop), top = el.scrollTop;
  const shown = st.check || (st.vMod ? "mod:" + st.vMod : "");
  const sameCheck = el.dataset.shown === shown && el.classList.contains("wide") === wide;
  el.classList.toggle("wide", wide);
  el.dataset.shown = shown;
  const main = headHtml() + (!wide && mod ? `<div class="vf-inline">${moduleDetailHtml(mod)}</div>` : "") + tableHtml(mods, wide);
  el.innerHTML = wide ? `<div class="vf-col vf-main">${main}</div><div class="vf-col vf-side">${c ? detailHtml(c) : mod ? moduleDetailHtml(mod) : asideHtml()}</div>`
    : `<div class="vf-main">${main}</div>`;
  const cols = el.querySelectorAll(".vf-col");
  if (wide && tops.length === 2) { cols[0].scrollTop = tops[0]; if (sameCheck) cols[1].scrollTop = tops[1]; }
  el.scrollTop = top;
}

function chooseCheck(n) {
  st.check = st.check === n ? null : n;
  st.vMod = null;
  st.vFilter = { rule: null, surface: null };
  st.vCap = PAGE;
  renderVerifier();
}

export function setOnly(n) {
  st.only = st.only === n ? null : n;
  renderMarks();
  look3d();
  renderElev();
  renderVerifier();
  renderSide();
}

function showIn(where) {
  // the chosen fault in 3D (close to it, in the faults view) or on its surface in the Surfaces tab
  const f = chosenFault();
  if (!f) return;
  if (st.only && st.only !== f.check) { st.only = f.check; renderMarks(); renderSide(); }
  if (!finished()) goto(Infinity);
  if (where === "3d") {
    setView("faults");
    zoomTo(f.at);
  } else {
    if (st.storey && !listed(f.surface)) { st.storey = 0; renderStoreys(); look3d(); }
    renderElev();
    showTab("elev");
    scrollElevTo(f.surface, { block: "center" });
  }
}

$("#verifier").addEventListener("click", (e) => {
  const t = e.target;
  const only = t.closest("[data-only]");
  if (only) { e.preventDefault(); return setOnly(only.dataset.only); }
  const act = t.closest("button[data-act]");
  if (act) return showIn(act.dataset.act);
  if (t.closest("[data-close]")) { if (st.check) return chooseCheck(st.check); st.vMod = null; return renderVerifier(); }
  const show = t.closest("[data-show]");
  if (show) { st.vShow = show.dataset.show; return renderVerifier(); }
  if (t.closest("[data-more]")) { st.vCap += 2 * PAGE; return renderVerifier(); }
  if (t.closest("[data-unfilter]")) { e.preventDefault(); st.vFilter = { rule: null, surface: null }; st.vCap = PAGE; return renderVerifier(); }
  const fr = t.closest("[data-frule]"), fs = t.closest("[data-fsurf]");
  if (fr || fs) {
    const k = fr ? "rule" : "surface", v = (fr || fs).dataset[fr ? "frule" : "fsurf"];
    st.vFilter[k] = st.vFilter[k] === v ? null : v;
    st.vCap = PAGE;
    return renderVerifier();
  }
  const c = t.closest(".chip[data-id]");
  if (c && st.byId[c.dataset.id]) return select({ kind: "member", id: c.dataset.id });
  const r = t.closest(".chip[data-rule]");
  if (r) return select({ kind: "rule", id: r.dataset.rule });
  if (t.closest("a, button, summary, .vf-explain")) return;
  const fi = t.closest("[data-fault]");
  if (fi) return chooseFault(+fi.dataset.fault);
  const ch = t.closest("[data-check]");
  if (ch) return chooseCheck(ch.dataset.check);
  const mh = t.closest("[data-mod]");
  if (mh) {
    st.vMod = st.vMod === mh.dataset.mod ? null : mh.dataset.mod;
    st.check = null;
    renderVerifier();
  }
});

// details remember being open across repaints ("toggle" does not bubble, so listen on the way down)
$("#verifier").addEventListener("toggle", (e) => {
  const k = e.target.dataset?.key;
  if (k) e.target.open ? st.vOpen.add(k) : st.vOpen.delete(k);
}, true);

// a chosen check moves between its own column and under its row as the tab's width allows
new ResizeObserver(() => {
  const el = $("#verifier");
  if (el.clientWidth && (el.clientWidth >= WIDE) !== el.classList.contains("wide")) renderVerifier();
}).observe($("#verifier"));
