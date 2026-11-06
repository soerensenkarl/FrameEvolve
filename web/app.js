// FrameEvolve workbench. One page: pick a house and a grammar, build, look at the frame in 3D and in
// elevation, step through the build rule by rule, inspect members and their contacts, read faults, edit the
// grammar and rebuild. The Runs view shows the search: progress, the grammars it kept, what the proposer did,
// and starts or stops searches and the tests.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7",
  "#9c755f", "#86bcb6", "#d37295", "#a0cbe8", "#ffbe7d", "#8cd17d", "#bab0ac"];
const REL = { bears: "#2f6fdf", carries: "#2fa84f", side: "#a05cc8" };
const PAST = "#d9d4c9";   // members placed by earlier build steps
const SURF = "#8fb0cf";   // the house's wall surfaces: the input
const GONE = "#d8342c";   // members a step removes
const FACE = { outer: "#d8342c", inner: "#8a4fc8" };   // backing gaps on the outside and inside face
const FACE_NAME = { outer: "outside face", inner: "inside face" };
const S = 0.0254;         // the 3D view is in metres; the model is in inches

// ---------------------------------------------------------------- units: inches shown as feet and inches

function frac(x) {
  // inches to 1/16", as 1 1/2"
  const n = Math.round(Math.abs(x) * 16);
  const whole = Math.floor(n / 16);
  let r = n % 16, d = 16;
  while (r && r % 2 === 0) { r /= 2; d /= 2; }
  const s = r ? (whole ? `${whole} ${r}/${d}` : `${r}/${d}`) : `${whole}`;
  return (x < 0 && n ? "-" : "") + s;
}
const inch = (x) => `${frac(x)}"`;
function ftin(x) {
  // inches as 9'-6", small sizes as 5 1/2"
  if (Math.abs(x) < 12) return inch(x);
  const n = Math.round(Math.abs(x) * 16) / 16;
  const ft = Math.floor(n / 12);
  return `${x < 0 ? "-" : ""}${ft}'-${frac(n - ft * 12)}"`;
}
const num = (v, d = 1) => (+v).toFixed(d);

function inkOn(hex) {
  const c = parseInt(hex.slice(1), 16);
  const l = (0.299 * (c >> 16) + 0.587 * ((c >> 8) & 255) + 0.114 * (c & 255)) / 255;
  return l > 0.62 ? "#1d1d1b" : "#ffffff";
}
const pill = (name, c) => `<span class="pill" style="background:${c};color:${inkOn(c)}">${esc(name)}</span>`;
const plain = (log) => (log || "").replace(/\x1b\[[0-9;]*m/g, "");
const oneLine = (doc) => (doc || "").split(/\n\s*\n/)[0].replace(/\s+/g, " ").trim();
function ago(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

const st = {
  data: null, byId: {}, colors: {}, counts: {}, faulty: new Set(), ruleFaults: {},
  sel: null,            // {kind: "member" | "rule", id}
  hidden: new Set(),    // rule names hidden from view
  saved: "",            // grammar source as saved on disk
  origin: null,         // where unsaved edits came from, e.g. "run demo, c002"
  fitFor: null,         // the house the 3D camera was last framed on
  at: 0,                // half-steps shown: 2k-1 is step k's trigger (before it fires), 2k its output
  placedAt: {}, removedAt: {}, playing: null, builds: 0,
  demo: new Map(), demoFor: null,
  surf: {}, level: {},  // surfaces by id, and each one's storey
  storey: 0,            // the storey filter: 0 for all
  vinfo: null,          // the verifier's checks and limits
  only: null,           // show only this check's faults
  fault: null,          // the fault chosen in the Verifier tab, an index into data.faults
  openChecks: new Set(),
};
const finished = () => !st.data || st.at >= 2 * st.data.steps.length;
const applied = () => Math.floor(st.at / 2);           // steps whose output is shown
const stepNo = () => Math.ceil(st.at / 2);             // the step being shown, from 1
const trigger = () => st.at % 2 === 1;                 // showing what a rule matched, before it fires
const present = (id) => st.placedAt[id] < applied() && !(st.removedAt[id] < applied());
const current = () => (st.data && !finished() && st.at > 0 ? st.data.steps[stepNo() - 1] : null);
const placedNow = (id) => !finished() && !trigger() && st.placedAt[id] === applied() - 1;
const goneNow = (id) => !finished() && !trigger() && st.removedAt[id] === applied() - 1;
const matchedMember = (id) => { const t = current()?.target; return t?.kind === "member" && t.member === id; };
const runsMode = () => document.body.classList.contains("runs-mode");

// ---------------------------------------------------------------- server

async function api(method, url, body) {
  const r = await fetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function status(text, err = false) {
  $("#status").textContent = text;
  $("#status").className = err ? "err" : "";
}

function remember(k, v) { try { localStorage.setItem("fe." + k, v); } catch {} }
function recall(k) { try { return localStorage.getItem("fe." + k); } catch { return null; } }

function fill(select, items, value) {
  select.innerHTML = items.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join("");
  if (value && items.some(([v]) => v === value)) select.value = value;
}

let houseList = [], grammarList = [];
async function loadLists(houseId) {
  houseList = await api("GET", "/api/houses");
  fill($("#house"), houseList.map((h) => [h.id,
    `${h.id}   ${ftin(h.size[0])} x ${ftin(h.size[1])}, ${h.openings} openings`]),
    houseId || recall("house"));
  grammarList = await api("GET", "/api/grammars");
  const label = (g) => (g.includes(".") ? `run ${g.split(".")[0]}: ${g.split(".")[1]}` : g);
  fill($("#grammar"), grammarList.map((g) => [g, label(g)]), $("#grammar").value || recall("grammar") || "seed");
}

async function loadGrammar() {
  const g = await api("GET", `/api/grammar/${$("#grammar").value}`);
  st.saved = g.source;
  st.origin = null;
  $("#src").value = g.source;
  editState();
}

const dirty = () => $("#src").value !== st.saved;

async function build(keepStep = false) {
  status("building...");
  const was = st.data && !finished() ? st.at : null;   // a live draft rebuilds where the user is stepping
  const t0 = performance.now();
  const body = { house: $("#house").value, grammar: $("#grammar").value };
  if (dirty()) body.source = $("#src").value;
  try {
    st.data = await api("POST", "/api/build", body);
  } catch (e) {
    status(e.message, true);
    return false;
  }
  index();
  if (keepStep && was != null) st.at = Math.min(was, 2 * st.data.steps.length);
  renderAll();
  const ms = (s) => `${Math.round(1000 * s)} ms`, tm = st.data.timing || {};
  status(`framed from scratch in ${ms(tm.build || 0)}, verified in ${ms(tm.verify || 0)}, ` +
         `${ms((performance.now() - t0) / 1000)} in all${dirty() ? ", from unsaved edits" : ""}`);
  return true;
}

function index() {
  const d = st.data;
  st.builds++;
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
  st.at = 2 * d.steps.length;
  stopPlay();
  if (st.sel?.kind === "member" && !st.byId[st.sel.id]) st.sel = null;
  if (st.sel?.kind === "rule" && !names.includes(st.sel.id)) st.sel = null;
}

function renderAll() {
  renderStats();
  renderRules();
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
function select(sel) {
  st.sel = sel;
  if (st.fault != null) { st.fault = null; renderVerifier(); }   // a selection replaces the fault being explained
  renderRules();
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
    ["build steps", s.steps, "", "Rule firings that changed something. Step through them below the view."],
  ];
  $("#stats").innerHTML = rows.map(([k, v, kind, tip]) =>
    `<span class="k" title="${esc(tip)}">${k}</span><span class="v ${kind}" title="${esc(tip)}">${v}</span>`).join("");
  $("#faultCount").textContent = s.hard + s.soft ? `(${s.hard} + ${s.soft})` : "";
}

function renderRules() {
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

// ---------------------------------------------------------------- 3D

let renderer, labeler, scene, camera, controls, group, gapGroup, markGroup, surfGroup, targetGroup, evGroup;
const meshes = new Map();
let surfs = [];   // per wall: {wall, mesh, line, label, opLabels}

function setup3d() {
  const el = $("#view3d");
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  el.appendChild(renderer.domElement);
  labeler = new CSS2DRenderer();
  labeler.domElement.className = "labels";
  el.appendChild(labeler.domElement);
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf7f6f3);
  camera = new THREE.PerspectiveCamera(35, 1, 0.05, 1000);
  camera.up.set(0, 0, 1);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.15;
  // as in AutoDesignIterator and Rhino for Mac: left clicks select, right drag orbits (Shift: pans), middle
  // drag pans, Cmd/Ctrl + right drag zooms; wheel and trackpad are handled below
  controls.mouseButtons = { LEFT: -1, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE };
  controls.enableZoom = false;
  const shiftPans = (e) => { controls.mouseButtons.RIGHT = e.shiftKey ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE; };
  window.addEventListener("keydown", shiftPans);
  window.addEventListener("keyup", shiftPans);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a877e, 1.7));
  const sun = new THREE.DirectionalLight(0xffffff, 1.3);
  sun.position.set(-6, -9, 14);
  scene.add(sun);
  const grid = new THREE.GridHelper(60, 60, 0xd6d3cc, 0xe6e4df);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = -0.002;
  scene.add(grid);
  group = new THREE.Group();
  gapGroup = new THREE.Group();
  markGroup = new THREE.Group();
  surfGroup = new THREE.Group();
  targetGroup = new THREE.Group();
  evGroup = new THREE.Group();
  scene.add(group, gapGroup, markGroup, surfGroup, targetGroup, evGroup);

  new ResizeObserver(resize).observe(el);
  const canvas = renderer.domElement;
  let down = null, zoomDrag = null;
  canvas.addEventListener("pointerdown", (e) => {     // Cmd/Ctrl + right drag zooms, before the orbit controls see it
    if (e.button === 2 && (e.ctrlKey || e.metaKey)) {
      e.stopImmediatePropagation();
      canvas.setPointerCapture(e.pointerId);
      zoomDrag = { y: e.clientY, at: { clientX: e.clientX, clientY: e.clientY } };
    }
  }, true);
  canvas.addEventListener("pointermove", (e) => {
    if (!zoomDrag) return;
    zoomAt(Math.exp((e.clientY - zoomDrag.y) * 0.01), zoomDrag.at);
    zoomDrag.y = e.clientY;
  });
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("pointermove", (e) => { if (measure.on && !e.buttons) measureHover(e); });
  canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY, e.button]; });
  canvas.addEventListener("pointerup", (e) => {
    if (zoomDrag) { zoomDrag = null; return; }
    if (!down || down[2] !== 0 || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    if (measure.on) return measureClick(e);
    const r = renderer.domElement.getBoundingClientRect();
    const p = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(p, camera);
    const hit = ray.intersectObjects([...meshes.values()].filter((m) => m.visible), false)[0];
    select(hit ? { kind: "member", id: hit.object.userData.id } : null);
  });
  // wheel and trackpad, as in Rhino for Mac: two fingers orbit, Shift + two fingers pan, pinch zooms; a wheel
  // mouse zooms to the cursor (Shift: pan). A trackpad sends fine pixel steps, often sideways too; once a trackpad
  // gesture starts it stays one until it rests, so its momentum is never read as a wheel.
  let padUntil = 0;
  const fromTrackpad = (e) => {
    const now = performance.now(), wd = e.wheelDeltaY ?? 0;
    const pad = e.deltaMode === 0 && (e.deltaX !== 0 || (wd !== 0 && wd === -3 * e.deltaY) ||
      (wd % 120 !== 0 && !Number.isInteger(e.deltaY)));
    if (pad) padUntil = now + 250;
    return pad || now < padUntil;
  };
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const px = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? window.innerHeight : 1;
    const dx = e.deltaX * px, dy = e.deltaY * px;
    if (e.ctrlKey) zoomAt(Math.exp(dy * 0.01), e);                       // pinch
    else if (fromTrackpad(e)) e.shiftKey ? panBy(dx, dy) : orbitBy(dx * 0.006, dy * 0.006);
    else if (e.shiftKey) panBy(dx, dy);
    else zoomAt(Math.exp(dy * 0.0015), e);
    controls.update();
  }, { passive: false });
  (function loop() {
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
    labeler.render(scene, camera);
  })();
}

// ---------------------------------------------------------------- measure: click two points, snapping to members

const measure = { on: false, first: null, group: null, marker: null };

function setMeasure(on) {
  measure.on = on;
  measure.first = null;
  $("#measureBtn").classList.toggle("on", on);
  $("#view3d").classList.toggle("measuring", on);
  if (!measure.group) {
    measure.group = new THREE.Group();
    measure.marker = new THREE.Mesh(new THREE.SphereGeometry(0.035, 16, 12),
      new THREE.MeshBasicMaterial({ color: 0x1d1d1b, depthTest: false }));
    measure.marker.renderOrder = 20;
    scene.add(measure.group, measure.marker);
  }
  measure.marker.visible = false;
  if (!on) clear(measure.group);    // measurements stay while measuring, go when you stop
}
$("#measureBtn").addEventListener("click", () => setMeasure(!measure.on));
$("#centerBtn").addEventListener("click", () => fit());

function measurePoint(e) {
  // the point under the cursor on a member (or the ground), snapped to the nearest corner or edge midpoint
  // of that member within 14 px; returns [point in metres, snapped]
  const el = renderer.domElement, r = el.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  const rc = new THREE.Raycaster();
  rc.setFromCamera(ndc, camera);
  const hit = rc.intersectObjects([...meshes.values()].filter((m) => m.visible), false)[0];
  if (!hit) {
    const g = rc.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0), new THREE.Vector3());
    return g ? [g, false] : [null, false];
  }
  const m = st.byId[hit.object.userData.id];
  const xs = [m.lo[0], (m.lo[0] + m.hi[0]) / 2, m.hi[0]], ys = [m.lo[1], (m.lo[1] + m.hi[1]) / 2, m.hi[1]],
        zs = [m.lo[2], (m.lo[2] + m.hi[2]) / 2, m.hi[2]];
  const pts = [];   // a box's corners and edge midpoints; a shaped member's own corners
  if (m.mesh) for (let i = 0; i < m.mesh.verts.length; i += 3) pts.push(m.mesh.verts.slice(i, i + 3));
  else for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let k = 0; k < 3; k++) {
    if ((i === 1) + (j === 1) + (k === 1) <= 1) pts.push([xs[i], ys[j], zs[k]]);
  }
  let best = null, bestPx = 14;
  for (const q of pts) {
    const p = new THREE.Vector3(...q.map((x) => x * S));
    const s = p.clone().project(camera);
    const px = Math.hypot((s.x - ndc.x) * r.width / 2, (s.y - ndc.y) * r.height / 2);
    if (px < bestPx) { bestPx = px; best = p; }
  }
  return best ? [best, true] : [hit.point.clone(), false];
}

function measureHover(e) {
  const [p, snapped] = measurePoint(e);
  measure.marker.visible = !!p;
  if (!p) return;
  measure.marker.position.copy(p);
  measure.marker.material.color.set(snapped ? 0x2f6fdf : 0x1d1d1b);
}

function measureClick(e) {
  const [p] = measurePoint(e);
  if (!p) return;
  const dot = new THREE.Mesh(new THREE.SphereGeometry(0.03, 12, 10),
    new THREE.MeshBasicMaterial({ color: 0x1d1d1b, depthTest: false }));
  dot.renderOrder = 20;
  dot.position.copy(p);
  measure.group.add(dot);
  if (!measure.first) { measure.first = p; return; }
  const a = measure.first, d = p.clone().sub(a);
  const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, p]),
    new THREE.LineBasicMaterial({ color: 0x1d1d1b, depthTest: false }));
  line.renderOrder = 20;
  const div = document.createElement("div");
  div.className = "lbl measure";
  const inch = (v) => Math.abs(v) / S;
  div.innerHTML = `${ftin(inch(d.length()))} <i>x ${ftin(inch(d.x))} y ${ftin(inch(d.y))} z ${ftin(inch(d.z))}</i>`;
  const label = new CSS2DObject(div);
  label.position.copy(a.clone().add(p).multiplyScalar(0.5));
  measure.group.add(line, label);
  measure.first = null;
}

