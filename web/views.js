// The view switch in the 3D view bar, the one way to change what the 3D view shows: build (members by rule,
// the timeline steps through the rule firings), panels (by prefab panel; pick one from the list), assembly (the
// erection order, stepped through on the timeline) and faults (members in faults, the rest a ghost). Here:
// the switch, the left column's list for each view (the rules stay in app.js), the panel inspector, and the
// assembly's state, track and caption. view3d.js paints from `asmState` and `related`.
import { $, esc, ftin, pill, st, SITE, finished, stopPlay, remember, panelColour, kindName, runsMode } from "./state.js";
import { select, renderRules } from "./app.js";
import { look3d, frameMembers } from "./view3d.js";
import { renderElev, renderCaption } from "./elevations.js";
import { renderTimeline, renderInspect } from "./inspect.js";
import { setOnly } from "./verifier.js";

const VIEWS = ["build", "panels", "assembly", "faults"];

export function setView(v) {
  st.view = VIEWS.includes(v) ? v : "build";
  remember("view", st.view);
  stopPlay();
  st.hoverPanel = null;
  if (st.sel?.kind === "panel" && st.view !== "panels") st.sel = null;
  $("#viewSwitch").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.view === st.view));
  for (const x of VIEWS) document.body.classList.toggle("view-" + x, x === st.view);
  if (!st.data) return;
  if (st.view !== "build") st.at = 2 * st.data.steps.length;   // the other views show the finished frame
  renderRules();
  renderSide();
  look3d();
  renderElev();
  renderTimeline();
  renderCaption();
  renderInspect();
}

$("#viewSwitch").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-view]");
  if (b && b.dataset.view !== st.view) setView(b.dataset.view);
});

// ---------------------------------------------------------------- what the views read, worked out once per frame

let ix = { data: null };
function index() {
  const d = st.data;
  if (ix.data === d) return ix;
  const live = d.members.filter((m) => !m.removed);
  // panels: as the server lists them, or (an older server) gathered from the members, without size or weight
  const counts = {};
  for (const m of live) if (m.panel) counts[m.panel] = (counts[m.panel] || 0) + 1;
  const panels = d.panels || Object.keys(counts).map((name) => ({ name, surface: live.find((m) => m.panel === name).surface, members: counts[name] }));
  const byName = new Map(panels.map((p) => [p.name, p]));
  const faults = {};   // panel -> indices of the faults that involve its members
  d.faults.forEach((f, i) => {
    for (const p of new Set(f.members.map((id) => st.byId[id]?.panel).filter(Boolean))) (faults[p] ||= []).push(i);
  });
  const order = d.assembly || null;
  const unitAt = new Map(), memberAt = new Map();
  order?.forEach((u, i) => { unitAt.set(u.unit, i); for (const id of u.members) memberAt.set(id, i); });
  ix = { data: d, panels, byName, faults, site: live.filter((m) => !m.panel).length, order, unitAt, memberAt };
  return ix;
}

const sizeText = (p) => (p.size ? `${ftin(p.size[0])} x ${ftin(p.size[1])}` : "");
const weightText = (p) => (p.weight != null ? `${Math.round(p.weight).toLocaleString()} lb` : "");
const surfText = (sid) => { const s = st.surf[sid]; return s ? `${kindName(s)} ${sid}` : sid || ""; };
const unitColour = (u) => (u.panel ? panelColour(u.unit) : SITE);
function unitName(name) {
  // a panel by its name, a piece built on site by its member id and role
  const m = st.byId[name];
  return m ? `${name} ${m.role || m.rule}` : name;
}
function unitList(names, max = 6) {
  const shown = names.slice(0, max).map((n) => `<b>${esc(n)}</b>`).join(", ");
  return names.length > max ? `${shown} and ${names.length - max} more` : shown;
}

// ---------------------------------------------------------------- the left column: the list for the view

export function renderSide() {
  const v = st.view;
  $("#rulesSec").hidden = v !== "build";
  $("#viewSec").hidden = v === "build";
  if (v === "build" || !st.data) return;
  const [title, hint, html] = v === "panels" ? panelsSide() : v === "assembly" ? asmSide() : faultsSide();
  $("#viewTitle").innerHTML = title;
  $("#viewHint").textContent = hint;
  const list = $("#viewList");
  list.innerHTML = html;
  list.querySelector(".now")?.scrollIntoView({ block: "nearest" });
}

