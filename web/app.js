// FrameEvolve workbench. One page: pick a house and a grammar, build, look at the frame in 3D and in
// elevation, step through the build rule by rule, inspect members and their contacts, read faults, edit the
// grammar and rebuild. The Runs view shows the search: progress, the grammars it kept, what the proposer did,
// and starts or stops searches and the tests.
//
// This is the entry: the build (streamed from the server and drawn as it happens), the index of a loaded
// frame, what repaints when, the stats and rules on the left, the tabs, the header and the keys. The views
// live in their own modules: state.js, view3d.js, views.js, elevations.js, verifier.js, inspect.js, editor.js, runs.js,
// live.js.
import * as THREE from "three";
import { $, esc, num, oneLine, PALETTE, SITE, st, finished, applied, trigger, current, present, runsMode, stopPlay, api,
  status, remember, recall, loadLists, dirty, surfaceList, hideTip, byPanel } from "./state.js";
import "./houses.js";
import { setup3d, resize, render3d, look3d, renderSurfaces, fit, startLiveDraw, addMember, removeMember, edgeMaterial,
  measuring, setMeasure, meshes } from "./view3d.js";
import { renderElev, renderStoreys, renderCaption, scrollElevTo } from "./elevations.js";
import { renderInspect, renderReport, renderTimeline, stepBy } from "./inspect.js";
import { renderVerifier, chooseFault } from "./verifier.js";
import { setView, renderSide } from "./views.js";
import { loadGrammar } from "./editor.js";
import { rs, pollJobs, loadRunsList, enterRuns } from "./runs.js";
import { startLive, setFollow } from "./live.js";

// ---------------------------------------------------------------- build

// Build: frame the house from scratch and draw each piece the moment the server places it, at the build's
// own speed; the full frame and its verification follow when the build is done. True when it built.
let building = null;   // the build in progress: a new one (another house, Regenerate, an edit) ends it