function orbitBy(dAz, dPol) {
  const off = camera.position.clone().sub(controls.target);
  const r = off.length();
  let az = Math.atan2(off.y, off.x), pol = Math.acos(THREE.MathUtils.clamp(off.z / r, -1, 1));
  az += dAz;
  pol = THREE.MathUtils.clamp(pol + dPol, 0.02, Math.PI - 0.02);
  off.set(r * Math.sin(pol) * Math.cos(az), r * Math.sin(pol) * Math.sin(az), r * Math.cos(pol));
  camera.position.copy(controls.target).add(off);
  camera.lookAt(controls.target);
}

function panBy(dx, dy) {
  const el = renderer.domElement;
  const dist = camera.position.distanceTo(controls.target);
  const perPx = 2 * dist * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / el.clientHeight;
  const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
  const up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
  const move = right.multiplyScalar(dx * perPx).add(up.multiplyScalar(-dy * perPx));
  camera.position.add(move);
  controls.target.add(move);
}

function zoomAt(factor, e) {
  // dolly toward the point under the cursor: the member there, else the ground, else the view's target plane
  const r = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  const rc = new THREE.Raycaster();
  rc.setFromCamera(ndc, camera);
  const hit = rc.intersectObjects([...meshes.values()].filter((m) => m.visible), false)[0];
  const focus = hit?.point
    || rc.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0), new THREE.Vector3())
    || rc.ray.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(
      camera.getWorldDirection(new THREE.Vector3()), controls.target), new THREE.Vector3())
    || controls.target.clone();
  if (factor < 1 && camera.position.distanceTo(controls.target) < 0.3) return;
  camera.position.sub(focus).multiplyScalar(factor).add(focus);
  controls.target.sub(focus).multiplyScalar(factor).add(focus);
}

function resize() {
  const el = $("#view3d");
  if (!el.clientWidth || !el.clientHeight) return;
  renderer.setSize(el.clientWidth, el.clientHeight);
  labeler.setSize(el.clientWidth, el.clientHeight);
  camera.aspect = el.clientWidth / el.clientHeight;
  camera.updateProjectionMatrix();
}

function clear(g) {
  for (const o of [...g.children]) {
    o.traverse((c) => { c.geometry?.dispose(); c.material?.dispose?.(); });
    g.remove(o);
  }
}

// every surface, wall or floor, maps its (u, v, w) to the world through its own axes
function surfMatrix(s, out = 0) {
  // `out` pushes the plane out of the framing (outside a wall, above a floor), in metres
  const [eu, ev, ew] = [s.eu, s.ev, s.ew].map((a) => new THREE.Vector3(...a));
  const o = new THREE.Vector3(...s.origin).multiplyScalar(S).addScaledVector(ew, -out);
  return new THREE.Matrix4().makeBasis(eu, ev, ew).setPosition(o);
}

function toLocal(s, p) {
  // a world point (inches) in a surface's u, v, w
  const q = [0, 1, 2].map((k) => p[k] - s.origin[k]);
  return [s.eu, s.ev, s.ew].map((a) => a[0] * q[0] + a[1] * q[1] + a[2] * q[2]);
}

const surfaceList = () => [...st.data.walls, ...st.data.floors, ...(st.data.roofs || [])];
const isFloor = (s) => s.kind === "floor";
const isWall = (s) => s.kind === "wall";
const kindName = (s) => (isWall(s) ? (s.role === "interior" ? "partition" : "wall") : s.role === "ceiling" ? "ceiling" : s.kind);
const FACES = { exterior: { outer: "outside face", inner: "inside face" }, interior: { outer: "face side", inner: "back side" },
  floor: { outer: "subfloor (top)", inner: "ceiling (underside)" }, ceiling: { outer: "ceiling (underside)" }, roof: { outer: "roof sheathing (top)" } };
const faceName = (s, face) => (FACES[s.role] || FACES[isWall(s) ? "exterior" : s.kind])[face];
const storeyOf = (id) => st.level[id] ?? 1;
const shown3d = (id) => !st.storey || storeyOf(id) <= st.storey;        // 3D: this storey and the ones below
const listed = (id) => !st.storey || storeyOf(id) === st.storey;         // surfaces list: this storey only

function label(text, cls, pos, groupTo = surfGroup) {
  const div = document.createElement("div");
  div.className = "lbl " + cls;
  div.innerHTML = text;
  const o = new CSS2DObject(div);
  o.position.copy(pos);
  groupTo.add(o);
  return o;
}

const v2 = (u, v) => new THREE.Vector2(u * S, v * S);

function renderSurfaces(list = surfaceList()) {
  clear(surfGroup);
  surfs = [];
  for (const s of list) {
    const M = surfMatrix(s, 0.004);
    const shape = new THREE.Shape(s.outline.map(([u, v]) => v2(u, v)));
    const pts = s.outline.map((p, i) => [p, s.outline[(i + 1) % s.outline.length]]);
    for (const o of s.openings) {
      const r = [[o.u0, o.v0], [o.u1, o.v0], [o.u1, o.v1], [o.u0, o.v1]];
      shape.holes.push(new THREE.Path(r.map(([u, v]) => v2(u, v))));
      pts.push(...r.map((p, i) => [p, r[(i + 1) % 4]]));
    }
    const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape),
      new THREE.MeshBasicMaterial({ color: SURF, transparent: true, opacity: 0.3, side: THREE.DoubleSide, depthWrite: false }));
    mesh.applyMatrix4(M);
    mesh.renderOrder = -1;
    const line = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts.flatMap(([a, b]) =>
      [new THREE.Vector3(a[0] * S, a[1] * S, 0), new THREE.Vector3(b[0] * S, b[1] * S, 0)])),
      new THREE.LineBasicMaterial({ color: 0x4d6780, transparent: true, opacity: 0.8 }));
    line.applyMatrix4(M);
    surfGroup.add(mesh, line);
    const [U, V] = s.size;
    const at = isWall(s) ? new THREE.Vector3(U * S / 2, V * S + 0.25, 0) : new THREE.Vector3(U * S * 0.08, V * S * 0.08, 0);
    const name = kindName(s) === "wall" ? "" : kindName(s);
    const lbl = label(`${esc(s.id)} <i>${name ? name + ", " : ""}${ftin(U)}${isWall(s) ? "" : ` x ${ftin(V)}`}</i>`, "wall", at.applyMatrix4(M));
    const ol = s.openings.map((o) => label(`${esc(o.kind)} ${ftin(o.u1 - o.u0)} x ${ftin(o.v1 - o.v0)}`, "op",
      new THREE.Vector3(((o.u0 + o.u1) / 2) * S, ((o.v0 + o.v1) / 2) * S, 0).applyMatrix4(M)));
    surfs.push({ wall: s.id, mesh, line, label: lbl, opLabels: ol });
  }
}

function renderMarks() {
  // fault markers, and backing gaps, for every check or only the one chosen in the Verifier tab
  clear(gapGroup);
  clear(markGroup);
  const only = st.only;
  for (const s of surfaceList()) {
    if (only && only !== "backing") break;
    for (const g of s.gaps) {
      const p = g.world.map((c) => new THREE.Vector3(...c.map((x) => x * S)));
      const mesh = new THREE.Mesh(new THREE.BufferGeometry().setFromPoints([p[0], p[1], p[2], p[0], p[2], p[3]]),
        new THREE.MeshBasicMaterial({ color: FACE[g.face], transparent: true, opacity: 0.32, side: THREE.DoubleSide, depthWrite: false }));
      mesh.userData.surface = s.id;
      gapGroup.add(mesh);
    }
  }
  const hardMat = new THREE.MeshBasicMaterial({ color: 0xd8342c, depthTest: false, transparent: true });
  const softMat = new THREE.MeshBasicMaterial({ color: 0xe08a00, depthTest: false, transparent: true });
  const ball = new THREE.SphereGeometry(0.06, 16, 12);
  for (const f of st.data.faults) {
    if (!f.at || f.check === "backing" || (only && f.check !== only)) continue;
    const s = new THREE.Mesh(ball, f.hard ? hardMat : softMat);
    s.position.set(...f.at.map((x) => x * S));
    s.userData.surface = f.wall;
    s.renderOrder = 10;
    markGroup.add(s);
  }
}

function memberMesh(m, mat, edgeMat) {
  // a member's solid, in world metres: its triangle mesh where it is cut, notched or at an angle, else its box
  let geo;
  if (m.mesh) {
    geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(m.mesh.verts.map((x) => x * S), 3));
    geo.setIndex(m.mesh.idx.flat());
    geo = geo.toNonIndexed();   // a normal per triangle, so cut faces stay flat and crisp
    geo.computeVertexNormals();
  } else {
    geo = new THREE.BoxGeometry(...[0, 1, 2].map((k) => (m.hi[k] - m.lo[k]) * S))
      .translate(...[0, 1, 2].map((k) => ((m.lo[k] + m.hi[k]) / 2) * S));
  }
  const mesh = new THREE.Mesh(geo, mat);
  mesh.userData.id = m.id;
  mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 20), edgeMat));   // real edges, not the triangles'
  return mesh;
}

function render3d() {
  clear(group);
  meshes.clear();
  const edgeMat = new THREE.LineBasicMaterial({ color: 0x1d1d1b, transparent: true, opacity: 0.35 });
  for (const m of st.data.members) {
    const mesh = memberMesh(m, new THREE.MeshStandardMaterial({ roughness: 0.85, transparent: true }), edgeMat);
    group.add(mesh);
    meshes.set(m.id, mesh);
  }
  renderMarks();
  renderSurfaces();
  if (st.fitFor !== st.data.house) {
    st.fitFor = st.data.house;
    fit();
  }
  look3d();
}

function fit() {
  // frame the whole house, allowing for a narrow or wide view
  const box = new THREE.Box3();
  for (const s of surfs) box.expandByObject(s.mesh);
  if (box.isEmpty()) box.setFromObject(group);
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3());
  const r = box.getSize(new THREE.Vector3()).length() / 2;
  const half = THREE.MathUtils.degToRad(camera.fov / 2);
  const dist = (1.15 * r) / Math.sin(half) / Math.min(1, camera.aspect);
  const dir = new THREE.Vector3(-0.45, -0.75, 0.5).normalize();
  controls.target.copy(c);
  camera.position.copy(c).addScaledVector(dir, dist);
  camera.near = r / 200;
  camera.far = dist * 10;
  camera.updateProjectionMatrix();
}

function related() {
  // id -> relation to the selection: "self", "bears", "carries", "side", "rule"; null when nothing is selected.
  // A fault chosen in the Verifier tab works like a selection: its members, and what holds them.
  const sel = st.sel, f = st.fault != null ? st.data.faults[st.fault] : null;
  if (!sel && !f) return null;
  const rel = new Map();
  if (f) {
    const ev = evidence(f);
    for (const id of ev.supports) rel.set(id, "bears");
    for (const id of f.members) if (st.byId[id]) rel.set(id, "self");
    if (!rel.size) return null;   // nothing placed there: the evidence alone shows it
  } else if (sel.kind === "member") {
    const m = st.byId[sel.id];
    rel.set(m.id, "self");
    for (const k of ["bears", "carries", "side"]) for (const id of m[k]) if (st.byId[id]) rel.set(id, k);
  } else {
    for (const m of st.data.members) if (m.rule === sel.id) rel.set(m.id, "rule");
  }
  return rel;
}

function look3d() {
  if (!st.data) return;
  const rel = related();
  const done = finished();
  const cur = current();
  for (const [id, mesh] of meshes) {
    const m = st.byId[id];
    const r = rel?.get(id);
    const gone = goneNow(id);
    mesh.visible = !st.hidden.has(m.rule) && (present(id) || gone) && shown3d(m.surface);
    const mat = mesh.material;
    const isNow = placedNow(id);
    const hit = matchedMember(id);
    // while stepping, earlier members are neutral; the rule's output, or the member it matched, carry its colour
    const c = r && REL[r] ? REL[r] : gone ? GONE : hit ? st.colors[cur.rule] : done || isNow || r === "rule" ? st.colors[m.rule] : PAST;
    mat.color.set(c);
    if (r === "self") mat.emissive.set(0x555500);
    else if (isNow || (hit && trigger())) mat.emissive.set(c).multiplyScalar(0.35);
    else mat.emissive.set(done && st.faulty.has(id) ? 0x550000 : 0x000000);
    mat.opacity = rel && !r ? 0.12 : gone ? 0.35 : 1;
    mat.depthWrite = mat.opacity === 1;
  }
  const show = $("#showFaults").checked && done && st.fault == null;   // a chosen fault shows its own evidence instead
  gapGroup.visible = markGroup.visible = show;
  for (const o of [...gapGroup.children, ...markGroup.children]) o.visible = shown3d(o.userData.surface);
  // the house's surfaces: strong on the bare house, faint once framing exists
  const on = $("#showSurfaces").checked;
  for (const s of surfs) {
    const active = cur?.wall === s.wall || cur?.target?.other === s.wall;
    const vis = on && shown3d(s.wall);
    s.mesh.visible = s.line.visible = s.label.visible = vis;
    s.mesh.material.opacity = st.at === 0 ? 0.32 : active ? 0.2 : done ? 0.06 : 0.1;
    s.line.material.opacity = st.at === 0 ? 0.9 : active ? 0.8 : done ? 0.3 : 0.45;
    s.label.element.classList.toggle("active", active);
    s.label.element.classList.toggle("faint", done && st.at > 0);
    for (const o of s.opLabels) {
      o.visible = vis && (st.at === 0 || active || done);
      o.element.classList.toggle("faint", st.at > 0 && !active);
    }
  }
  renderTarget3d();
  renderEvidence3d();
}

function depthOf(id) {
  // how far a surface's framing reaches in from it: the commonest reach of its members
  const n = {};
  for (const m of st.data.members) if (m.surface === id && m.local && present(m.id)) n[m.local[1][2]] = (n[m.local[1][2]] || 0) + 1;
  const best = Object.entries(n).sort((a, b) => b[1] - a[1])[0];
  return best ? +best[0] : st.surf[id]?.depth || 3.5;
}

function otherEnd(t) {
  // where the other wall of a corner or tee meets this one, in its own coordinates
  const o = (t.kind === "corner" || t.kind === "tee") && st.surf[t.other];
  return o ? { wall: o.id, u0: o.end_meets === t.wall ? o.length : 0, u1: o.end_meets === t.wall ? o.length : 0, v0: 0, v1: o.height } : null;
}

const isLine = (t) => t.u1 - t.u0 < 1e-6 || t.v1 - t.v0 < 1e-6;