function panelsSide() {
  const x = index();
  if (!x.panels.length) return ["Panels", "", `<p class="empty">This grammar builds no prefab panels: every piece is cut and nailed on site.</p>`];
  const bySurf = {};
  for (const p of x.panels) (bySurf[p.surface] ||= []).push(p);
  const num = (a, b) => a.localeCompare(b, undefined, { numeric: true });
  const surfs = Object.keys(bySurf).sort((a, b) => (st.level[a] ?? 9) - (st.level[b] ?? 9) || num(a, b));
  const sel = st.sel?.kind === "panel" ? st.sel.id : null;
  const html = surfs.map((sid) => `<li class="grp">${esc(sid)} <span>${esc(st.surf[sid] ? `${kindName(st.surf[sid])}, storey ${st.level[sid]}` : "")}</span></li>` +
    bySurf[sid].sort((a, b) => num(a.name, b.name)).map((p) => {
      const nf = x.faults[p.name]?.length;
      const meta = [sizeText(p), weightText(p), `${p.members} members`].filter(Boolean).join(", ");
      return `<li data-panel="${esc(p.name)}" class="${sel === p.name ? "sel" : ""}"><span class="sw" style="background:${panelColour(p.name)}"></span>
        <span class="nm">${esc(p.name)}<small>${esc(meta)}</small></span>${nf ? `<span class="bad" title="faults involving its members">${nf}!</span>` : ""}</li>`;
    }).join("")).join("");
  return [`Panels <small>${x.panels.length}, by surface</small>`,
    `Point at one to see it, click to pick it out and look at it. ${x.site ? `${x.site} pieces are built on site (grey).` : ""}`, `<ul class="vlist">${html}</ul>`];
}

function asmSide() {
  const x = index();
  if (!x.order) return ["Assembly", "", `<p class="empty">This server does not send the erection order; restart it on the current code.</p>`];
  const k = st.asm;
  const html = x.order.map((u, i) => {
    const m = !u.panel && st.byId[u.unit];
    const p = u.panel && x.byName.get(u.unit);
    const where = p ? surfText(p.surface) : m ? `on site, ${surfText(m.surface)}` : "";
    const flag = u.blocked ? `<span class="flag bad">blocked</span>` : u.waits?.length ? `<span class="flag warn">waits</span>` : "";
    return `<li data-unit="${i}" class="${i === k ? "now" : ""} ${i > k ? "notyet" : ""} ${u.panel ? "" : "site"}" style="--c:${unitColour(u)}">
      <span class="no">${i + 1}</span><span class="sw" style="background:${unitColour(u)}"></span>
      <span class="nm">${esc(u.panel ? u.unit : unitName(u.unit))}<small>${esc(where)}</small></span>${flag}</li>`;
  }).join("");
  const bad = x.order.filter((u) => u.blocked || u.waits?.length).length;
  return [`Assembly <small>${x.order.length} lifts and pieces, lowest first</small>`,
    `The order the verifier can put the house up in, each on what is already up. Step through it below the view.${bad ? ` ${bad} cannot go up as they should (red, amber).` : ""}`,
    `<ul class="vlist">${html}</ul>`];
}

function faultsSide() {
  const by = {};
  for (const f of st.data.faults) (by[f.check] ||= { n: 0, hard: f.hard }).n++;
  const names = (st.vinfo?.checks.map((c) => c.name) || []).filter((n) => by[n]);
  for (const n of Object.keys(by)) if (!names.includes(n)) names.push(n);
  const row = (n, label, count, hard) => `<li data-only="${esc(n)}" class="${(st.only || "") === n ? "sel" : ""}">
    ${hard == null ? `<span class="sw"></span>` : `<span class="tag ${hard ? "" : "soft"}">${hard ? "hard" : "soft"}</span>`}
    <span class="nm">${esc(label)}</span><span class="ct">${count}</span></li>`;
  return [`Faults <small>members in faults, by check</small>`,
    "Hard faults in red, soft in amber, everything else a ghost. Pick a check to see only its faults; the Verifier tab explains each.",
    `<ul class="vlist">${row("", "every check", st.data.faults.length, null)}${names.map((n) => row(n, n, by[n].n, by[n].hard)).join("")}</ul>`];
}