export async function build(keepStep = false) {
  building?.abort();
  const mine = building = new AbortController();
  stopPlay();
  status("framing...");
  const was = st.data && !finished() ? st.at : null;   // a live draft rebuilds where the user is stepping
  const body = { house: $("#house").value, grammar: $("#grammar").value };
  if (dirty()) body.source = $("#src").value;
  const t0 = performance.now();
  let res;
  try {
    res = await fetch("/api/build", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: mine.signal });
  } catch (e) {
    if (mine.signal.aborted) return false;      // a newer build took over
    throw e;
  }
  if (!res.ok || !res.body) { status((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`, true); return false; }
  startLiveDraw();
  const colors = { ...st.colors }, panels = {}, edgeMat = edgeMaterial();
  const colorOf = (r) => colors[r] || (colors[r] = PALETTE[Object.keys(colors).length % PALETTE.length]);
  // by panel, a panel takes the next colour as it first appears; the finished frame orders them by name
  const panelOf = (p) => (!p ? SITE : panels[p] || (panels[p] = PALETTE[Object.keys(panels).length % PALETTE.length]));
  const live = (m) => (byPanel() ? panelOf(m.panel) : colorOf(m.rule));
  const put = (m) => addMember(m, new THREE.MeshStandardMaterial({ roughness: 0.85, color: live(m) }), edgeMat);
  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = "", pieces = 0, frame = null, built = 0;
  const handle = (msg) => {
    if (msg.house) {   // the house comes first: show its surfaces, and frame a new one in the view
      const h = msg.house;
      renderSurfaces([...h.walls, ...h.floors, ...h.roofs]);
      if (st.fitFor !== h.house) { st.fitFor = h.house; fit(); }
    } else if (msg.step) {
      for (const m of msg.step.placed) put(m);
      for (const m of msg.step.shaped) put(m);   // a new shape for a member a later rule cut or notched
      for (const id of msg.step.removed) removeMember(id);
      if (byPanel()) for (const a of msg.step.assigned || []) meshes.get(a.id)?.material.color.set(panelOf(a.panel));
      pieces += msg.step.placed.length - msg.step.removed.length;
      status(`framing: ${Math.round(1000 * msg.step.t)} ms, ${pieces} pieces, ${msg.step.rule}`);
    } else if (msg.built != null) {
      built = msg.built;
      status(`framed in ${Math.round(1000 * built)} ms, ${pieces} pieces; verifying...`);
    } else if (msg.frame) frame = msg.frame;
  };
  for (;;) {
    let got;
    try { got = await reader.read(); } catch (e) { if (mine.signal.aborted) return false; throw e; }
    if (mine.signal.aborted) return false;      // stopped: the server stops building when the page stops listening
    const { done, value } = got;
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const l of lines) if (l.trim()) handle(JSON.parse(l));
  }
  if (building === mine) building = null;
  if (!frame || frame.error) { status(frame?.error || "the build stopped before it finished", true); return false; }
  st.data = frame;
  index();
  if (keepStep && was != null) st.at = Math.min(was, 2 * st.data.steps.length);
  renderAll();
  const ms = (x) => `${Math.round(1000 * x)} ms`;
  status(`framed from scratch in ${ms(built)}, verified in ${ms(frame.timing.verify)}, ` +
         `${ms((performance.now() - t0) / 1000)} in all${dirty() ? ", from unsaved edits" : ""}`);
  return true;
}

function index() {
  const d = st.data;
  st.byId = Object.fromEntries(d.members.map((m) => [m.id, m]));
  st.surf = Object.fromEntries(surfaceList().map((x) => [x.id, x]));
  st.level = Object.fromEntries(surfaceList().map((x) => [x.id, x.storey]));
  st.fault = null;
  if (st.only && !d.faults.some((f) => f.check === st.only)) st.only = null;
  const names = d.rules.filter((r) => r.name).map((r) => r.name);
  for (const m of d.members) if (!names.includes(m.rule)) names.push(m.rule);
  st.colors = Object.fromEntries(names.map((n, i) => [n, PALETTE[i % PALETTE.length]]));
  st.counts = {};
  for (const m of d.members) if (!m.removed) st.counts[m.rule] = (st.counts[m.rule] || 0) + 1;
  st.faulty = new Set(d.faults.filter((f) => f.hard).flatMap((f) => f.members));
  st.ruleFaults = {};
  for (const f of d.faults) if (f.hard) for (const r of f.rules) st.ruleFaults[r] = (st.ruleFaults[r] || 0) + 1;
  st.placedAt = {};
  st.removedAt = {};
  d.steps.forEach((s, i) => {
    for (const id of s.placed) st.placedAt[id] = i;
    for (const id of s.removed) st.removedAt[id] = i;
  });
  for (const m of d.members) if (!(m.id in st.placedAt)) st.placedAt[m.id] = -1;
  d.guides ||= [];
  const panels = [...new Set(d.members.filter((m) => m.panel).map((m) => m.panel))]
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  st.panelColors = Object.fromEntries(panels.map((p, i) => [p, PALETTE[i % PALETTE.length]]));
  st.panelAt = {};
  st.guideAt = {};
  d.steps.forEach((s, i) => {
    for (const id of s.assigned || []) st.panelAt[id] = i;
    for (const id of s.guides || []) st.guideAt[id] = i;
  });
  for (const m of d.members) if (m.panel && !(m.id in st.panelAt)) st.panelAt[m.id] = st.placedAt[m.id];
  for (const g of d.guides) if (!(g.id in st.guideAt)) st.guideAt[g.id] = -1;
  st.at = 2 * d.steps.length;
  stopPlay();
  if (st.sel?.kind === "member" && !st.byId[st.sel.id]) st.sel = null;
  if (st.sel?.kind === "rule" && !names.includes(st.sel.id)) st.sel = null;
  if (st.sel?.kind === "panel" && !d.members.some((m) => m.panel === st.sel.id)) st.sel = null;
  st.asm = Math.min(st.asm, d.assembly?.length || 0);
}

function renderAll() {
  renderStats();
  renderRules();
  renderSide();
  render3d();
  renderElev();
  renderStoreys();
  renderInspect();
  renderVerifier();
  renderReport();
  renderTimeline();
  renderCaption();
}

// selection changes repaint only what depends on it
export function select(sel) {
  st.sel = sel;
  if (st.fault != null) { st.fault = null; renderVerifier(); }   // a selection replaces the fault being explained
  renderRules();
  renderSide();
  look3d();
  renderElev();
  renderInspect();
  if (sel) showTab("inspect");
}

// ---------------------------------------------------------------- left: stats and rules

function renderStats() {
  const s = st.data.stats;
  const rows = [
    ["hard faults", s.hard, s.hard ? "bad" : "good", "Unbuildable as drawn. A good grammar has none."],
    ["soft faults", s.soft, "", "Against code or good practice, but buildable."],
    ["cost", `${num(s.cost)} ft`, "", "Linear feet of 2x4 equivalent: timber bought, deeper sections weighted by depth, plus a fixed cost per piece."],
    ["timber bought", `${num(s.bought_ft)} ft`, "", "Linear feet bought in stock lengths."],
    ["waste", `${s.waste_pct} %`, "", "Offcuts, as a share of the timber bought."],
    ["members", s.members, "", "Pieces of timber in the finished frame."],
    ...(s.panels != null ? [["panels", s.panels, "", "Prefab panels built in the shop, trucked and lifted into place."]] : []),
    ...(s.site_pieces != null ? [["built on site", s.site_pieces, "", "Pieces in no panel: cut and nailed on site."]] : []),
    ["build steps", s.steps, "", "Rule firings that changed something. Step through them below the view."],
  ];
  $("#stats").innerHTML = rows.map(([k, v, kind, tip]) =>
    `<span class="k" title="${esc(tip)}">${k}</span><span class="v ${kind}" title="${esc(tip)}">${v}</span>`).join("");
  $("#faultCount").innerHTML = (s.hard ? `<i class="bad" title="hard faults">${s.hard}</i>` : "") +
    (s.soft ? `<i class="warn" title="soft faults">${s.soft}</i>` : "") + (s.hard + s.soft ? "" : `<i class="good" title="no faults">0</i>`);
}

export function renderRules() {
  const ul = $("#rules");
  const rules = st.data.rules;
  if (rules[0]?.error) {
    ul.innerHTML = `<li class="bad">${esc(rules[0].error)}</li>`;
    $("#rulesHint").textContent = "Fix the grammar in the Grammar tab, then build.";
    return;
  }
  if (!rules.length) {
    ul.innerHTML = "";
    $("#rulesHint").textContent = "No rules in this grammar. A rule is a function marked @rule(priority).";
    return;
  }
  const done = finished();
  const cur = current();
  const fired = new Set(st.data.steps.slice(0, applied()).map((s) => s.rule));
  let counts = st.counts;
  if (!done) {
    counts = {};
    for (const m of st.data.members) if (present(m.id)) counts[m.rule] = (counts[m.rule] || 0) + 1;
  }
  $("#rulesHint").textContent = done ? "Click a rule to see what it does and highlight its members."
    : st.at === 0 ? "Step 0: no rule has fired yet."
    : "Marked: the rule at this step. Faded: not fired yet. Grey: what each rule matches.";
  ul.innerHTML = rules.map((r, i) => {
    const isNow = cur?.rule === r.name;
    const cls = [st.sel?.kind === "rule" && st.sel.id === r.name ? "sel" : "", st.hidden.has(r.name) ? "off" : "",
      isNow ? "now" : "", !done && !fired.has(r.name) ? "notyet" : ""].join(" ");
    return `<li data-rule="${esc(r.name)}" class="${cls}" style="--c:${st.colors[r.name]}" title="${esc(oneLine(r.doc))}">
      <span class="no" title="rule ${i + 1}, in the order the builder tries them">${i + 1}</span>
      <span class="sw" style="background:${st.colors[r.name]}"></span>
      <span class="nm">${esc(r.name)}${r.match ? `<small>${esc(r.match)}${r.when ? `, when ${esc(r.when)}` : ""}</small>` : ""}</span>
      ${isNow ? `<span class="firing">${trigger() ? "matched" : "fired"}</span>` : ""}
      ${done && st.ruleFaults[r.name] ? `<span class="bad" title="hard faults involving this rule">${st.ruleFaults[r.name]}!</span>` : ""}
      <span class="ct" title="members placed by this rule${done ? "" : " so far"}">${counts[r.name] || 0}</span>
      <span class="pr" title="priority: lower fires first in every pass">p${r.priority}</span>
      <button class="eye" title="show or hide its members">${st.hidden.has(r.name) ? "○" : "●"}</button>
    </li>`;
  }).join("");
}

$("#rules").addEventListener("click", (e) => {
  const li = e.target.closest("li[data-rule]");
  if (!li) return;
  const name = li.dataset.rule;
  if (e.target.closest(".eye")) {
    st.hidden.has(name) ? st.hidden.delete(name) : st.hidden.add(name);
    renderRules();
    look3d();
    renderElev();
    return;
  }
  select(st.sel?.kind === "rule" && st.sel.id === name ? null : { kind: "rule", id: name });
});

// ---------------------------------------------------------------- tabs, header, keys

export function showTab(id) {
  const pane = document.getElementById(id);
  const host = pane.closest("#center, #right");
  host.querySelectorAll("nav.tabs button[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === id));
  host.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p === pane));
  remember("tab." + host.id, id);
  if (host.id === "center") {
    document.body.classList.toggle("runs-mode", id === "runs");
    document.body.classList.toggle("verifier-mode", id === "verifier");
    hideTip();
    renderCaption();
    if (id === "runs") enterRuns();
    if (id === "view3d") requestAnimationFrame(resize);
    if (id === "elev") scrollElevTo(current()?.surface, { block: "nearest" });
  }
}

document.querySelectorAll("nav.tabs").forEach((nav) => nav.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (b) showTab(b.dataset.tab);
}));

$("#showFaults").addEventListener("change", () => { look3d(); renderElev(); });
document.addEventListener("click", (e) => {        // the show menu closes when you click elsewhere
  const menu = $("#showMenu");
  if (menu.open && !menu.contains(e.target)) menu.open = false;
});
$("#showSurfaces").addEventListener("change", () => { remember("surfaces", $("#showSurfaces").checked ? "1" : "0"); look3d(); renderElev(); });
$("#showGuides").addEventListener("change", () => { remember("guides", $("#showGuides").checked ? "1" : "0"); look3d(); renderElev(); });

$("#rebuild").addEventListener("click", () => build());

$("#house").addEventListener("change", () => { remember("house", $("#house").value); build(); });
$("#grammar").addEventListener("change", async () => {
  setFollow(false);
  remember("grammar", $("#grammar").value);
  st.hidden.clear();
  st.sel = null;
  await loadGrammar();
  build();
});
$("#newHouse").addEventListener("click", async () => {
  try {
    const { id } = await api("POST", "/api/houses", {});
    $("#house").add(new Option(id, id), 0);   // frame it at once; the full house list catches up after
    $("#house").value = id;
    remember("house", id);
    if (runsMode()) showTab("view3d");
    await build();
    await loadLists(id);
  } catch (e) { status(e.message, true); }
});
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); build(); }
  const typing = ["TEXTAREA", "INPUT", "SELECT"].includes(document.activeElement?.tagName);
  if (typing || runsMode()) return;
  if (e.key === "Escape") { if (measuring()) setMeasure(false); else if (st.fault != null) chooseFault(st.fault); else select(null); }
  if (e.key === "ArrowLeft") { e.preventDefault(); stepBy(-1); }
  if (e.key === "ArrowRight") { e.preventDefault(); stepBy(1); }
});

// ---------------------------------------------------------------- start

(async function start() {
  if (recall("surfaces") === "0") $("#showSurfaces").checked = false;
  if (recall("guides") === "1") $("#showGuides").checked = true;
  setView(recall("view"));
  setup3d();
  for (const host of ["center", "right"]) {
    const t = recall("tab." + host);
    if (t && document.getElementById(t)) showTab(t);
  }
  try {
    st.vinfo = await api("GET", "/api/verifier");
    await loadLists();
    await loadGrammar();
    await build();
    await pollJobs();
    await loadRunsList();
    const live = rs.jobs.find((j) => j.kind === "evolve" && j.status === "running")?.settings.run ?? rs.list.find((r) => r.live)?.name;
    if (live) startLive(live, false);
  } catch (e) {
    status(e.message, true);
  }
})();