function markOn(groupTo, sid, t, c, strong, face) {
  // a rectangle or a line in a surface's u, v, on its outer face or (face "inner") at its framing depth
  const s = st.surf[sid];
  if (!s) return;
  const M = surfMatrix(s, face === "inner" ? -(depthOf(sid) + 0.3) * S : 0.008);
  if (isLine(t)) {
    const a = new THREE.Vector3(t.u0 * S, t.v0 * S, 0), b = new THREE.Vector3(t.u1 * S, t.v1 * S, 0);
    const len = a.distanceTo(b);
    const post = new THREE.Mesh(new THREE.BoxGeometry(2.5 * S, len || 2.5 * S, 2.5 * S),
      new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: strong ? 0.9 : 0.4, depthTest: !strong }));
    post.position.copy(a.clone().add(b).multiplyScalar(0.5));
    post.position.z = -1.5 * S;
    if (len) post.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    post.applyMatrix4(M);
    post.renderOrder = 5;
    groupTo.add(post);
    return;
  }
  const pts = [[t.u0, t.v0], [t.u1, t.v0], [t.u1, t.v1], [t.u0, t.v1]].map(([u, v]) => new THREE.Vector3(u * S, v * S, 0));
  if (strong) {
    const plane = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(pts.map((p) => new THREE.Vector2(p.x, p.y)))),
      new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.45, side: THREE.DoubleSide, depthWrite: false }));
    plane.applyMatrix4(M);
    groupTo.add(plane);
  }
  const loop = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color: c, transparent: true, opacity: strong ? 1 : 0.6, depthTest: false }));
  loop.applyMatrix4(M);
  loop.renderOrder = 5;
  groupTo.add(loop);
  if (face === "inner") label(faceName(s, "inner"), "target", new THREE.Vector3(((t.u0 + t.u1) / 2) * S, ((t.v0 + t.v1) / 2) * S, 0).applyMatrix4(M), groupTo);
}

function renderTarget3d() {
  // what the current step's rule matched: strong at the trigger, an outline at the output
  clear(targetGroup);
  const s = current();
  const t = s?.target;
  if (!t || t.kind === "member") return;
  const c = st.colors[s.rule], trig = trigger();
  markOn(targetGroup, t.wall, t, c, trig, t.face);
  const o = otherEnd(t);
  if (o) markOn(targetGroup, o.wall, o, c, trig);
}

// ---------------------------------------------------------------- surfaces: wall elevations and floor plans, by storey

// a member on its surface: its outline polygons where it is cut or at an angle, else its rectangle u0..u1, v0..v1
const memberSvg = (b, attrs, title) => (b.poly
  ? `<path ${attrs} d="${b.poly.map((p) => `M${p.map(([u, v]) => `${u} ${-v}`).join("L")}z`).join("")}"><title>${title}</title></path>`
  : `<rect ${attrs} x="${b.u0}" y="${-b.v1}" width="${b.u1 - b.u0}" height="${b.v1 - b.v0}"><title>${title}</title></rect>`);

function surfaceSvg(s, span, rel) {
  // one surface drawn in its own u (right) and v (up): an elevation of a wall, a plan of a floor from above
  const [U, V] = s.size;
  const k = span / 1000;   // drawing unit: sizes below scale with the drawing
  const pad = 20 * k;
  const done = finished();
  const cur = current();
  const showFaults = $("#showFaults").checked && done && st.fault == null;
  const surfOp = st.at === 0 ? 0.42 : done ? 0.12 : 0.2;
  const active = cur && (cur.wall === s.id || cur.target?.other === s.id);
  const own = st.data.members.filter((m) => m.surface === s.id && !st.hidden.has(m.rule) && (present(m.id) || goneNow(m.id)));
  const rects = own.map((m) => {
    const [lo, hi] = m.local;
    const r = rel?.get(m.id);
    const gone = goneNow(m.id);
    const isNow = placedNow(m.id);
    const hit = matchedMember(m.id);
    const cls = ["m", rel && !r ? "dim" : "", r === "self" ? "sel" : "", showFaults && st.faulty.has(m.id) ? "fault" : "",
      isNow || (hit && trigger()) ? "now" : "", gone ? "gone" : ""].join(" ");
    const fillc = r && REL[r] ? REL[r] : gone ? "none" : hit ? st.colors[cur.rule] : done || isNow || r === "rule" ? st.colors[m.rule] : PAST;
    return memberSvg({ u0: lo[0], v0: lo[1], u1: hi[0], v1: hi[1], poly: m.poly }, `class="${cls}" data-id="${m.id}" fill="${fillc}"`,
      `${m.id} ${esc(m.role || "")}, ${esc(m.rule)}, ${esc(m.section)}${gone ? ", removed at this step" : ""}`);
  }).join("");
  // around it: other walls' members at a wall's face; the walls under a floor (faint) and on it (dashed)
  const nbs = !isWall(s) ? ["bearers", "loads"].map((key) => (s[key] || []).map((b) => {
    const [sx, sy] = b.side, d = b.depth || 3.5;
    const pts = [b.a, b.b, [b.b[0] + sx * d, b.b[1] + sy * d], [b.a[0] + sx * d, b.a[1] + sy * d]];
    return `<polygon class="${key === "bearers" ? "under" : "onit"}" points="${pts.map(([u, v]) => `${u},${-v}`).join(" ")}"><title>${esc(b.wall)} ${key === "bearers" ? "under" : "on"} this floor</title></polygon>`;
  }).join("")).join("") : s.neighbours.filter((b) => present(b.id)).map((b) =>
    `<rect class="nb" data-id="${b.id}" x="${b.lo[0]}" y="${-b.hi[1]}" width="${b.hi[0] - b.lo[0]}" height="${b.hi[1] - b.lo[1]}"><title>${b.id}, on another wall</title></rect>`).join("");
  const outline = `M${s.outline.map(([u, v]) => `${u} ${-v}`).join("L")}z`;
  const holes = s.openings.map((o) => `M${o.u0} ${-o.v1}h${o.u1 - o.u0}v${o.v1 - o.v0}h${o.u0 - o.u1}z`).join("");
  const surf = $("#showSurfaces").checked ? `<path class="surf" d="${outline}${holes}" fill="${SURF}" fill-opacity="${surfOp}" fill-rule="evenodd"/>` : "";
  const ops = s.openings.map((o) =>
    `<rect class="op" x="${o.u0}" y="${-o.v1}" width="${o.u1 - o.u0}" height="${o.v1 - o.v0}"/>` +
    `<text x="${(o.u0 + o.u1) / 2}" y="${-(o.v0 + o.v1) / 2}" text-anchor="middle" font-size="${17 * k}">${esc(o.id)} ${esc(o.kind)}</text>` +
    `<text x="${(o.u0 + o.u1) / 2}" y="${-(o.v0 + o.v1) / 2 + 20 * k}" text-anchor="middle" font-size="${15 * k}">${ftin(o.u1 - o.u0)} x ${ftin(o.v1 - o.v0)}</text>`).join("");
  const a = 7 * k;
  const only = st.only;
  const marks = showFaults ? st.data.faults.filter((f) => f.wall === s.id && f.u != null && f.check !== "backing" && (!only || f.check === only)).map((f) =>
    `<g class="mark ${f.hard ? "" : "soft"}"><title>${esc(f.message)}</title>
      <line x1="${f.u - a}" y1="${-f.v - a}" x2="${f.u + a}" y2="${-f.v + a}"/><line x1="${f.u - a}" y1="${-f.v + a}" x2="${f.u + a}" y2="${-f.v - a}"/></g>`).join("") : "";
  const gaps = showFaults && (!only || only === "backing") ? s.gaps.map((g) =>
    `<rect class="gap" x="${g.u0}" y="${-g.v1}" width="${g.u1 - g.u0}" height="${g.v1 - g.v0}" stroke="${FACE[g.face]}" fill="url(#hatch-${g.face}-${s.id})"><title>${faceName(s, g.face)}: ${g.kind === "edge" ? "a board edge" : "a board"} ${ftin(g.u1 - g.u0)} by ${ftin(g.v1 - g.v0)} with nothing behind it</title></rect>`).join("") : "";
  const tees = (s.tees || []).map((t) => `<g class="tee"><title>${esc(t.wall)} meets this wall here</title>
    <line x1="${t.u}" x2="${t.u}" y1="0" y2="${-V}"/><text x="${t.u}" y="${-V - 5 * k}" text-anchor="middle" font-size="${16 * k}">${esc(t.wall)}</text></g>`).join("");
  const hatch = (face, angle) => `<pattern id="hatch-${face}-${s.id}" patternUnits="userSpaceOnUse" width="${8 * k}" height="${8 * k}" patternTransform="rotate(${angle})">
      <line x1="0" y1="0" x2="0" y2="${8 * k}" stroke="${FACE[face]}" stroke-width="${1.4 * k}"/></pattern>`;
  return `<svg viewBox="${-pad} ${-(V + pad)} ${Math.max(span, U) + 2 * pad} ${V + 2 * pad}">
      <defs>${hatch("outer", 45)}${hatch("inner", -45)}</defs>
      ${surf}<path class="outline" d="${outline}"/>
      ${nbs}${rects}${tees}${ops}${gaps}${marks}${active ? targetSvg(s, k) : ""}${evidenceSvg(s, k)}
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

function renderElev() {
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
      const active = cur && (cur.wall === s.id || cur.target?.other === s.id);
      const tag = !active ? "" : `<span class="steptag">${pill(cur.rule, st.colors[cur.rule])} ${cur.wall !== s.id ? `matched ${esc(cur.match)} on ${esc(cur.wall)}, which meets this one`
        : trigger() ? `matched ${esc(cur.match)}` : `placed ${cur.placed.length} here`} at step ${stepNo()}</span>`;
      return `<div class="wall ${isWall(s) ? "" : "floor"} ${active ? "active" : ""} ${cur && !active ? "rest" : ""}" id="wall-${s.id}">
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
  const at = t.wall === s.id ? t : otherEnd(t)?.wall === s.id ? otherEnd(t) : null;
  if (!at) return "";
  if (isLine(at)) return `<line class="${cls}" x1="${at.u0}" x2="${at.u1}" y1="${-at.v0}" y2="${-at.v1}" stroke="${c}"/>`;
  const face = t.face === "inner" ? `<text x="${(at.u0 + at.u1) / 2}" y="${-at.v1 - 4 * k}" text-anchor="middle" font-size="${15 * k}">${faceName(s, "inner")}</text>` : "";
  return `<rect class="${cls}" x="${at.u0}" y="${-at.v1}" width="${at.u1 - at.u0}" height="${at.v1 - at.v0}" stroke="${c}" fill="${c}"/>${face}`;
}

$("#elev").addEventListener("click", (e) => {
  const r = e.target.closest("[data-id]");
  select(r && st.byId[r.dataset.id] ? { kind: "member", id: r.dataset.id } : null);
});