{
  const list = $("#viewList");
  list.addEventListener("click", (e) => {
    const p = e.target.closest("[data-panel]");
    if (p) return choosePanel(p.dataset.panel, true);
    const u = e.target.closest("[data-unit]");
    if (u) { stopPlay(); return asmGo(+u.dataset.unit); }
    const o = e.target.closest("[data-only]");
    if (o) return setOnly(o.dataset.only ? o.dataset.only : st.only);
  });
  list.addEventListener("mouseover", (e) => {
    const p = e.target.closest("[data-panel]")?.dataset.panel ?? null;
    if (st.view === "panels" && p !== st.hoverPanel) { st.hoverPanel = p; if (!st.sel) { look3d(); renderElev(); } }
  });
  list.addEventListener("mouseleave", () => {
    if (st.hoverPanel == null) return;
    st.hoverPanel = null;
    if (!st.sel) { look3d(); renderElev(); }
  });
}

// ---------------------------------------------------------------- panels

export function choosePanel(name, zoom) {
  // pick a panel out (again: let it go); from the list, the 3D view comes close to it
  const again = st.sel?.kind === "panel" && st.sel.id === name;
  if (st.view !== "panels" && !again) setView("panels");
  select(again || !name ? null : { kind: "panel", id: name });
  if (!again && name && zoom) frameMembers(st.data.members.filter((m) => m.panel === name && !m.removed).map((m) => m.id));
}

export function clickMember(id) {
  // a click on a member in 3D: the panels view picks its panel, the assembly view goes to the step it goes up in.
  // False when the view leaves the click to the usual selection.
  if (st.view === "panels") { choosePanel(st.byId[id]?.panel || null, false); return true; }
  if (st.view === "assembly" && index().memberAt.has(id)) { stopPlay(); asmGo(index().memberAt.get(id)); return true; }
  return false;
}

export function panelHtml(name) {
  const x = index(), p = x.byName.get(name) || { name, members: 0 };
  const ms = st.data.members.filter((m) => m.panel === name && !m.removed);
  const secs = {};
  for (const m of ms) secs[m.section] = (secs[m.section] || 0) + 1;
  const fs = (x.faults[name] || []).map((i) => st.data.faults[i]);
  const at = x.unitAt.get(name), u = at != null && x.order[at];
  return `<div class="title"><span class="sw" style="background:${panelColour(name)}"></span>panel ${esc(name)}</div>
    <table class="kv">
      <tr><td>surface</td><td>${esc(surfText(p.surface))}${st.level[p.surface] ? `, storey ${st.level[p.surface]}` : ""}</td></tr>
      ${p.size ? `<tr><td>size</td><td>${ftin(p.size[0])} x ${ftin(p.size[1])}, ${ftin(p.size[2])} deep</td></tr>` : ""}
      ${p.weight != null ? `<tr><td>weight</td><td>${weightText(p)}</td></tr>` : ""}
      <tr><td>members</td><td>${ms.length} <span class="muted">(${Object.entries(secs).map(([k, n]) => `${n} ${esc(k)}`).join(", ")})</span></td></tr>
      ${u ? `<tr><td>goes up</td><td>step ${at + 1} of ${x.order.length}${u.rests_on.length ? `, on ${unitList(u.rests_on)}` : ", on the ground"}
        <button class="edit" data-asm="${at}" title="Step through the assembly from here">show</button></td></tr>` : ""}
      ${u?.blocked ? `<tr><td></td><td class="bad">blocked: ${esc(u.blocked[0])} of ${esc(u.blocked_by || "?")} is over ${esc(u.blocked[1])}</td></tr>` : ""}
      ${u?.waits?.length ? `<tr><td></td><td class="warn">waits for ${unitList(u.waits)}, which rest on it too</td></tr>` : ""}
    </table>
    <h4>Faults <small>${fs.length ? `${fs.length} involving its members` : "none"}</small></h4>
    ${fs.slice(0, 30).map((f) => `<p class="${f.hard ? "bad" : ""}"><span class="tag ${f.hard ? "" : "soft"}">${esc(f.check)}</span> ${esc(f.message)}</p>`).join("")}
    ${fs.length > 30 ? `<p class="muted">and ${fs.length - 30} more, in the Verifier tab</p>` : ""}`;
}

