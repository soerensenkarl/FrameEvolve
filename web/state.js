// Shared state and small helpers for the workbench page: the colours, the units, the API calls, the
// status line, the house and grammar lists, and `st` (the loaded frame and where the user is in it: the
// selection, the build step shown, the storey, the chosen fault). Every other module imports from here.

export const $ = (s) => document.querySelector(s);
export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
export const PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7",
  "#9c755f", "#86bcb6", "#d37295", "#a0cbe8", "#ffbe7d", "#8cd17d", "#bab0ac"];
export const REL = { bears: "#2f6fdf", carries: "#2fa84f", side: "#a05cc8" };
export const PAST = "#d9d4c9";   // members placed by earlier build steps
export const SURF = "#8fb0cf";   // the house's surfaces: the input
export const GONE = "#d8342c";   // members a step removes
export const FACE = { outer: "#d8342c", inner: "#8a4fc8" };   // backing gaps on the outside and inside face
export const SITE = "#b3afa6";   // by panel: members built on site
export const GUIDE = { grid: "#9a978f", "panel joint": "#2f6fdf" };   // guide lines by kind; others as grid
export const S = 0.0254;         // the 3D view is in metres; the model is in inches

// ---------------------------------------------------------------- units: inches shown as feet and inches

export function frac(x) {
  // inches to 1/16", as 1 1/2"
  const n = Math.round(Math.abs(x) * 16);
  const whole = Math.floor(n / 16);
  let r = n % 16, d = 16;
  while (r && r % 2 === 0) { r /= 2; d /= 2; }
  const s = r ? (whole ? `${whole} ${r}/${d}` : `${r}/${d}`) : `${whole}`;
  return (x < 0 && n ? "-" : "") + s;
}
export const inch = (x) => `${frac(x)}"`;
export function ftin(x) {
  // inches as 9'-6", small sizes as 5 1/2"
  if (Math.abs(x) < 12) return inch(x);
  const n = Math.round(Math.abs(x) * 16) / 16;
  const ft = Math.floor(n / 12), r = n - ft * 12;
  return `${x < 0 ? "-" : ""}${ft}'-${r > 0 && r < 1 ? "0 " : ""}${frac(r)}"`;   // 9'-0 3/4", not 9'-3/4"
}
export const num = (v, d = 1) => (+v).toFixed(d);