function renderStoreys() {
  // the storey filter in the view bar: All, 1, 2, 3
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

function renderCaption() {
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
    const ceilings = d.floors.filter((f) => f.role === "ceiling").length, roofs = (d.roofs || []).length;
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
    : `output: ${pill(s.rule, c)} ${what.join(", ")} on <b>${esc(s.wall)}</b>`;
  el.innerHTML = `<div class="c-top">step ${stepNo()} of ${n}, ${trigger() ? "trigger" : "output"}, pass ${s.pass}</div>
    <div class="c-main">${main}</div>
    ${r?.doc ? `<div class="c-doc">${esc(oneLine(r.doc))}</div>` : ""}
    ${trigger() && r?.when ? `<div class="c-doc">when <code>${esc(r.when)}</code></div>` : ""}`;
}

// ---------------------------------------------------------------- inspector

function chip(id) {
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

function renderInspect() {
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
  // every toy wall at one scale, in a frame fitted to the largest, so stepping between firings keeps still
  const w = d.wall, [L, H] = w.size, [SL, SH] = d.span;
  const pad = Math.max(SL, SH) / 50;
  const c = st.colors[d.rule] || "#888";
  const box = (b, cls, fillc) => memberSvg(b, `class="${cls}" fill="${fillc}"`, `${esc(b.id)} ${esc(b.role || b.rule)}`);
  const removed = new Set(d.removed.map((b) => b.id));
  const holes = w.openings.map((o) => `M${o.u0} ${-o.v1}h${o.u1 - o.u0}v${o.v1 - o.v0}h${o.u0 - o.u1}z`).join("");
  const before = d.before.filter((b) => !after || !removed.has(b.id));
  const t = d.target;
  return `<svg class="demo-svg" viewBox="${-pad - (SL - L) / 2} ${-(SH + pad)} ${SL + 2 * pad} ${SH + 2 * pad}">
    <path d="M${w.outline.map(([u, v]) => `${u} ${-v}`).join("L")}z${holes}" fill="${SURF}" fill-opacity="0.18" fill-rule="evenodd"/>
    <path class="outline" d="M${w.outline.map(([u, v]) => `${u} ${-v}`).join("L")}z"/>
    ${w.bearers.map((b) => {
      const [sx, sy] = b.side, dd = b.depth || 3.5;
      return `<polygon class="under" points="${[b.a, b.b, [b.b[0] + sx * dd, b.b[1] + sy * dd], [b.a[0] + sx * dd, b.a[1] + sy * dd]].map(([u, v]) => `${u},${-v}`).join(" ")}"/>`;
    }).join("")}
    ${d.neighbours.map((b) => box(b, "nb", "#e4e2dd")).join("")}
    ${before.map((b) => (t?.member === b.id ? box(b, `m now${after ? "" : " hit"}`, c) : box(b, "m", PAST))).join("")}
    ${after ? [...d.placed, ...(d.shaped || [])].map((b) => box(b, "m now", c)).join("") : d.removed.map((b) => box(b, "m gone", "none")).join("")}
    ${w.openings.map((o) => `<rect class="op" x="${o.u0}" y="${-o.v1}" width="${o.u1 - o.u0}" height="${o.v1 - o.v0}"/>`).join("")}
    ${w.tees.map((t) => `<g class="tee"><line x1="${t.u}" x2="${t.u}" y1="0" y2="${-H}"/><text x="${t.u}" y="${-H - pad / 4}" text-anchor="middle" font-size="${pad * 0.9}">${esc(t.wall)}</text></g>`).join("")}
    ${t && t.kind !== "member" ? (isLine(t)
      ? `<line class="target ${after ? "out" : "trig"}" x1="${t.u0}" x2="${t.u1}" y1="${-t.v0}" y2="${-t.v1}" stroke="${c}"/>`
      : `<rect class="target ${after ? "out" : "trig"}" x="${t.u0}" y="${-t.v1}" width="${t.u1 - t.u0}" height="${t.v1 - t.v0}" stroke="${c}" fill="${c}"/>`) : ""}
  </svg>`;
}

function demoHtml(d) {
  if (!d.wall) {
    return `<p class="empty demo-none">${esc(d.message || "This rule did nothing on the toy house.")}</p>
      ${d.errors?.length ? `<p class="bad">${esc(d.errors[0])}</p>` : ""}`;
  }
  const c = st.colors[d.rule] || "#888";
  const n = d.placed.length, r = d.removed.length, k = (d.shaped || []).length;
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
    <p class="dcap">On the toy house, ${d.wall.kind === "roof" ? "roof plane" : d.wall.role === "ceiling" ? "ceiling" : d.wall.kind} ${esc(d.wall.id)}${d.wall.kind !== "wall" ? (d.wall.role === "ceiling" ? " seen from below" : " seen from above") : ""}${d.target?.other ? ` where it meets ${esc(d.target.other)}` : ""}${d.target?.face === "inner" ? `, ${d.wall.kind === "floor" ? "ceiling" : "inside face"}` : ""},
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

const EV = "#d8342c";   // evidence drawn for the chosen fault
const axisOf = (m) => { const d = [0, 1, 2].map((k) => m.hi[k] - m.lo[k]); return d.indexOf(Math.max(...d)); };
const centre = (m) => [0, 1, 2].map((k) => (m.lo[k] + m.hi[k]) / 2);

function limitText(name) {
  // a limit from the verifier's constants, in feet and inches (or the unit its comment names)
  const c = st.vinfo?.constants[name];
  if (!c) return name;
  const v = c.value, len = (x) => (x >= 12 ? ftin(x) : inch(x));
  if (Array.isArray(v)) return `${len(Math.min(...v))} to ${len(Math.max(...v))}`;
  if (typeof v === "object") {
    const sec = Object.fromEntries(Object.entries(st.vinfo.sections).map(([n, d]) => [String(d), n]));
    return Object.entries(v).map(([d, x]) => `${sec[d] || inch(+d) + " deep"} ${len(x)}`).join(", ");
  }
  return /linear feet/.test(c.note) ? `${v} ft` : len(v);
}

function evidence(f) {
  // what to draw and say for one fault: members that hold it (supports), dimension lines, boxes, face rectangles
  const out = { supports: [], dims: [], boxes: [], rects: [], text: "" };
  const m = st.byId[f.members[0]];
  const name = (x) => `${x.id} (${esc(x.role || x.rule)})`;
  const limits = (ns) => ns.map((n) => `<span class="lim">${n}: ${limitText(n)}</span>`).join(" ");
  if ((f.check === "span" || f.check === "overhang") && m) {
    const k = axisOf(m), c = centre(m);
    const sup = m.bears.filter((id) => st.byId[id]).map((id) => {
      const s = st.byId[id];
      return [Math.max(m.lo[k], s.lo[k]), Math.min(m.hi[k], s.hi[k]), id];
    }).sort((a, b) => a[0] - b[0]);
    out.supports = sup.map((x) => x[2]);
    const at = (x) => { const p = [...c]; p[k] = x; p[2] = m.hi[2] + 4; return p; };   // a little above the member
    const lim = f.message.match(/limit (.+?)(?: for (.+))?$/);
    if (f.check === "span") {
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
    } else {
      const last = Math.max(...sup.map((x) => x[1])), first = sup[0]?.[0];
      const [a, b] = Math.abs(f.at[k] - m.lo[k]) < Math.abs(f.at[k] - m.hi[k]) ? [m.lo[k], first] : [last, m.hi[k]];
      out.dims.push({ a: at(a), b: at(b), text: `${ftin(b - a)} past its support, limit ${limitText("MAX_OVERHANG")}` });
      out.text = `${name(m)} runs <b>${ftin(b - a)}</b> past its last support; a loaded member may overhang at most <b>${limitText("MAX_OVERHANG")}</b>.`;
    }
  } else if (f.check === "bearing" && m) {
    const s = st.byId[f.members[1]], k = axisOf(m), c = centre(m);
    out.supports = s ? [s.id] : [];
    if (s) {
      const a = Math.max(m.lo[k], s.lo[k]), b = Math.min(m.hi[k], s.hi[k]);
      const at = (x) => { const p = [...c]; p[k] = x; p[2] = m.lo[2] - 2; return p; };
      out.dims.push({ a: at(a), b: at(b), text: `bears ${inch(b - a)}, minimum ${limitText("MIN_BEARING")}` });
    }
    out.text = `${esc(f.message)}. A member must sit at least <b>${limitText("MIN_BEARING")}</b> on what holds it.`;
  } else if (f.check === "clash" && m && st.byId[f.members[1]]) {
    const o = st.byId[f.members[1]];
    const lo = [0, 1, 2].map((k) => Math.max(m.lo[k], o.lo[k])), hi = [0, 1, 2].map((k) => Math.min(m.hi[k], o.hi[k]));
    out.boxes.push({ lo, hi });
    out.text = `${name(m)} and ${name(o)} occupy the same space: the red box, ${inch(hi[0] - lo[0])} x ${inch(hi[1] - lo[1])} x ${inch(hi[2] - lo[2])}.
      Two pieces of timber cannot overlap; one must stop short, or be notched (not modelled yet).`;
  } else if (f.check === "backing") {
    const s = st.surf[f.wall], face = /inner face/.test(f.message) ? "inner" : "outer";
    const g = s?.gaps.find((x) => x.face === face && Math.abs((x.u0 + x.u1) / 2 - f.u) < 0.6 && Math.abs((x.v0 + x.v1) / 2 - f.v) < 0.6);
    if (g) {
      const W = g.u1 - g.u0, H = g.v1 - g.v0;
      out.rects.push({ sid: s.id, face, ...g, text: `${ftin(W)} x ${ftin(H)}` });
      out.text = g.kind === "edge"
        ? `On the ${faceName(s, face)} of ${s.id}, a board edge runs <b>${ftin(Math.max(W, H))}</b> with nothing behind it.
           An edge needs backing at least every <b>${limitText("MAX_EDGE")}</b>, so blocking or clips will do.`
        : `On the ${faceName(s, face)} of ${s.id}, a board spans <b>${ftin(W)} by ${ftin(H)}</b> with nothing behind it.
           It needs support within <b>${limitText("MAX_CLEAR")}</b> in at least one direction (24" centres less one stud).`;
    } else out.text = esc(f.message);
  } else if (f.check === "floating" && m) {
    const list = (ids) => ids.filter((id) => st.byId[id] || id === "ground").map(chip).join("") || "nothing";
    out.text = `${name(m)} has no chain of bearing down to the ground. It bears on: ${list(m.bears)}. Beside it: ${list(m.side)}.
      None of these is held up, and it is not nailed between two held-up members at both ends.`;
  } else {
    out.text = `${esc(f.message)}.`;
  }
  return out;
}

const chosenFault = () => (st.fault != null ? st.data.faults[st.fault] : null);

function renderEvidence3d() {
  clear(evGroup);
  const f = chosenFault();
  if (!f) return;
  const ev = evidence(f);
  const P = (p) => new THREE.Vector3(...p.map((x) => x * S));
  const mat = new THREE.LineBasicMaterial({ color: EV, depthTest: false });
  for (const d of ev.dims) {
    const a = P(d.a), b = P(d.b);
    const tick = new THREE.Vector3(0, 0, 3 * S);
    const line = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints([a, b, a.clone().sub(tick), a.clone().add(tick), b.clone().sub(tick), b.clone().add(tick)]), mat);
    line.renderOrder = 12;
    evGroup.add(line);
    label(esc(d.text), "evidence", a.clone().add(b).multiplyScalar(0.5).add(new THREE.Vector3(0, 0, 4 * S)), evGroup);
  }
  for (const bx of ev.boxes) {
    const size = [0, 1, 2].map((k) => Math.max(0.2, bx.hi[k] - bx.lo[k]) * S);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), new THREE.MeshBasicMaterial({ color: EV, transparent: true, opacity: 0.55, depthTest: false }));
    mesh.position.copy(P([0, 1, 2].map((k) => (bx.lo[k] + bx.hi[k]) / 2)));
    mesh.renderOrder = 12;
    evGroup.add(mesh);
  }
  for (const r of ev.rects) {
    markOn(evGroup, r.sid, r, EV, true, r.face);
    const s = st.surf[r.sid];
    label(esc(r.text), "evidence", new THREE.Vector3(((r.u0 + r.u1) / 2) * S, ((r.v0 + r.v1) / 2) * S, 0).applyMatrix4(surfMatrix(s)), evGroup);
  }
  if (!ev.dims.length && !ev.boxes.length && !ev.rects.length && f.at) {
    const ring = new THREE.Mesh(new THREE.SphereGeometry(0.12, 20, 14), new THREE.MeshBasicMaterial({ color: EV, transparent: true, opacity: 0.5, depthTest: false }));
    ring.position.copy(P(f.at));
    ring.renderOrder = 12;
    evGroup.add(ring);
  }
}