// ---------------------------------------------------------------- assembly

export function asmGo(k) {
  const n = index().order?.length || 0;
  st.asm = Math.max(0, Math.min(n, k));
  renderTimeline();
  renderCaption();
  renderSide();
  look3d();
}

export function asmState() {
  // id -> "up" (in place before this step), "now" (going up), "under" (what it rests on), "wait" (what it rests on
  // that is not up yet), "block" (the member in the way); members after it are left out (not up yet). `all` once
  // the whole order is up.
  const x = index(), A = x.order || [], k = Math.min(st.asm, A.length), of = new Map();
  for (let i = 0; i < k; i++) for (const id of A[i].members) of.set(id, "up");
  const u = A[k];
  if (u) {
    for (const r of u.rests_on) {
      const j = x.unitAt.get(r);
      if (j != null) for (const id of A[j].members) of.set(id, j < k ? "under" : "wait");
    }
    for (const id of u.members) of.set(id, "now");
    if (u.blocked) of.set(u.blocked[0], "block");
  }
  return { of, all: k >= A.length };
}

export const asmTrack = {
  get key() { return index().order || []; },
  get count() { return index().order?.length || 0; },
  zero: false,
  brk(i) {
    // a wider gap where the order moves up a storey
    const A = index().order, lv = (u) => st.level[u.panel ? index().byName.get(u.unit)?.surface : st.byId[u.unit]?.surface] ?? 0;
    return lv(A[i]) !== lv(A[i - 1]) ? 2 : 1;
  },
  look(i) {
    const u = index().order[i];
    return [u.blocked ? "#d8342c" : u.waits?.length ? "#e08a00" : unitColour(u), null];
  },
  at: () => st.asm,
  get max() { return index().order?.length || 0; },
  cursor: () => st.asm,
  go: (i) => asmGo(i),
  tip(i) {
    const u = index().order[i];
    return `step ${i + 1}: ${u.panel ? `panel ${esc(u.unit)}` : `${esc(unitName(u.unit))}, built on site`}${u.blocked ? ", blocked" : u.waits?.length ? ", waits" : ""}`;
  },
  label() {
    const n = index().order?.length || 0;
    return !index().order ? "no erection order" : st.asm >= n ? `<b>all up</b>, ${n} steps` : `<b>step ${st.asm + 1}</b> of ${n}`;
  },
};

export function asmCaption(el) {
  // the caption over the view while stepping through the assembly
  const x = index(), A = x.order, k = st.asm, u = A?.[k];
  if (!u || runsMode()) { el.hidden = true; return; }
  el.hidden = false;
  const p = u.panel && x.byName.get(u.unit), m = !u.panel && st.byId[u.unit];
  const what = u.panel ? `panel ${pill(u.unit, unitColour(u))} <span class="muted">(${esc(surfText(p?.surface))})</span>`
    : `${pill(unitName(u.unit), "#f28e2b")} <span class="muted">built on site${m ? `, ${esc(surfText(m.surface))}` : ""}</span>`;
  const bad = [
    u.waits?.length ? `waits for ${unitList(u.waits)}: they rest on it too, so there is no order` : "",
    u.blocked ? `blocked: ${esc(u.blocked[0])} of ${esc(u.blocked_by || "?")} is over ${esc(u.blocked[1])}, so it cannot be lowered in` : "",
  ].filter(Boolean);
  el.innerHTML = `<div class="c-top">step ${k + 1} of ${A.length}${p?.weight != null ? `, ${weightText(p)}` : ""}</div>
    <div class="c-main">${what}, rests on ${u.rests_on.length ? unitList(u.rests_on) : "the ground"}</div>
    ${bad.map((b) => `<div class="c-bad">${b}</div>`).join("")}`;
}