function inkOn(hex) {
  const c = parseInt(hex.slice(1), 16);
  const l = (0.299 * (c >> 16) + 0.587 * ((c >> 8) & 255) + 0.114 * (c & 255)) / 255;
  return l > 0.62 ? "#1d1d1b" : "#ffffff";
}
export const pill = (name, c) => `<span class="pill" style="background:${c};color:${inkOn(c)}">${esc(name)}</span>`;
export const plain = (log) => (log || "").replace(/\x1b\[[0-9;]*m/g, "");
export const oneLine = (doc) => (doc || "").split(/\n\s*\n/)[0].replace(/\s+/g, " ").trim();
export function ago(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

// ---------------------------------------------------------------- the loaded frame and where the user is in it

export const st = {
  data: null, byId: {}, colors: {}, counts: {}, faulty: new Set(), ruleFaults: {},
  sel: null,            // {kind: "member" | "rule" | "panel", id}
  hidden: new Set(),    // rule names hidden from view
  saved: "",            // grammar source as saved on disk
  origin: null,         // where unsaved edits came from, e.g. "run demo, c002"
  fitFor: null,         // the house the 3D camera was last framed on
  at: 0,                // half-steps shown: 2k-1 is step k's trigger (before it fires), 2k its output
  placedAt: {}, removedAt: {}, playing: null,
  demo: new Map(), demoFor: null,
  surf: {}, level: {},  // surfaces by id, and each one's storey
  storey: 0,            // the storey filter: 0 for all
  vinfo: null,          // the verifier's checks and limits
  only: null,           // show only this check's faults
  fault: null,          // the fault chosen in the Verifier tab, an index into data.faults
  check: null,          // the check open in the Verifier tab
  vFilter: { rule: null, surface: null },   // its faults narrowed to one rule or surface
  vCap: 80,             // how many of its faults are listed
  vOpen: new Set(),     // Verifier sections opened ("d:...") or modules folded and unfolded ("mod:...")
  view: "build",        // what the 3D view shows: "build" (by rule, stepping the build), "panels", "assembly", "faults"
  asm: 0,               // the assembly view's step: the unit going up, or the length of the order when all are up
  hoverPanel: null,     // the panel under the pointer in the panels list
  panelColors: {}, panelAt: {}, guideAt: {},   // each panel's colour; the step a member got its panel, a guide was laid
};
export const finished = () => !st.data || st.at >= 2 * st.data.steps.length;
export const applied = () => Math.floor(st.at / 2);           // steps whose output is shown
export const stepNo = () => Math.ceil(st.at / 2);             // the step being shown, from 1
export const trigger = () => st.at % 2 === 1;                 // showing what a rule matched, before it fires
export const present = (id) => st.placedAt[id] < applied() && !(st.removedAt[id] < applied());
export const current = () => (st.data && !finished() && st.at > 0 ? st.data.steps[stepNo() - 1] : null);
export const placedNow = (id) => !finished() && !trigger() && st.placedAt[id] === applied() - 1;
export const goneNow = (id) => !finished() && !trigger() && st.removedAt[id] === applied() - 1;
export const matchedMember = (id) => { const t = current()?.target; return t?.kind === "member" && t.member === id; };
export const runsMode = () => document.body.classList.contains("runs-mode");
export const chosenFault = () => (st.fault != null ? st.data.faults[st.fault] : null);

// the surface the current step is on, or the one its match meets, is "active" in the views
export const isActive = (sid) => { const cur = current(); return !!cur && (cur.surface === sid || cur.target?.other === sid); };

// prefab panels and guides as of the step shown: a member's panel ("" built on site), whether a guide is laid yet
export const byPanel = () => st.view === "panels" || st.view === "assembly";   // members coloured by prefab panel
export const panelOf = (m) => (m.panel && (finished() || st.panelAt[m.id] < applied()) ? m.panel : "");
export const panelColour = (p) => (p ? st.panelColors[p] || SITE : SITE);
export const guideShown = (g) => finished() || st.guideAt[g.id] < applied();

export function memberColour(m, r, goneColour = GONE) {
  // a member's colour given its relation `r` to the selection ("self", "bears", "carries", "side", "rule" or
  // undefined). While stepping, earlier members are neutral; the rule's output, or the member it matched,
  // carry its colour. A member the step removes shows `goneColour`. By panel, every member shows its panel's
  // colour, or grey when it is built on site.
  if (r && REL[r]) return REL[r];
  if (goneNow(m.id)) return goneColour;
  if (byPanel()) return panelColour(panelOf(m));
  if (matchedMember(m.id)) return st.colors[current().rule];
  return finished() || placedNow(m.id) || r === "rule" ? st.colors[m.rule] : PAST;
}

export const surfaceList = () => [...st.data.walls, ...st.data.floors, ...st.data.roofs];
export const isFloor = (s) => s.kind === "floor";
export const isWall = (s) => s.kind === "wall";
export const kindName = (s) => (isWall(s) ? (s.role === "interior" ? "partition" : "wall") : s.role === "ceiling" ? "ceiling" : s.kind);
const FACES = { exterior: { outer: "outside face", inner: "inside face" }, interior: { outer: "face side", inner: "back side" },
  floor: { outer: "subfloor (top)", inner: "ceiling (underside)" }, ceiling: { outer: "ceiling (underside)" }, roof: { outer: "roof sheathing (top)" } };
export const faceName = (s, face) => (FACES[s.role] || FACES[isWall(s) ? "exterior" : s.kind])[face];
export const storeyOf = (id) => st.level[id] ?? 1;
export const shown3d = (id) => !st.storey || storeyOf(id) <= st.storey;        // 3D: this storey and the ones below
export const listed = (id) => !st.storey || storeyOf(id) === st.storey;         // surfaces list: this storey only

export function stopPlay() {
  if (st.playing) clearInterval(st.playing);
  st.playing = null;
}

// ---------------------------------------------------------------- server

export async function api(method, url, body) {
  const r = await fetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

export function status(text, err = false) {
  $("#status").textContent = text;
  $("#status").className = err ? "err" : "";
}

export function remember(k, v) { try { localStorage.setItem("fe." + k, v); } catch {} }
export function recall(k) { try { return localStorage.getItem("fe." + k); } catch { return null; } }

export function fill(select, items, value) {
  select.innerHTML = items.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join("");
  if (value && items.some(([v]) => v === value)) select.value = value;
}

export let houseList = [], grammarList = [];
export async function loadLists(houseId) {
  houseList = await api("GET", "/api/houses");
  fill($("#house"), houseList.map((h) => [h.id,
    `${h.id}   ${ftin(h.size[0])} x ${ftin(h.size[1])}, ${h.openings} openings`]),
    houseId || recall("house"));
  grammarList = await api("GET", "/api/grammars");
  const label = (g) => (g.includes(".") ? `run ${g.split(".")[0]}: ${g.split(".")[1]}` : g);
  fill($("#grammar"), grammarList.map((g) => [g, label(g)]), $("#grammar").value || recall("grammar") || "seed");
}

export const dirty = () => $("#src").value !== st.saved;

// ---------------------------------------------------------------- a small tooltip shared by the build strip and the run charts

export function showTip(html, rect, where = "above") {
  const tip = $("#tip");
  const host = $("#stage").getBoundingClientRect();
  tip.innerHTML = html;
  tip.hidden = false;
  const x = Math.max(4, Math.min(host.width - tip.offsetWidth - 4, rect.left + rect.width / 2 - host.left - tip.offsetWidth / 2));
  const y = where === "above" ? rect.top - host.top - tip.offsetHeight - 6 : rect.bottom - host.top + 6;
  tip.style.left = `${x}px`;
  tip.style.top = `${Math.max(2, y)}px`;
}
export function hideTip() { $("#tip").hidden = true; }