function evidenceSvg(s, k) {
  const f = chosenFault();
  if (!f || f.wall !== s.id) return "";
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

function renderVerifier() {
  const el = $("#faults");
  const d = st.data, vi = st.vinfo;
  if (!d || !vi) { el.innerHTML = `<p class="empty">Loading the verifier...</p>`; return; }
  const s = d.stats, cost = vi.constants.PIECE_COST?.value ?? 0;
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
          The lumber bought counts in proportion to its depth, as linear feet of 2x4, and every piece adds ${cost} ft for cutting, handling and nailing.</p>
        <table class="costs"><tr><th>section</th><th>pieces</th><th>bought</th><th>depth</th><th>as 2x4</th></tr>${rows}
          <tr><td colspan="4">${s.members} pieces x ${cost} ft</td><td>${num(s.members * cost)} ft</td></tr>
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

function zoomTo(p) {
  // keep the viewing direction, come within about ten feet of a point
  showTab("view3d");
  const t = new THREE.Vector3(...p.map((x) => x * S));
  const dir = camera.position.clone().sub(controls.target).normalize();
  controls.target.copy(t);
  camera.position.copy(t).addScaledVector(dir, 3);
}

function chooseFault(i) {
  st.fault = st.fault === i ? null : i;
  st.sel = null;
  const f = chosenFault();
  if (f && st.storey && !shown3d(f.wall)) st.storey = 0;
  renderStoreys();
  look3d();
  renderElev();
  renderInspect();
  renderVerifier();
  if (f?.wall && $("#elev").classList.contains("on")) document.getElementById(`wall-${f.wall}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
}

// ---------------------------------------------------------------- report

function renderReport() {
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

function renderTimeline() {
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
    : `step ${i / 2}, output: ${esc(s.rule)} placed ${s.placed.length}${s.removed.length ? `, removed ${s.removed.length}` : ""} on ${esc(s.wall)}`;
}

function goto(at) {
  if (!st.data) return;
  st.at = Math.max(0, Math.min(2 * st.data.steps.length, at));
  renderTimeline();
  renderRules();
  renderCaption();
  look3d();
  renderElev();
  const cur = current();
  if (cur && $("#elev").classList.contains("on")) {
    document.getElementById(`wall-${cur.wall}`)?.scrollIntoView({ block: "nearest", behavior: st.playing ? "auto" : "smooth" });
  }
}

function stopPlay() {
  if (st.playing) clearInterval(st.playing);
  st.playing = null;
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

// a small tooltip shared by the strip and the run charts
function showTip(html, rect, where = "above") {
  const tip = $("#tip");
  const host = $("#stage").getBoundingClientRect();
  tip.innerHTML = html;
  tip.hidden = false;
  const x = Math.max(4, Math.min(host.width - tip.offsetWidth - 4, rect.left + rect.width / 2 - host.left - tip.offsetWidth / 2));
  const y = where === "above" ? rect.top - host.top - tip.offsetHeight - 6 : rect.bottom - host.top + 6;
  tip.style.left = `${x}px`;
  tip.style.top = `${Math.max(2, y)}px`;
}
function hideTip() { $("#tip").hidden = true; }

// ---------------------------------------------------------------- editor

function editState() {
  const d = dirty();
  $("#edState").innerHTML = d
    ? `<b>Unsaved${st.origin ? `: ${esc(st.origin)}` : " edits"}.</b> Builds use them. Save writes grammars/${esc($("#grammar").value)}.py; Revert goes back to it.`
    : `Saved as grammars/${esc($("#grammar").value)}.py. Edit, then Build with this (Cmd+Enter) to try it.`;
  $("#edState").className = d ? "dirty" : "";
  $("#dirty").textContent = d ? "*" : "";
}

function jumpToRule(name) {
  const r = st.data.rules.find((x) => x.name === name);
  showTab("editor");
  if (!r) return;
  const ta = $("#src");
  const lines = ta.value.split("\n");
  const start = lines.slice(0, Math.max(0, r.line - 2)).join("\n").length + (r.line > 1 ? 1 : 0);
  const end = lines.slice(0, r.end).join("\n").length;
  ta.focus();
  ta.setSelectionRange(start, end);
  ta.scrollTop = Math.max(0, (r.line - 4) * 18.6);
}

$("#src").addEventListener("input", () => { setFollow(false); editState(); });
$("#src").addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    const ta = e.target;
    const [a, b] = [ta.selectionStart, ta.selectionEnd];
    ta.setRangeText("    ", a, b, "end");
    editState();
  }
});
$("#edBuild").addEventListener("click", build);
$("#edRevert").addEventListener("click", () => { setFollow(false); $("#src").value = st.saved; st.origin = null; editState(); build(); });
$("#edSave").addEventListener("click", async () => {
  try {
    await api("PUT", `/api/grammar/${$("#grammar").value}`, { source: $("#src").value });
    st.saved = $("#src").value;
    st.origin = null;
    editState();
    status(`saved grammars/${$("#grammar").value}.py`);
  } catch (e) { status(e.message, true); }
});
$("#edScore").addEventListener("click", async () => {
  const g = $("#grammar").value;
  try {
    const job = await api("POST", "/api/jobs", { kind: "evaluate", settings: {
      grammar: `grammars/${g}.py`, houses: houseList.map((h) => `data/houses/${h.id}.json`) } });
    rs.anyRunning = true;
    rs.watch.add(job.id);
    status(`scoring grammars/${g}.py on ${houseList.length} houses${dirty() ? " (the saved file, not your unsaved edits)" : ""}; Runs shows the log`);
  } catch (e) { status(e.message, true); }
});

// ---------------------------------------------------------------- Runs: the search, and steering it

const rs = {
  list: [], name: recall("run"), run: null, sel: null, src: {}, jobs: [], creds: null,
  anyRunning: false, watch: new Set(), mainKey: "", form: null,
};

async function loadRunsList() {
  rs.list = await api("GET", "/api/runs");
  if (!rs.list.some((r) => r.name === rs.name) && !runningSearch(rs.name)) rs.name = rs.list[0]?.name ?? null;
}

async function loadRun() {
  rs.run = null;
  if (rs.name && rs.list.some((r) => r.name === rs.name)) {
    try { rs.run = await api("GET", `/api/run/${rs.name}`); } catch (e) { status(e.message, true); }
  }
}

async function pollJobs() {
  const was = new Set(rs.jobs.filter((j) => j.status === "running").map((j) => j.id));
  const j = await api("GET", "/api/jobs");
  rs.jobs = j.jobs;
  rs.creds = j.credentials;
  const running = rs.jobs.filter((x) => x.status === "running");
  rs.anyRunning = running.length > 0;
  $("#runDot").textContent = running.some((x) => x.kind === "evolve") ? "●" : "";
  return { running, ended: rs.jobs.filter((x) => was.has(x.id) && x.status !== "running") };
}

const runningSearch = (name) => rs.jobs.find((j) => j.kind === "evolve" && j.status === "running" && j.settings?.run === name);
const liveRun = (name) => !!runningSearch(name) || !!rs.list.find((r) => r.name === name)?.live;

async function enterRuns() {
  try {
    await pollJobs();
    await loadRunsList();
    await loadRun();
  } catch (e) { status(e.message, true); }
  if (liveRun(rs.name) && lv.run !== rs.name) startLive(rs.name, true);
  rs.mainKey = "";
  renderRuns();
}

function renderRuns() {
  renderRunsSide();
  renderRunsMain();
  renderRunsDetail();
}

async function tick() {
  if (!runsMode() && !rs.anyRunning) return;
  let r;
  try { r = await pollJobs(); } catch { return; }
  for (const j of r.ended) {
    if (!rs.watch.has(j.id)) continue;
    rs.watch.delete(j.id);
    if (j.kind === "tests") status(j.status === "done" ? "tests passed" : `tests ${j.status}: see the log in Runs`, j.status !== "done");
    else if (j.kind === "evaluate") status(j.status === "done" ? "scoring finished: the log in Runs has the results" : `scoring ${j.status}`, j.status !== "done");
    else status(`search ${j.settings?.run}: ${j.status}`, j.status === "failed");
  }
  if (!runsMode()) return;
  if (r.running.some((j) => j.kind === "evolve") || r.ended.length || rs.list.some((x) => x.live)) {
    await loadRunsList();
    await loadRun();
  }
  renderRunsSide();
  renderRunsMain();
  if (rs.sel?.kind === "job") renderRunsDetail(true);
}
setInterval(tick, 2000);

// ---- side: runs, jobs, tests

function renderRunsSide() {
  const lastTest = rs.jobs.find((j) => j.kind === "tests");
  const testState = !lastTest ? "" : lastTest.status === "running" ? `<span class="muted">running...</span>`
    : lastTest.status === "done" ? `<span class="good">passed</span> <span class="muted">${ago(lastTest.ended)}</span>`
    : `<span class="bad">${lastTest.status === "failed" ? "failed" : lastTest.status}</span> <span class="muted">${ago(lastTest.ended)}</span>`;
  const pending = rs.name && !rs.list.some((r) => r.name === rs.name) ? [{ name: rs.name, pending: true }] : [];
  $("#runsSide").innerHTML = `
    <h3>Runs</h3>
    <ul class="list">${[...pending, ...rs.list].map((r) => `<li data-run="${esc(r.name)}" class="${r.name === rs.name ? "sel" : ""}">
      <b>${esc(r.name)}</b>${liveRun(r.name) ? ` <span class="live">searching</span>` : ""}
      <small>${r.pending ? "starting..." : `${r.iterations} iterations, ${r.candidates} grammars kept, ${esc(r.model)}`}</small></li>`).join("")
      || `<li class="empty">No runs yet.</li>`}</ul>
    <button data-act="new" class="${rs.sel?.kind === "new" ? "on" : ""}">New run</button>
    <h3>Tests</h3>
    <div class="row"><button data-act="tests" ${lastTest?.status === "running" ? "disabled" : ""}>Run tests</button> ${testState}</div>
    <h3>Jobs <small>searches, tests, scoring</small></h3>
    <ul class="list jobs">${rs.jobs.slice(0, 15).map((j) => `<li data-job="${esc(j.id)}" class="${rs.sel?.kind === "job" && rs.sel.id === j.id ? "sel" : ""}">
      <span class="jst ${j.status}">${j.status}</span> ${esc(j.title)}<small>${ago(j.started)}</small></li>`).join("")
      || `<li class="empty">Searches, test runs and scoring you start here are listed with their logs.</li>`}</ul>`;
}

$("#runsSide").addEventListener("click", async (e) => {
  const run = e.target.closest("[data-run]");
  if (run) {
    rs.name = run.dataset.run;
    remember("run", rs.name);
    rs.sel = null;
    if (liveRun(rs.name)) startLive(rs.name, true);
    await loadRun();
    rs.mainKey = "";
    return renderRuns();
  }
  const job = e.target.closest("[data-job]");
  if (job) { rs.sel = { kind: "job", id: job.dataset.job }; renderRunsSide(); return renderRunsDetail(); }
  const act = e.target.closest("button[data-act]")?.dataset.act;
  if (act === "new") { rs.sel = { kind: "new" }; renderRunsSide(); return renderRunsDetail(); }
  if (act === "tests") {
    try {
      const j = await api("POST", "/api/jobs", { kind: "tests", settings: {} });
      rs.watch.add(j.id);
      rs.sel = { kind: "job", id: j.id };
      await pollJobs();
      renderRunsSide();
      renderRunsDetail();
    } catch (err) { status(err.message, true); }
  }
});

// ---- main: the selected run

const fmtScore = (s) => `${s[0]} hard, ${s[1]} soft, cost ${num(s[2])} ft`;
const lt = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

function renderRunsMain() {
  const el = $("#runsMain");
  const run = rs.run;
  const job = runningSearch(rs.name);
  const key = JSON.stringify([rs.name, run?.iterations.length, run?.candidates.length, job?.id, rs.creds?.ok, rs.sel, liveRun(rs.name), lv.run]);
  if (key === rs.mainKey) return;
  rs.mainKey = key;
  if (!run) {
    el.innerHTML = rs.name && job ? `<div class="empty-big"><h2>${esc(rs.name)}</h2>
        <p>Starting: the seed grammar is being scored on the training houses. The run appears here in a moment.</p></div>`
      : `<div class="empty-big"><h2>The search</h2>
        <p>A run evolves a grammar. Each iteration, Claude proposes an edit to a grammar; the verifier scores it on a few
        training houses, and the edit is kept only if it beats its parent there. The grammars that are best on some house
        form the Pareto set.</p><p>No runs yet. Start one with <b>New run</b> on the left.</p></div>`;
    return;
  }
  const c = run.config;
  const its = run.iterations;
  const kept = run.candidates.length - 1;
  el.innerHTML = `
    <div class="runhead"><h2>${esc(run.name)}</h2>
      <p class="muted">${esc(c.model)} proposer, ${run.houses.length} training houses, ${c.minibatch} per iteration,
        ${its.length} iterations, ${kept} edits kept. Started ${c.created ? new Date(c.created * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "?"}.</p>
      ${steerHtml(run, job)}${lv.run === run.name && liveRun(run.name) ? `<div id="runLive"></div>` : ""}</div>
    ${paretoView(run)}
    <section><h3>Progress <small>the best grammar so far, summed over the ${run.houses.length} training houses</small></h3>${progressSvg(run)}</section>
    <section><h3>Iterations <small>newest first; click one to see what the proposer saw and did</small></h3>${iterList(run)}</section>`;
  renderRunLive();
}

function steerHtml(run, job) {
  if (job?.detached) {
    return `<div class="steer live"><span class="livedot"></span> Searching: ${esc(job.title)}, started ${ago(job.started)},
      before the workbench last restarted, so stop it from the terminal if needed.</div>`;
  }
  if (job) {
    return `<div class="steer live"><span class="livedot"></span> Searching: ${esc(job.title)}, started ${ago(job.started)}.
      <button data-act="stop" title="Finish the current iteration, then stop">Stop after this iteration</button>
      <button data-act="kill" class="danger" title="End the search now; the current iteration is lost">Kill now</button></div>`;
  }
  const scripted = run.config.model === "scripted";
  const dry = scripted || !rs.creds?.ok;
  return `<div class="steer">Continue for <input type="number" id="ctN" value="5" min="1" max="500"> iterations
    <label class="chk"><input type="checkbox" id="ctDry" ${dry ? "checked" : ""}> dry run (no Claude)</label>
    <button data-act="continue" class="primary">Continue</button>
    <span class="cred">${credLine()}</span></div>`;
}

function credLine() {
  if (!rs.creds) return "";
  return rs.creds.ok ? `<span class="good">Claude reachable</span> <span class="muted">(${esc(rs.creds.how)})</span>`
    : `<span class="bad">Claude not reachable.</span> <span class="muted">${esc(rs.creds.how)}</span>`;
}

$("#runsMain").addEventListener("click", async (e) => {
  const act = e.target.closest("button[data-act]")?.dataset.act;
  if (act === "continue") {
    const dry = $("#ctDry").checked;
    if (!dry && !rs.creds?.ok) return status("Claude is not reachable; tick dry run, or set credentials first.", true);
    const settings = { run: rs.name, iterations: +$("#ctN").value || 5, dry };
    if (!dry && /^claude-/.test(rs.run.config.model)) settings.model = rs.run.config.model;
    return startSearch(settings);
  }
  if (act === "stop" || act === "kill") {
    const job = runningSearch(rs.name);
    if (!job) return;
    try {
      await api("POST", `/api/job/${job.id}/${act}`);
      status(act === "stop" ? `${rs.name} stops after the current iteration` : `${rs.name} killed`);
      await tick();
    } catch (err) { status(err.message, true); }
    return;
  }
  const zoom = e.target.closest("a[data-zoom]");
  if (zoom) { e.preventDefault(); rs.zoom = zoom.dataset.zoom; rs.mainKey = ""; return renderRunsMain(); }
  const yk = e.target.closest("button[data-yk]");
  if (yk) { rs.yk = yk.dataset.yk; rs.mainKey = ""; return renderRunsMain(); }
  const open = e.target.closest("button[data-open]");
  const cell = e.target.closest("td[data-house]");
  const cand = e.target.closest("[data-cand]");
  if (open) return openCandidate(open.dataset.open);
  if (cell && cand) return openCandidate(cand.dataset.cand, cell.dataset.house);
  if (cand) { rs.sel = { kind: "cand", id: cand.dataset.cand }; rs.mainKey = ""; renderRunsMain(); return renderRunsDetail(); }
  const it = e.target.closest("[data-it]");
  if (it) { rs.sel = { kind: "iter", n: +it.dataset.it }; rs.mainKey = ""; renderRunsMain(); return renderRunsDetail(); }
});

async function startSearch(settings) {
  try {
    const job = await api("POST", "/api/jobs", { kind: "evolve", settings });
    rs.watch.add(job.id);
    rs.name = settings.run;
    remember("run", rs.name);
    rs.sel = { kind: "job", id: job.id };
    status(`started ${job.title}`);
    await pollJobs();
    await loadRunsList();
    await loadRun();
    rs.mainKey = "";
    renderRuns();
    return true;
  } catch (err) {
    status(err.message, true);
    return err.message;
  }
}

// best total so far after each iteration, as three small charts sharing the iteration axis
function progressSvg(run) {
  const N = Math.max(0, ...run.iterations.map((i) => i.iteration));
  const best = [];
  for (let i = 0; i <= N; i++) {
    const pool = run.candidates.filter((c) => c.iteration <= i).map((c) => c.total);
    best.push(pool.length ? pool.reduce((a, b) => (lt(b, a) < 0 ? b : a)) : null);
  }
  const W = 640, L = 118, R = 70, rowH = 40, gap = 16, top = 10;
  const pw = W - L - R;
  const x = (i) => L + (N ? (i / N) * pw : pw / 2);
  const rows = [
    { k: 0, label: "hard faults", note: "must reach 0", color: "#c8322b", zero: true },
    { k: 1, label: "soft faults", color: "#d98200" },
    { k: 2, label: "cost", note: "linear ft", color: "#2f6fdf", zero: false },
  ];
  let svg = "";
  rows.forEach((row, ri) => {
    const y0 = top + ri * (rowH + gap);
    const vals = best.map((b) => (b ? b[row.k] : null));
    const known = vals.filter((v) => v != null);
    // hard faults from zero, so "none" sits on the baseline; the others zoomed to their range
    let lo = Math.min(...known), hi = Math.max(...known);
    if (row.zero) { lo = 0; hi = Math.max(hi, 1); }
    else { const m = (hi - lo) * 0.15 || Math.abs(hi) * 0.05 || 1; lo -= m; hi += m; }
    const y = (v) => y0 + rowH - ((v - lo) / (hi - lo)) * rowH;
    let d = "";
    vals.forEach((v, i) => {
      if (v == null) return;
      d += d ? `H${x(i)}V${y(v)}` : `M${x(i)} ${y(v)}`;
    });
    if (N === 0 && known.length) d += `H${x(0) + 1}`;
    const last = known[known.length - 1];
    const flatZero = row.zero && known.every((v) => v === 0);
    svg += `<rect class="band" x="${L}" y="${y0 - 4}" width="${pw}" height="${rowH + 8}"/><line class="base" x1="${L}" x2="${L + pw}" y1="${y0 + rowH}" y2="${y0 + rowH}"/>
      <text class="rl" x="0" y="${y0 + 14}">${row.label}</text>
      ${row.note ? `<text class="rn" x="0" y="${y0 + 28}">${row.note}</text>` : ""}
      <path d="${d}" fill="none" stroke="${row.color}" stroke-width="2"/>
      <text class="rv" x="${L + pw + 8}" y="${y(last) + 4}">${row.k === 2 ? num(last) : last}</text>
      ${flatZero ? `<text class="rn" x="${L + 6}" y="${y0 + rowH - 6}">none at any point</text>` : ""}
      ${run.iterations.filter((it) => it.accepted).map((it) =>
        `<circle cx="${x(it.iteration)}" cy="${y(vals[it.iteration])}" r="4.5" fill="${row.color}" stroke="#fff" stroke-width="2"/>`).join("")}`;
  });
  const ym = top + 3 * (rowH + gap) + 4;
  svg += `<text class="rl" x="0" y="${ym + 4}">iterations</text>` + run.iterations.map((it) => {
    const cx = x(it.iteration);
    return it.accepted ? `<circle cx="${cx}" cy="${ym}" r="5" fill="#2f8a4a"/>`
      : it.error ? `<path d="M${cx - 3.5} ${ym - 3.5}l7 7m0 -7l-7 7" stroke="#9a978f" stroke-width="1.6"/>`
      : `<circle cx="${cx}" cy="${ym}" r="4" fill="none" stroke="#9a978f" stroke-width="1.6"/>`;
  }).join("");
  const ticks = [...new Set([0, N, ...(N > 4 ? [Math.round(N / 2)] : [])])];
  svg += ticks.map((i) => `<text class="tk" x="${x(i)}" y="${ym + 20}" text-anchor="middle">${i}</text>`).join("");
  const colW = N ? pw / N : pw;
  svg += `<line id="xhair" x1="0" x2="0" y1="${top}" y2="${ym + 6}" stroke="#1d1d1b" stroke-opacity=".25" visibility="hidden"/>`;
  svg += best.map((b, i) => `<rect class="hit" data-ci="${i}" x="${x(i) - colW / 2}" y="0" width="${colW}" height="${ym + 24}" fill="transparent"/>`).join("");
  const H = ym + 26;
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" width="100%" data-best='${esc(JSON.stringify(best))}'>${svg}</svg>
    <div class="legend"><span style="--c:#2f8a4a">kept</span><span class="hollow">not better</span><span class="cross">no change or error</span>
    <span class="muted">dots on the lines mark kept edits; hard faults count most, then soft faults, then cost</span></div></div>`;
}

$("#runsMain").addEventListener("pointermove", (e) => {
  const hit = e.target.closest("rect.hit");
  const cell = e.target.closest("td[data-tip]");
  const xh = $("#xhair");
  if (hit) {
    const svg = hit.ownerSVGElement;
    const i = +hit.dataset.ci;
    const b = JSON.parse(svg.dataset.best)[i];
    const it = rs.run.iterations.find((x) => x.iteration === i);
    const verdict = i === 0 ? "the seed grammar" : !it ? "" : it.accepted ? `kept as ${it.child}` : it.error ? esc(it.error) : "not better than its parent";
    const cx = +hit.getAttribute("x") + +hit.getAttribute("width") / 2;
    xh.setAttribute("x1", cx); xh.setAttribute("x2", cx); xh.setAttribute("visibility", "visible");
    const r = hit.getBoundingClientRect();
    showTip(`<b>after iteration ${i}</b>: ${verdict}<br>best so far: ${b ? fmtScore(b) : "-"}`,
      { left: r.left, width: r.width, top: svg.getBoundingClientRect().top, bottom: 0 }, "above");
  } else if (cell) {
    showTip(cell.dataset.tip, cell.getBoundingClientRect(), "above");
    xh?.setAttribute("visibility", "hidden");
  } else {
    if (!e.target.closest("#pf [data-cand]")) hideTip();   // a grammar keeps the tip it got on pointerover
    xh?.setAttribute("visibility", "hidden");
  }
});
$("#runsMain").addEventListener("pointerleave", hideTip);

// ---- the Pareto set: houses x grammars, the lineage, the trade-off; hovering one grammar lights it up in all three

const headline = (t) => (t[0] ? `${t[0]} hard` : t[1] ? `${t[1]} soft` : `${(t[2] / 1000).toFixed(1)}k ft`);
const headCls = (t) => (t[0] ? "bad" : t[1] ? "warn" : "");

function paretoView(run) {
  return `<section id="pf"><h3>Pareto set</h3>
    <p class="explain">Each grammar is scored on every house. The Pareto set keeps every grammar that is best on at least one
    house; the search picks parents from it, more often the more houses they win.</p>
    ${houseMatrix(run)}
    <h4>Lineage <small>parent to child, by iteration</small></h4>${lineageSvg(run)}
    <h4>Trade-off <small>totals over ${run.houses.length} houses</small>
      <span class="seg2">${["hard", "soft"].map((k) => `<button data-yk="${k}" class="${(rs.yk || "hard") === k ? "on" : ""}">${k} faults</button>`).join("")}</span></h4>
    ${tradeoffSvg(run, rs.yk === "soft" ? 1 : 0)}</section>`;
}

function footprint(walls) {
  if (!walls?.length) return "";
  const xs = walls.flatMap((w) => [w[0], w[2]]), ys = walls.flatMap((w) => [w[1], w[3]]);
  const [x0, y0] = [Math.min(...xs), Math.min(...ys)], s = Math.max(Math.max(...xs) - x0, Math.max(...ys) - y0) || 1;
  const k = 26 / s;   // fit in 26 px; north up, so y flips
  return `<svg class="fp" viewBox="-2 -2 30 30" width="30" height="30">${walls.map((w) =>
    `<line x1="${(w[0] - x0) * k}" y1="${26 - (w[1] - y0) * k}" x2="${(w[2] - x0) * k}" y2="${26 - (w[3] - y0) * k}" class="${w[4] ? "in" : ""}"/>`).join("")}</svg>`;
}

function houseMatrix(run) {
  const H = run.houses;
  const col = Object.fromEntries(H.map((h) => {
    const sc = run.candidates.map((c) => c.scores[h]).filter(Boolean);
    const best = sc.reduce((a, b) => (lt(b, a) < 0 ? b : a), sc[0]);
    return [h, { best, lo: Math.min(...sc.map((x) => x[2])), hi: Math.max(...sc.map((x) => x[2])) }];
  }));
  const rows = run.candidates.map((c) => {
    const wins = run.pareto[c.id]?.length || 0;
    const cls = [wins ? "" : "dom", rs.sel?.kind === "cand" && rs.sel.id === c.id ? "sel" : ""].join(" ");
    const cells = H.map((h) => {
      const sc = c.scores[h], k = col[h];
      if (!sc) return `<td></td>`;
      const win = lt(sc, k.best) === 0;
      const w = k.hi > k.lo ? 25 + 75 * (sc[2] - k.lo) / (k.hi - k.lo) : 60;
      const tone = sc[0] ? "hard" : sc[1] ? "soft" : win ? "win" : "";
      const mark = sc[0] ? `<i class="bad">${sc[0]}</i>` : sc[1] ? `<i class="warn">${sc[1]}</i>` : "";
      return `<td data-house="${esc(h)}" class="${win ? "win" : ""}" data-tip="${esc(`<b>${c.id}</b> on ${h}: ${fmtScore(sc)}${win ? "<br>the best on this house" : ""}<br>click to open it in 3D`)}">
        <span class="bar ${tone}" style="width:${w}%"></span>${mark}</td>`;
    }).join("");
    return `<tr data-cand="${esc(c.id)}" class="${cls}">
      <th><span class="pdot ${wins ? "on" : ""}"></span>${esc(c.id)} <small class="${headCls(c.total)}">${headline(c.total)}</small></th>${cells}
      <td class="won" title="${wins ? `best on ${wins} of ${H.length} houses` : "not best on any house: dominated"}">
        <span class="wonbar"><span style="width:${(100 * wins) / H.length}%"></span></span>${wins || ""}</td>
      <td><button class="open" data-open="${esc(c.id)}" title="Open this grammar in 3D on the current house">open</button></td></tr>`;
  }).join("");
  return `<table class="pm"><thead><tr><th></th>${H.map((h) => `<th title="${esc(h)}">${footprint(run.footprints?.[h])}<div>${esc(h)}</div></th>`).join("")}
    <th>houses won</th><th></th></tr></thead><tbody>${rows}</tbody></table>
    <p class="hint">A bar per grammar and house: its length is the cost, from the cheapest to the dearest on that house; a number
    counts hard faults (red) or soft faults (amber). Green: the best on that house. Click a bar to open that grammar on that house.</p>`;
}

function lineageSvg(run) {
  const C = run.candidates, by = Object.fromEntries(C.map((c) => [c.id, c]));
  const kids = {};
  for (const c of C) (kids[c.parent] ||= []).push(c);
  const lane = {};
  let lanes = 0;
  const place = (c, l) => {   // the first child carries on its parent's lane; later ones branch below
    lane[c.id] = l;
    (kids[c.id] || []).sort((a, b) => a.iteration - b.iteration).forEach((k, i) => place(k, i ? lanes++ : l));
  };
  for (const root of C.filter((c) => !by[c.parent])) place(root, lanes++);
  const N = Math.max(1, ...C.map((c) => c.iteration));
  const W = 680, L = 24, R = 30, top = 22, lh = 54;
  const x = (c) => L + (c.iteration / N) * (W - L - R), y = (c) => top + lane[c.id] * lh;
  const edges = C.filter((c) => by[c.parent]).map((c) => {
    const p = by[c.parent], mx = (x(p) + x(c)) / 2;
    return `<path data-cand="${esc(c.id)}" class="edge" d="M${x(p)} ${y(p)}C${mx} ${y(p)} ${mx} ${y(c)} ${x(c)} ${y(c)}"/>`;
  }).join("");
  const nodes = C.map((c) => {
    const on = !!run.pareto[c.id], sel = rs.sel?.kind === "cand" && rs.sel.id === c.id;
    return `<g data-cand="${esc(c.id)}" class="node ${on ? "on" : "dom"} ${sel ? "sel" : ""}">
      <circle cx="${x(c)}" cy="${y(c)}" r="7"/><text x="${x(c)}" y="${y(c) - 11}" text-anchor="middle">${esc(c.id)}</text>
      <text class="sub ${headCls(c.total)}" x="${x(c)}" y="${y(c) + 20}" text-anchor="middle">${headline(c.total)}</text></g>`;
  }).join("");
  const H = top + (lanes - 1) * lh + 40;
  const ticks = [0, ...(N > 1 ? [Math.round(N / 2), N] : [N])].map((i) =>
    `<text class="tk" x="${L + (i / N) * (W - L - R)}" y="${H - 2}" text-anchor="middle">${i}</text>`).join("");
  return `<svg class="tree" viewBox="0 0 ${W} ${H + 4}" width="100%">${edges}${nodes}${ticks}</svg>
    <p class="hint">Green: in the Pareto set. Grey: kept once, now beaten on every house. The axis is the iteration.</p>`;
}

function tradeoffSvg(run, k) {
  // close up: leave out grammars far worse than the best on this measure, which squash the rest into a corner
  const all = run.candidates, lo = Math.min(...all.map((c) => c.total[k])), hi = Math.max(...all.map((c) => c.total[k]));
  const near = all.filter((c) => c.total[k] <= lo + Math.max(5, 0.1 * (hi - lo)));
  const close = rs.zoom !== "all" && near.length > 1 && near.length < all.length;
  const C = close ? near : all;
  const off = all.filter((c) => !C.includes(c));
  const W = 680, H = 230, L = 44, R = 20, T = 14, B = 30;
  const xs = C.map((c) => c.total[2]), ys = C.map((c) => c.total[k]);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)], pad = (x1 - x0) * 0.08 || x0 * 0.05 || 1;
  const ymax = Math.max(1, ...ys);
  const px = (v) => L + ((v - x0 + pad) / (x1 - x0 + 2 * pad)) * (W - L - R);
  const py = (v) => T + (1 - Math.sqrt(v / ymax)) * (H - T - B);   // square root, so small counts stay apart from big ones
  // grammars no other beats on both totals, cheapest first: the frontier
  const front = [...C].sort((a, b) => a.total[2] - b.total[2] || a.total[k] - b.total[k])
    .reduce((f, c) => (!f.length || c.total[k] < f.at(-1).total[k] ? [...f, c] : f), []);
  const line = front.map((c, i) => (i ? `H${px(c.total[2])}V${py(c.total[k])}` : `M${px(c.total[2])} ${py(c.total[k])}`)).join("");
  const onFront = new Set(front.map((c) => c.id));
  const pts = C.map((c) => {
    const sel = rs.sel?.kind === "cand" && rs.sel.id === c.id;
    return `<g data-cand="${esc(c.id)}" class="pt ${run.pareto[c.id] ? "on" : "dom"} ${sel ? "sel" : ""}">
      <circle cx="${px(c.total[2])}" cy="${py(c.total[k])}" r="6"/>
      ${onFront.has(c.id) ? `<text x="${px(c.total[2]) + 9}" y="${py(c.total[k]) - 6}">${esc(c.id)}</text>` : ""}</g>`;
  }).join("");
  const yt = [0, ymax].map((v) => `<text class="tk" x="${L - 6}" y="${py(v) + 4}" text-anchor="end">${v}</text>`).join("");
  const xt = [x0, x1].map((v) => `<text class="tk" x="${px(v)}" y="${H - 12}" text-anchor="middle">${(v / 1000).toFixed(1)}k</text>`).join("");
  return `<svg class="scatter" viewBox="0 0 ${W} ${H}" width="100%">
    <line class="axis" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/><line class="axis" x1="${L}" x2="${L}" y1="${T}" y2="${H - B}"/>
    ${yt}${xt}<text class="tk" x="${W - R}" y="${H - 1}" text-anchor="end">cost, linear ft</text>
    <text class="tk" x="4" y="${T - 2}">${k ? "soft" : "hard"}</text>
    <path class="front" d="${line}"/>${pts}</svg>
    <p class="hint">Lower left is better. The dashed line joins the grammars no other shown beats on both totals; the vertical
    scale is a square root so small counts stay readable.
    ${off.length ? `Close up: ${off.map((c) => `${esc(c.id)} (${headline(c.total)}, ${(c.total[2] / 1000).toFixed(1)}k ft)`).join(", ")} ${off.length === 1 ? "is" : "are"} off the chart.
      <a href="#" data-zoom="all">Show all</a>` : rs.zoom === "all" && near.length < all.length ? `<a href="#" data-zoom="close">Close up</a>` : ""}</p>`;
}

function pfHighlight(id) {
  const pf = $("#pf");
  if (!pf) return;
  pf.classList.toggle("hovering", !!id);
  pf.querySelectorAll("[data-cand]").forEach((el) => el.classList.toggle("hl", el.dataset.cand === id));
}

$("#runsMain").addEventListener("pointerover", (e) => {
  const el = e.target.closest("#pf [data-cand]");
  pfHighlight(el?.dataset.cand);
  if (el && !e.target.closest("td[data-tip]")) {
    const c = rs.run.candidates.find((x) => x.id === el.dataset.cand);
    const wins = rs.run.pareto[c.id]?.length || 0;
    const target = el.querySelector("circle") || el.querySelector("th") || el;
    showTip(`<b>${esc(c.id)}</b>${c.parent ? ` from ${esc(c.parent)}` : ""}: ${fmtScore(c.total)}<br>${wins ? `best on ${wins} of ${rs.run.houses.length} houses` : "dominated: not best on any house"}
      ${c.note ? `<br><span class="tipnote">${esc(c.note.slice(0, 220))}${c.note.length > 220 ? "..." : ""}</span>` : ""}`, target.getBoundingClientRect(), "above");
  }
});
$("#runsMain").addEventListener("pointerleave", () => pfHighlight(null));

function iterList(run) {
  if (!run.iterations.length) return `<p class="empty">No iterations yet. ${runningSearch(run.name) ? "The first one is running." : "Continue the run to start the search."}</p>`;
  return `<div class="iters">${[...run.iterations].reverse().map((it) => {
    const sel = rs.sel?.kind === "iter" && rs.sel.n === it.iteration;
    const verdict = it.accepted ? `<span class="good">kept as <b>${esc(it.child)}</b></span>`
      : `<span class="no">not kept:</span> ${esc(it.error || "not better than its parent on these houses")}`;
    const cmp = it.child_batch ? `${fmtScore(it.parent_batch)} &#x2192; ${fmtScore(it.child_batch)}
        <span class="${it.child_batch[2] < it.parent_batch[2] ? "good" : "bad"}">(${it.child_batch[2] - it.parent_batch[2] > 0 ? "+" : ""}${num(it.child_batch[2] - it.parent_batch[2])} ft)</span>`
      : it.parent_batch ? `parent: ${fmtScore(it.parent_batch)}` : "";
    return `<div class="it ${it.accepted ? "kept" : ""} ${sel ? "sel" : ""}" data-it="${it.iteration}">
      <div class="ihead"><b>#${it.iteration}</b> ${verdict}<span class="muted">${it.seconds != null ? `${it.seconds} s` : ""}</span></div>
      <div class="muted">parent ${esc(it.parent)} on ${it.batch.map(esc).join(", ")}</div>
      <div class="cmp">${cmp}</div>
      ${it.note ? `<div class="note">${esc(it.note)}</div>` : ""}
    </div>`;
  }).join("")}</div>`;
}

// ---- detail: a candidate, an iteration's proposal, a job, or the new-run form

async function runGrammar(cid) {
  const k = `${rs.name}/${cid}`;
  if (!rs.src[k]) rs.src[k] = api("GET", `/api/run/${rs.name}/grammar/${cid}`).then((g) => g.source);
  try { return await rs.src[k]; } catch (e) { delete rs.src[k]; throw e; }
}

function diffLines(a, b) {
  const A = a.split("\n"), B = b.split("\n");
  let p = 0;
  while (p < A.length && p < B.length && A[p] === B[p]) p++;
  let s = 0;
  while (s < A.length - p && s < B.length - p && A[A.length - 1 - s] === B[B.length - 1 - s]) s++;
  const a2 = A.slice(p, A.length - s), b2 = B.slice(p, B.length - s);
  const n = a2.length, m = b2.length;
  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a2[i] === b2[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const ops = A.slice(0, p).map((t) => [" ", t]);
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a2[i] === b2[j]) { ops.push([" ", a2[i]]); i++; j++; }
    else if (i < n && (j >= m || dp[i + 1][j] >= dp[i][j + 1])) ops.push(["-", a2[i++]]);
    else ops.push(["+", b2[j++]]);
  }
  return ops.concat(A.slice(A.length - s).map((t) => [" ", t]));
}

function diffHtml(a, b, ctx = 3) {
  const ops = diffLines(a, b);
  const add = ops.filter((o) => o[0] === "+").length, del = ops.filter((o) => o[0] === "-").length;
  if (!add && !del) return { html: `<p class="empty">No changes.</p>`, add, del };
  const keep = ops.map(() => false);
  ops.forEach((o, i) => { if (o[0] !== " ") for (let k = Math.max(0, i - ctx); k <= Math.min(ops.length - 1, i + ctx); k++) keep[k] = true; });
  let out = "", skip = 0;
  ops.forEach((o, i) => {
    if (!keep[i]) { skip++; return; }
    if (skip) { out += `<div class="skip">${skip} unchanged line${skip === 1 ? "" : "s"}</div>`; skip = 0; }
    out += `<div class="${o[0] === "+" ? "add" : o[0] === "-" ? "del" : ""}"><i>${o[0]}</i>${esc(o[1]) || " "}</div>`;
  });
  if (skip) out += `<div class="skip">${skip} unchanged line${skip === 1 ? "" : "s"}</div>`;
  return { html: `<div class="diff">${out}</div>`, add, del };
}

function lineage(cid) {
  const by = Object.fromEntries(rs.run.candidates.map((c) => [c.id, c]));
  const chain = [];
  for (let c = by[cid]; c; c = by[c.parent]) { chain.unshift(c.id); if (chain.length > 200) break; }
  return chain;
}

const candChip = (id) => `<span class="chip" data-cand="${esc(id)}">${esc(id)}</span>`;
const openHint = () => `builds it on ${esc($("#house").value)} as unsaved edits; grammars/${esc($("#grammar").value)}.py is not changed`;

async function renderRunsDetail(refresh = false) {
  const el = $("#runsDetail");
  const sel = rs.sel;
  if (!sel) {
    el.innerHTML = `<p class="empty">Click a grammar (a row of the table) or an iteration to see it here: its note,
      its changes against its parent, the proposer's pictures and steps. Open in workbench builds it so you can step through
      it and read its faults.</p>`;
    return;
  }
  if (sel.kind === "new") return renderNewRun(el);
  if (sel.kind === "job") return renderJob(el, sel.id, refresh);
  const run = rs.run;
  if (!run) { el.innerHTML = ""; return; }
  if (sel.kind === "cand") {
    const c = run.candidates.find((x) => x.id === sel.id);
    if (!c) { el.innerHTML = `<p class="empty">No grammar ${esc(sel.id)} in this run.</p>`; return; }
    const wins = run.pareto[c.id] || [];
    const parent = run.candidates.find((x) => x.id === c.parent);
    el.innerHTML = `<div class="dhead"><h2>${esc(c.id)}</h2>${wins.length ? `<span class="pbadge">Pareto set: best on ${wins.length} of ${run.houses.length} houses</span>` : `<span class="muted">dominated: not best on any house</span>`}</div>
      ${c.note ? `<p class="note">${esc(c.note)}</p>` : ""}
      <table class="kv">
        <tr><td>made in</td><td>${c.iteration ? `iteration <a href="#" data-it="${c.iteration}">${c.iteration}</a>` : "the start: the seed grammar"}</td></tr>
        <tr><td>lineage</td><td>${lineage(c.id).map(candChip).join(" &#x2192; ")}</td></tr>
        <tr><td>total</td><td>${fmtScore(c.total)}</td></tr>
        ${parent ? `<tr><td>vs ${esc(parent.id)}</td><td>${c.total[1] - parent.total[1]} soft, ${num(c.total[2] - parent.total[2])} ft cost</td></tr>` : ""}
        ${wins.length ? `<tr><td>best on</td><td>${wins.map(esc).join(", ")}</td></tr>` : ""}
      </table>
      <div class="actions"><button class="primary" data-open="${esc(c.id)}">Open in workbench</button><span class="muted">builds it on ${esc($("#house").value)}; it is in the grammar menu as ${esc(rs.name)}.${esc(c.id)}</span></div>
      <div id="cdiff"><p class="empty">Loading the grammar...</p></div>`;
    try {
      const src = await runGrammar(c.id);
      const psrc = c.parent ? await runGrammar(c.parent) : null;
      if (rs.sel !== sel) return;
      const d = psrc != null ? diffHtml(psrc, src) : null;
      $("#cdiff").innerHTML = (d ? `<h4>Changes from ${esc(c.parent)} <small><span class="good">+${d.add}</span> <span class="bad">-${d.del}</span> lines</small></h4>${d.html}` : "")
        + `<details ${d ? "" : "open"}><summary>Whole grammar, ${src.split("\n").length} lines</summary><pre class="code">${esc(src)}</pre></details>`;
    } catch (e) { $("#cdiff").innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
    return;
  }
  if (sel.kind === "iter") {
    const it = run.iterations.find((x) => x.iteration === sel.n);
    if (!it) { el.innerHTML = ""; return; }
    const verdict = it.accepted ? `<span class="good">kept as ${candChip(it.child)}</span>`
      : `<span class="no">not kept:</span> ${esc(it.error || "not better than its parent on these houses")}`;
    el.innerHTML = `<div class="dhead"><h2>Iteration ${it.iteration}</h2></div>
      <p>${verdict}</p>
      <table class="kv">
        <tr><td>parent</td><td>${candChip(it.parent)}</td></tr>
        <tr><td>houses</td><td>${it.batch.map(esc).join(", ")}</td></tr>
        <tr><td>parent score</td><td>${it.parent_batch ? fmtScore(it.parent_batch) : "-"}</td></tr>
        <tr><td>its score</td><td>${it.child_batch ? fmtScore(it.child_batch) : "not scored"}</td></tr>
        ${it.seconds != null ? `<tr><td>time</td><td>${it.seconds} s</td></tr>` : ""}
        ${it.usage?.turns ? `<tr><td>Claude</td><td>${it.usage.turns} turns, ${it.usage.input_tokens} tokens in, ${it.usage.output_tokens} out${it.usage.checks != null ? `, ${it.usage.checks} checks` : ""}</td></tr>` : ""}
      </table>
      <h4>The proposer's note</h4><p class="note">${esc(it.note || "No note.")}</p>
      <div id="prop"><p class="empty">Loading the proposal folder...</p></div>`;
    let p;
    try { p = await api("GET", `/api/run/${rs.name}/proposal/${it.iteration}`); } catch (e) {
      $("#prop").innerHTML = `<p class="empty">No proposal folder for this iteration (${esc(e.message)}).</p>`;
      return;
    }
    if (rs.sel !== sel) return;
    const base = `/api/run/${encodeURIComponent(rs.name)}/proposal/${it.iteration}`;
    const t = p.transcript;
    let html = `<h4>What the proposer saw <small>the parent's elevations, hard faults marked; click to enlarge</small></h4>`
      + (p.images.length ? `<div class="thumbs">${p.images.map((f) => `<a href="${base}/${f}" target="_blank" title="open full size"><img src="${base}/${f}" alt="${esc(f)}"><span>${esc(f.replace(".png", ""))}</span></a>`).join("")}</div>`
        : `<p class="empty">No pictures in this folder.</p>`)
      + `<h4>What it did</h4>` + (t ? (t.calls.length ? `<ol class="calls">${t.calls.map((c) => `<li><b>${esc(c.name)}</b> <code>${esc(c.input)}</code></li>`).join("")}</ol>` : `<p class="empty">No tool calls.</p>`)
        + (t.note ? `<p class="note">Final: ${esc(t.note)}</p>` : "") + (t.usage ? `<p class="muted">${t.turns} turns, ${t.usage.input_tokens} tokens in, ${t.usage.output_tokens} out.</p>` : "")
        : `<p class="empty">No transcript: ${run.config.model === "scripted" ? "this run used the scripted proposer, which only changes the stud spacing." : "transcript.json is missing."}</p>`)
      + (p.prompt ? `<details><summary>The prompt it was given</summary><pre class="code wrap">${esc(p.prompt)}</pre></details>` : `<p class="empty">No prompt.md saved${run.config.model === "scripted" ? " (the scripted proposer has none)" : ""}.</p>`);
    if (p.proposed != null) {
      html += `<div class="actions"><button class="primary" data-openprop="${it.iteration}">Open proposal in workbench</button><span class="muted">${openHint()}</span></div><div id="pdiff"></div>`;
    } else html += `<p class="empty">No proposed grammar saved.</p>`;
    $("#prop").innerHTML = html;
    if (p.proposed != null) {
      rs.proposed = { n: it.iteration, source: p.proposed };
      try {
        const psrc = await runGrammar(it.parent);
        const d = diffHtml(psrc, p.proposed);
        if (rs.sel === sel) $("#pdiff").innerHTML = `<h4>Proposed grammar: changes from ${esc(it.parent)} <small><span class="good">+${d.add}</span> <span class="bad">-${d.del}</span> lines</small></h4>${d.html}`;
      } catch (e) { $("#pdiff").innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
    }
  }
}

async function renderJob(el, id, refresh) {
  let j;
  try { j = await api("GET", `/api/job/${id}`); } catch (e) { el.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
  if (rs.sel?.kind !== "job" || rs.sel.id !== id) return;
  const log = el.querySelector("pre.log");
  const atEnd = !log || log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
  if (refresh && log) {
    log.textContent = plain(j.log);
    el.querySelector(".jst").className = `jst ${j.status}`;
    el.querySelector(".jst").textContent = j.status;
    if (j.status !== "running") el.querySelectorAll("[data-jact]").forEach((b) => b.remove());
  } else {
    const verdict = j.kind === "tests" && j.status !== "running" ? (j.status === "done" ? `<p class="good">The tests passed.</p>` : `<p class="bad">The tests did not pass; the log says why.</p>`) : "";
    el.innerHTML = `<div class="dhead"><h2>${esc(j.title)}</h2><span class="jst ${j.status}">${j.status}</span></div>
      ${verdict}
      <table class="kv"><tr><td>started</td><td>${new Date(j.started * 1000).toLocaleString()}</td></tr>
      ${j.ended ? `<tr><td>ended</td><td>${new Date(j.ended * 1000).toLocaleString()} (exit ${j.returncode})</td></tr>` : ""}
      <tr><td>command</td><td><code>${esc(j.argv.join(" "))}</code></td></tr></table>
      ${j.status === "running" ? `<div class="actions">${j.kind === "evolve" ? `<button data-jact="stop">Stop after this iteration</button>` : ""}<button data-jact="kill" class="danger">${j.kind === "evolve" ? "Kill now" : "Stop"}</button></div>` : ""}
      <h4>Log <small>last lines</small></h4><pre class="code log">${esc(plain(j.log) || "(empty so far)")}</pre>`;
  }
  const pre = el.querySelector("pre.log");
  if (atEnd) pre.scrollTop = pre.scrollHeight;
}

function renderNewRun(el) {
  const f = rs.form || { name: `run-${new Date().toISOString().slice(5, 10)}`, seed: "seed", iterations: 5, minibatch: 3,
    model: "claude-opus-5-5", effort: "medium", checks: 3, images: true, dry: !rs.creds?.ok };
  rs.form = f;
  el.innerHTML = `<div class="dhead"><h2>New run</h2></div>
    <p class="muted">A run starts from a seed grammar and evolves it on the training houses h000 to h009. Each iteration
    Claude proposes one edit to a grammar from the Pareto set; it is kept only if it beats its parent on a few houses.</p>
    <form id="nrForm" class="form">
      <label>Name <input name="name" value="${esc(f.name)}" pattern="[A-Za-z0-9_\\-]+" required><small>letters, digits, - and _; it becomes runs/&lt;name&gt;</small></label>
      <label>Seed grammar <select name="seed">${grammarList.map((g) => `<option ${g === f.seed ? "selected" : ""}>${esc(g)}</option>`).join("")}</select><small>from grammars/</small></label>
      <div class="two"><label>Iterations <input name="iterations" type="number" min="1" max="500" value="${f.iterations}"></label>
      <label>Houses per iteration <input name="minibatch" type="number" min="1" max="10" value="${f.minibatch}"></label></div>
      <label class="chk"><input type="checkbox" name="dry" ${f.dry ? "checked" : ""}> Dry run (no Claude) <small>a scripted proposer that only changes the stud spacing, to try the search</small></label>
      <fieldset ${f.dry ? "disabled" : ""}>
        <div class="two"><label>Claude model <input name="model" value="${esc(f.model)}"></label>
        <label>Effort <select name="effort">${["low", "medium", "high", "xhigh", "max"].map((x) => `<option ${x === f.effort ? "selected" : ""}>${x}</option>`).join("")}</select></label></div>
        <div class="two"><label>Checks per proposal <input name="checks" type="number" min="0" max="20" value="${f.checks}"><small>draft builds it may test</small></label>
        <label class="chk"><input type="checkbox" name="images" ${f.images ? "checked" : ""}> Show it the elevations</label></div>
      </fieldset>
      <div class="actions"><button class="primary" type="submit">Start</button><span class="cred">${credLine()}</span></div>
      <p id="nrErr" class="bad"></p>
    </form>`;
  const form = $("#nrForm");
  const read = () => {
    const d = new FormData(form);
    Object.assign(f, { name: d.get("name"), seed: d.get("seed"), iterations: +d.get("iterations"), minibatch: +d.get("minibatch"),
      dry: !!d.get("dry"), model: d.get("model") ?? f.model, effort: d.get("effort") ?? f.effort, checks: d.get("checks") != null ? +d.get("checks") : f.checks,
      images: form.elements.images.checked });
  };
  form.addEventListener("change", (e) => { read(); if (e.target.name === "dry") form.querySelector("fieldset").disabled = f.dry; });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    read();
    if (!f.dry && !rs.creds?.ok) { $("#nrErr").textContent = "Claude is not reachable from here; tick Dry run, or set credentials and restart the workbench."; return; }
    if (rs.list.some((r) => r.name === f.name)) { $("#nrErr").textContent = `A run called ${f.name} exists; pick another name, or continue that run.`; return; }
    const settings = { run: f.name, iterations: f.iterations, minibatch: f.minibatch, seed_grammar: `grammars/${f.seed}.py`, dry: f.dry };
    if (!f.dry) Object.assign(settings, { model: f.model, effort: f.effort, checks: f.checks, no_images: !f.images });
    const r = await startSearch(settings);
    if (r !== true) $("#nrErr").textContent = r;
    else rs.form = null;
  });
}

$("#runsDetail").addEventListener("click", async (e) => {
  const cand = e.target.closest("[data-cand]");
  if (cand && !e.target.closest("button")) { rs.sel = { kind: "cand", id: cand.dataset.cand }; rs.mainKey = ""; renderRunsMain(); return renderRunsDetail(); }
  const itl = e.target.closest("a[data-it]");
  if (itl) { e.preventDefault(); rs.sel = { kind: "iter", n: +itl.dataset.it }; rs.mainKey = ""; renderRunsMain(); return renderRunsDetail(); }
  const open = e.target.closest("button[data-open]");
  if (open) return openCandidate(open.dataset.open);
  const op = e.target.closest("button[data-openprop]");
  if (op && rs.proposed?.n === +op.dataset.openprop) return openInWorkbench(rs.proposed.source, `run ${rs.name}, proposal of iteration ${op.dataset.openprop}`);
  const ja = e.target.closest("button[data-jact]");
  if (ja && rs.sel?.kind === "job") {
    try { await api("POST", `/api/job/${rs.sel.id}/${ja.dataset.jact}`); await tick(); renderRunsDetail(); } catch (err) { status(err.message, true); }
  }
});

async function openCandidate(cid, house) {
  // a kept grammar is in the grammar menu as run.cid: open it there, on `house` if given
  const g = `${rs.name}.${cid}`;
  if (!grammarList.includes(g)) await loadLists($("#house").value);
  if (!grammarList.includes(g)) return openInWorkbench(await runGrammar(cid), `run ${rs.name}, ${cid}`);
  setFollow(false);
  if (house) { $("#house").value = house; remember("house", house); }
  $("#grammar").value = g;
  remember("grammar", g);
  st.hidden.clear();
  st.sel = null;
  await loadGrammar();
  showTab("view3d");
  showTab("faults");
  if (await build()) status(`run ${rs.name}, ${cid}, on ${$("#house").value}`);
}

async function openInWorkbench(source, label) {
  setFollow(false);
  $("#src").value = source;
  st.origin = label;
  editState();
  showTab("view3d");
  showTab("faults");
  if (await build()) status(`${label}, built on ${$("#house").value} from unsaved edits. Revert in the Grammar tab goes back.`);
}

// ---------------------------------------------------------------- Live: a running search, as it happens

const lv = {
  run: null, follow: false, data: null, proposal: "", count: 0, t0: 0, draft: null, parent: null, parentSrc: "",
  houseFor: null, runData: null, runKey: "", news: "",
};

function startLive(name, follow) {
  if (lv.run !== name) {
    Object.assign(lv, { run: name, data: null, proposal: "", count: 0, draft: null, parent: null, parentSrc: "",
      houseFor: null, runData: null, runKey: "", news: "" });
    $("#lvFeed").innerHTML = "";
  }
  if (follow) setFollow(true);
  liveTick();
}

function setFollow(on) {
  if (lv.follow === on) return;
  lv.follow = on;
  document.querySelectorAll(".lvFollow").forEach((b) => { b.checked = on; });
  if (on && lv.draft != null) followDraft();
}

const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const span = (s) => (s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);
const ft = (x) => `${Math.round(x).toLocaleString()} ft`;

let liveBusy = false;
async function liveTick() {
  if (!lv.run || liveBusy) return;
  liveBusy = true;
  try {
    const d = await api("GET", `/api/run/${encodeURIComponent(lv.run)}/live?proposal=${lv.proposal}&after=${lv.count}`);
    const name = d.live?.proposal || "";
    if (name && name !== lv.proposal) {   // a new iteration: the server sent all of its actions
      lv.proposal = name;
      $("#lvFeed").innerHTML = "";
      lv.t0 = d.live?.started || d.events[0]?.time || Date.now() / 1000;   // times count from the iteration's start
    }
    lv.data = d;
    if (name === lv.proposal) {   // once stopped there is no proposal: keep the last iteration's feed
      lv.count = d.count;
      appendFeed(d.events);
    }
    if (d.live?.parent && d.live.parent !== lv.parent) {
      lv.parent = d.live.parent;
      lv.parentSrc = await api("GET", `/api/run/${lv.run}/grammar/${lv.parent}`).then((g) => g.source).catch(() => "");
    }
    const key = JSON.stringify([d.job?.done, d.live?.stage, d.live?.iteration]);
    if (key !== lv.runKey) {   // an iteration ended or a stage changed: the chart and the news
      lv.runKey = key;
      lv.runData = await api("GET", `/api/run/${lv.run}`).catch(() => lv.runData);
      const r = lv.runData;
      const best = r?.candidates.reduce((a, c) => (!a || lt(c.total, a.total) < 0 ? c : a), null);
      $("#lvChart").innerHTML = best ? `<div class="muted">Best so far: <b>${esc(best.id)}</b>, ${fmtScore(best.total)} over
        ${r.houses.length} houses. ${r.candidates.length - 1} of ${r.iterations.length} edits kept; the Runs view has the chart.</div>` : "";
      renderNews();
    }
    if (d.draft != null && d.draft !== lv.draft) {
      lv.draft = d.draft;
      renderDraftDiff();
      if (lv.follow) await followDraft();
    }
  } catch (e) {   // the next tick tries again, unless the run is gone
    if (/not found|no such run/i.test(e.message)) Object.assign(lv, { run: null, follow: false });
  } finally { liveBusy = false; }
  renderLiveHead();
  renderRunLive();
}
setInterval(liveTick, 1500);

function liveState() {
  // a line or two saying where the search is
  const d = lv.data;
  if (!d) return { on: false, html: "" };
  const L = d.live, job = d.job;
  const on = d.active;
  if (L && (!on || L.stage === "stopped")) return { on, html: `<b>${esc(lv.run)}</b> has stopped, after ${lv.runData?.iterations.length ?? "its"} iterations.` };
  if (!L) {
    return { on, html: on ? `<b>${esc(lv.run)}</b>: ${job.done} of ${job.of} iterations done. This search started before the live view
      existed, so only finished iterations show.` : `<b>${esc(lv.run)}</b> is not running.` };
  }
  const of = job ? `, ${Math.min(job.done + 1, job.of)} of ${job.of} in this search` : "";
  return { on, html: `<b>${esc(lv.run)}</b>, iteration ${L.iteration}${of}: <span class="stage">${esc(L.stage)}</span>
    for ${span(Date.now() / 1000 - L.time)}
    ${L.parent ? `<div class="muted">parent ${esc(L.parent)} on ${(L.houses || []).map(esc).join(", ")}</div>` : ""}` };
}

function followLine() {
  return `<label class="chk follow" title="On: the 3D view, rules and stepping follow Claude's draft. Off: browse freely.">
    <input type="checkbox" class="lvFollow" ${lv.follow ? "checked" : ""}> Follow live</label>
    <span class="muted">${lv.follow ? (lv.draft != null ? `the 3D view shows the draft on ${esc($("#house").value)}` : "waiting for a draft") : "the 3D view is yours"}</span>`;
}

function renderLiveHead() {
  $("#liveDot").textContent = lv.data?.active ? "●" : "";
  if (!lv.run) return;
  const s = liveState();
  $("#lvHead").innerHTML = `<div class="lv-status">${s.on ? `<span class="livedot"></span>` : ""}<div>${s.html}</div></div>
    <div class="lv-follow">${followLine()}</div>`;
  $("#lvFeedTitle").hidden = !lv.proposal;
}

function renderNews() {
  // say clearly when a child is kept
  const L = lv.data?.live;
  const last = lv.runData?.iterations.at(-1);
  let html = "";
  if (L?.stage === "scoring on every house") html = `<div class="news good">${esc(L.child)} beat ${esc(L.parent)}: scoring it on every house...</div>`;
  else if (L?.accepted) html = `<div class="news good"><b>Kept as ${esc(L.child)}</b>: iteration ${L.iteration} beat ${esc(L.parent)} on ${(L.houses || []).map(esc).join(", ")}.</div>`;
  else if (L?.stage === "between iterations" && last?.iteration === L.iteration) {
    html = `<div class="news">Iteration ${L.iteration} not kept: ${esc(last.error || "not better than its parent on these houses")}.</div>`;
  }
  if (html !== lv.news) {
    if (L?.accepted && !lv.news.includes(`Kept as ${L.child}`)) status(`run ${lv.run}: kept ${L.child}`);
    lv.news = html;
    $("#lvNews").innerHTML = html;
  }
}

function renderRunLive() {
  // the live box at the top of the Runs view
  const el = document.getElementById("runLive");
  if (!el || !lv.data) return;
  const s = liveState();
  const lastSay = [...$("#lvFeed").querySelectorAll(".fi")].at(-1)?.textContent || "";
  el.innerHTML = `<div class="runlive"><div>${s.html}</div>${lv.news}
    ${lastSay ? `<div class="lastfeed" title="the proposer's latest action">${esc(lastSay)}</div>` : ""}
    <div class="row">${followLine()}<button data-act="watch" class="primary">Watch in 3D</button></div></div>`;
}

document.addEventListener("change", (e) => { if (e.target.classList.contains("lvFollow")) setFollow(e.target.checked); });
$("#runsMain").addEventListener("click", (e) => {
  if (e.target.closest("button[data-act=watch]")) { setFollow(true); showTab("view3d"); showTab("live"); }
});

async function followDraft() {
  // the draft as unsaved edits to its parent grammar, built on a house of this iteration's minibatch
  const L = lv.data?.live;
  if (!L || lv.draft == null) return;
  const gname = `${lv.run}.${L.parent}`;
  if (!grammarList.includes(gname)) await loadLists($("#house").value);
  if (grammarList.includes(gname) && $("#grammar").value !== gname) {
    $("#grammar").value = gname;
    st.saved = lv.parentSrc;
    st.hidden.clear();
  }
  if (lv.houseFor !== L.iteration) {
    lv.houseFor = L.iteration;
    if (L.houses?.length && !L.houses.includes($("#house").value)) $("#house").value = L.houses[0];
  }
  $("#src").value = lv.draft;
  st.origin = `Live draft: run ${lv.run}, iteration ${L.iteration}`;
  editState();
  await build(true);
}

function renderDraftDiff() {
  const box = $("#lvDiff");
  box.hidden = lv.draft == null;
  if (lv.draft == null) return;
  const d = diffHtml(lv.parentSrc, lv.draft);
  box.querySelector("summary").innerHTML = `Draft against ${esc(lv.parent)}: <span class="good">+${d.add}</span> <span class="bad">-${d.del}</span> lines`;
  box.querySelector("div").innerHTML = d.html;
}

function enclosing(src, snippet) {
  // the function a piece of text sits in: a name, "" at the top of the file, null when not found
  const first = String(snippet || "").split("\n").map((l) => l.trim()).find((l) => l && l !== "...");
  if (!first || !src) return null;
  const lines = src.split("\n");
  let i = lines.findIndex((l) => l.includes(first));
  if (i < 0) return null;
  if (lines[i].startsWith("@")) while (i < lines.length - 1 && !lines[i].startsWith("def ")) i++;
  for (; i >= 0; i--) {
    const m = lines[i].match(/^def (\w+)/);
    if (m) return m[1];
    if (lines[i] && !/^[\s@#]/.test(lines[i])) return "";
  }
  return "";
}

function editWords(input) {
  const defs = (t) => new Set([...String(t || "").matchAll(/def (\w+)\(/g)].map((m) => m[1]));
  const added = [...defs(input.new)].filter((n) => !defs(input.old).has(n));
  if (added.length) return `added ${added.join(", ")}`;
  const name = enclosing(lv.draft, input.new) ?? enclosing(lv.parentSrc, input.old);
  return name ? `edited ${name}` : name === "" ? "edited the settings at the top" : "edited the grammar";
}

function feedHtml(e) {
  const t = `<i>${clock(Math.max(0, e.time - lv.t0))}</i>`;
  const line = (text, cls = "") => `<div class="fi ${cls}">${t}${text}</div>`;
  const inp = e.input || {};
  if (e.kind === "start") return line(`Claude starts: ${esc(e.model)}, ${esc(e.effort)} effort, via ${esc(e.via)}`, "muted");
  if (e.kind === "say") return `<div class="fi say">${t}<span>${esc(e.text)}</span></div>`;
  if (e.kind === "tool") {
    if (e.tool === "view_grammar") {
      const a = +inp.start || 1, b = +inp.end || 0;
      return line(a <= 1 && !b ? "read the whole grammar" : `read lines ${a}-${b || "end"}`);
    }
    if (e.tool === "edit_grammar") return line(esc(editWords(inp)), "edit");
    if (e.tool === "write_grammar") return line("rewrote the whole grammar", "edit");
    if (e.tool === "check_grammar") return line(`checking the draft on ${(lv.data?.live?.houses || []).map(esc).join(", ") || "this round's houses"}...`);
    return line(`${esc(e.tool)}`);
  }
  if (e.kind === "result") {
    const text = String(e.text || "");
    if (e.tool === "edit_grammar" && text.startsWith("Not changed")) return line(`edit not applied: ${esc(text.replace(/^Not changed: /, ""))}`, "bad");
    if (e.tool === "check_grammar") {
      const m = text.match(/Total over these houses: (\d+) hard, (\d+) soft, cost ([\d.]+) \(parent: \[([^\]]*)\]\)/);
      const head = m ? (() => {
        const p = m[4].split(",").map(Number);
        return `checked: <b>${m[1]} hard, ${m[2]} soft, cost ${ft(+m[3])}</b> <span class="muted">(parent ${p[0]} hard, ${p[1]} soft, ${ft(p[2])})</span>`;
      })() : esc(text.split("\n")[0]);
      return `<div class="fi check">${t}<span>${head}<details><summary>reports</summary><pre class="code wrap">${esc(text)}</pre></details></span></div>`;
    }
  }
  return "";   // view results, write confirmations and draft notices say nothing new
}

function appendFeed(events) {
  if (!events.length) return;
  const feed = $("#lvFeed");
  const atEnd = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 30;
  feed.insertAdjacentHTML("beforeend", events.map(feedHtml).join(""));
  if (atEnd) feed.scrollTop = feed.scrollHeight;
}

// ---------------------------------------------------------------- tabs, header, keys

function showTab(id) {
  const pane = document.getElementById(id);
  const host = pane.closest("#center, #right");
  host.querySelectorAll("nav.tabs button[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === id));
  host.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p === pane));
  remember("tab." + host.id, id);
  if (host.id === "center") {
    document.body.classList.toggle("runs-mode", id === "runs");
    hideTip();
    renderCaption();
    if (id === "runs") enterRuns();
    if (id === "view3d") requestAnimationFrame(resize);
    if (id === "elev") {
      const cur = current();
      if (cur) document.getElementById(`wall-${cur.wall}`)?.scrollIntoView({ block: "nearest" });
    }
  }
}

document.querySelectorAll("nav.tabs").forEach((nav) => nav.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (b) showTab(b.dataset.tab);
}));

$("#showFaults").addEventListener("change", () => { look3d(); renderElev(); });
$("#showSurfaces").addEventListener("change", () => { remember("surfaces", $("#showSurfaces").checked ? "1" : "0"); look3d(); renderElev(); });
$("#rebuild").addEventListener("click", regenerate);

// Regenerate (and New house): frame the house from scratch and draw each piece the moment the server places it, at the
// build's own speed; the full frame and its verification follow when the build is done
async function regenerate() {
  stopPlay();
  status("framing...");
  const body = { house: $("#house").value, grammar: $("#grammar").value };
  if (dirty()) body.source = $("#src").value;
  const t0 = performance.now();
  const res = await fetch("/api/build_live", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok || !res.body) { status((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`, true); return; }
  clear(group);
  meshes.clear();
  gapGroup.visible = markGroup.visible = false;
  const colors = { ...st.colors }, mat = new THREE.LineBasicMaterial({ color: 0x1d1d1b, transparent: true, opacity: 0.35 });
  const colorOf = (r) => colors[r] || (colors[r] = PALETTE[Object.keys(colors).length % PALETTE.length]);
  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = "", pieces = 0, frame = null, built = 0;
  const drop = (id) => {
    const x = meshes.get(id);
    if (!x) return;
    group.remove(x);
    x.traverse((c) => c.geometry?.dispose());
    meshes.delete(id);
  };
  const put = (m) => {   // a new member, or a new shape for one a later rule cut or notched
    drop(m.id);
    const mesh = memberMesh(m, new THREE.MeshStandardMaterial({ roughness: 0.85, color: colorOf(m.rule) }), mat);
    group.add(mesh);
    meshes.set(m.id, mesh);
  };
  const handle = (msg) => {
    if (msg.house) {   // the house comes first: show its surfaces, and frame a new one in the view
      const h = msg.house;
      renderSurfaces([...h.walls, ...h.floors, ...h.roofs]);
      if (st.fitFor !== h.house) { st.fitFor = h.house; fit(); }
    } else if (msg.step) {
      for (const m of msg.step.placed) put(m);
      for (const m of msg.step.shaped || []) put(m);
      for (const id of msg.step.removed) drop(id);
      pieces += msg.step.placed.length - msg.step.removed.length;
      status(`framing: ${Math.round(1000 * msg.step.t)} ms, ${pieces} pieces, ${msg.step.rule}`);
    } else if (msg.built != null) {
      built = msg.built;
      status(`framed in ${Math.round(1000 * built)} ms, ${pieces} pieces; verifying...`);
    } else if (msg.frame) frame = msg.frame;
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const l of lines) if (l.trim()) handle(JSON.parse(l));
  }
  if (!frame) { status(frame?.error || "the build stopped before it finished", true); return; }
  if (frame.error) { status(frame.error, true); return; }
  st.data = frame;
  index();
  renderAll();
  const ms = (x) => `${Math.round(1000 * x)} ms`;
  status(`framed from scratch in ${ms(built)}, verified in ${ms(frame.timing.verify)}, ` +
         `${ms((performance.now() - t0) / 1000)} in all${dirty() ? ", from unsaved edits" : ""}`);
}
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
    await regenerate();
    await loadLists(id);
  } catch (e) { status(e.message, true); }
});
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); build(); }
  const typing = ["TEXTAREA", "INPUT", "SELECT"].includes(document.activeElement?.tagName);
  if (typing || runsMode()) return;
  if (e.key === "Escape") { if (measure.on) setMeasure(false); else if (st.fault != null) chooseFault(st.fault); else select(null); }
  if (e.key === "ArrowLeft") { e.preventDefault(); stopPlay(); goto(st.at - 1); }
  if (e.key === "ArrowRight") { e.preventDefault(); stopPlay(); goto(st.at + 1); }
});

// ---------------------------------------------------------------- start

(async function start() {
  if (recall("surfaces") === "0") $("#showSurfaces").checked = false;
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
