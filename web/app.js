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
const wallById = (id) => st.data.walls.find((w) => w.id === id);
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
  fill($("#grammar"), grammarList.map((g) => [g, g]), $("#grammar").value || recall("grammar") || "seed");
}

async function loadGrammar() {
  const g = await api("GET", `/api/grammar/${$("#grammar").value}`);
  st.saved = g.source;
  st.origin = null;
  $("#src").value = g.source;
  editState();
}

const dirty = () => $("#src").value !== st.saved;

async function build() {
  status("building...");
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
  renderAll();
  status(`built in ${Math.round(performance.now() - t0)} ms${dirty() ? ", from unsaved edits" : ""}`);
  return true;
}

function index() {
  const d = st.data;
  st.builds++;
  st.byId = Object.fromEntries(d.members.map((m) => [m.id, m]));
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
  renderInspect();
  renderFaults();
  renderReport();
  renderTimeline();
  renderCaption();
}

// selection changes repaint only what depends on it
function select(sel) {
  st.sel = sel;
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
  ul.innerHTML = rules.map((r) => {
    const isNow = cur?.rule === r.name;
    const cls = [st.sel?.kind === "rule" && st.sel.id === r.name ? "sel" : "", st.hidden.has(r.name) ? "off" : "",
      isNow ? "now" : "", !done && !fired.has(r.name) ? "notyet" : ""].join(" ");
    return `<li data-rule="${esc(r.name)}" class="${cls}" style="--c:${st.colors[r.name]}" title="${esc(oneLine(r.doc))}">
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

let renderer, labeler, scene, camera, controls, group, gapGroup, markGroup, surfGroup, targetGroup;
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
  scene.add(group, gapGroup, markGroup, surfGroup, targetGroup);

  new ResizeObserver(resize).observe(el);
  let down = null;
  renderer.domElement.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const r = renderer.domElement.getBoundingClientRect();
    const p = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(p, camera);
    const hit = ray.intersectObjects([...meshes.values()].filter((m) => m.visible), false)[0];
    select(hit ? { kind: "member", id: hit.object.userData.id } : null);
  });
  (function loop() {
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
    labeler.render(scene, camera);
  })();
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

function wallMatrix(w, out = 0) {
  // wall coordinates (u, v, w) in metres to world; `out` pushes the plane outward, in metres
  const dir = new THREE.Vector3(w.end[0] - w.start[0], w.end[1] - w.start[1], 0).normalize();
  const nrm = new THREE.Vector3(-dir.y, dir.x, 0);
  return new THREE.Matrix4().makeBasis(dir, new THREE.Vector3(0, 0, 1), nrm)
    .setPosition(w.start[0] * S - nrm.x * out, w.start[1] * S - nrm.y * out, (w.base || 0) * S);
}

function label(text, cls, pos) {
  const div = document.createElement("div");
  div.className = "lbl " + cls;
  div.innerHTML = text;
  const o = new CSS2DObject(div);
  o.position.copy(pos);
  surfGroup.add(o);
  return o;
}

function renderSurfaces() {
  clear(surfGroup);
  surfs = [];
  for (const w of st.data.walls) {
    const L = w.length * S, H = w.height * S;
    const M = wallMatrix(w, 0.004);
    const shape = new THREE.Shape([[0, 0], [L, 0], [L, H], [0, H]].map(([x, y]) => new THREE.Vector2(x, y)));
    const pts = [[0, 0, L, 0], [L, 0, L, H], [L, H, 0, H], [0, H, 0, 0]];
    for (const o of w.openings) {
      const [a, b, c, d] = [o.u0 * S, o.v0 * S, o.u1 * S, o.v1 * S];
      shape.holes.push(new THREE.Path([[a, b], [c, b], [c, d], [a, d]].map(([x, y]) => new THREE.Vector2(x, y))));
      pts.push([a, b, c, b], [c, b, c, d], [c, d, a, d], [a, d, a, b]);
    }
    const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape),
      new THREE.MeshBasicMaterial({ color: SURF, transparent: true, opacity: 0.3, side: THREE.DoubleSide, depthWrite: false }));
    mesh.applyMatrix4(M);
    mesh.renderOrder = -1;
    const lineGeo = new THREE.BufferGeometry().setFromPoints(pts.flatMap(([a, b, c, d]) => [new THREE.Vector3(a, b, 0), new THREE.Vector3(c, d, 0)]));
    const line = new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({ color: 0x4d6780, transparent: true, opacity: 0.8 }));
    line.applyMatrix4(M);
    surfGroup.add(mesh, line);
    const wl = label(`${esc(w.id)} <i>${w.role === "interior" ? "partition, " : ""}${ftin(w.length)}</i>`, "wall", new THREE.Vector3(L / 2, H + 0.25, 0).applyMatrix4(M));
    const ol = w.openings.map((o) => label(`${esc(o.kind)} ${ftin(o.u1 - o.u0)} x ${ftin(o.v1 - o.v0)}`, "op",
      new THREE.Vector3(((o.u0 + o.u1) / 2) * S, ((o.v0 + o.v1) / 2) * S, 0).applyMatrix4(M)));
    surfs.push({ wall: w.id, mesh, line, label: wl, opLabels: ol });
  }
}

function render3d() {
  clear(group);
  clear(gapGroup);
  clear(markGroup);
  meshes.clear();
  const edgeMat = new THREE.LineBasicMaterial({ color: 0x1d1d1b, transparent: true, opacity: 0.35 });
  for (const m of st.data.members) {
    const size = [0, 1, 2].map((k) => (m.hi[k] - m.lo[k]) * S);
    const geo = new THREE.BoxGeometry(...size);
    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ roughness: 0.85, transparent: true }));
    mesh.position.set(...[0, 1, 2].map((k) => ((m.lo[k] + m.hi[k]) / 2) * S));
    mesh.userData.id = m.id;
    mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), edgeMat));
    group.add(mesh);
    meshes.set(m.id, mesh);
  }
  for (const w of st.data.walls) {
    for (const g of w.gaps) {
      const p = g.world.map((c) => new THREE.Vector3(...c.map((x) => x * S)));
      const geo = new THREE.BufferGeometry().setFromPoints([p[0], p[1], p[2], p[0], p[2], p[3]]);
      gapGroup.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: FACE[g.face], transparent: true, opacity: 0.32,
        side: THREE.DoubleSide, depthWrite: false })));
    }
  }
  const hardMat = new THREE.MeshBasicMaterial({ color: 0xd8342c, depthTest: false, transparent: true });
  const softMat = new THREE.MeshBasicMaterial({ color: 0xe08a00, depthTest: false, transparent: true });
  const ball = new THREE.SphereGeometry(0.06, 16, 12);
  for (const f of st.data.faults) {
    if (!f.at || f.check === "backing") continue;
    const s = new THREE.Mesh(ball, f.hard ? hardMat : softMat);
    s.position.set(...f.at.map((x) => x * S));
    s.renderOrder = 10;
    markGroup.add(s);
  }
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
  // id -> relation to the selection: "self", "bears", "carries", "side", "rule"; null when nothing is selected
  const sel = st.sel;
  if (!sel) return null;
  const rel = new Map();
  if (sel.kind === "member") {
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
    mesh.visible = !st.hidden.has(m.rule) && (present(id) || gone);
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
  const show = $("#showFaults").checked && done;
  gapGroup.visible = show;
  markGroup.visible = show;
  // the house's surfaces: strong on the bare house, faint once framing exists
  const on = $("#showSurfaces").checked;
  for (const s of surfs) {
    const active = cur?.wall === s.wall || cur?.target?.other === s.wall;
    s.mesh.visible = s.line.visible = s.label.visible = on;
    s.mesh.material.opacity = st.at === 0 ? 0.32 : active ? 0.2 : done ? 0.06 : 0.1;
    s.line.material.opacity = st.at === 0 ? 0.9 : active ? 0.8 : done ? 0.3 : 0.45;
    s.label.element.classList.toggle("active", active);
    s.label.element.classList.toggle("faint", done && st.at > 0);
    for (const o of s.opLabels) {
      o.visible = on && (st.at === 0 || active || done);
      o.element.classList.toggle("faint", st.at > 0 && !active);
    }
  }
  renderTarget3d();
}

function depthOf(wall) {
  // how far a wall's framing reaches in from its surface: the commonest reach of its members
  const n = {};
  for (const m of st.data.members) if (m.surface === wall && m.local && present(m.id)) n[m.local[1][2]] = (n[m.local[1][2]] || 0) + 1;
  const best = Object.entries(n).sort((a, b) => b[1] - a[1])[0];
  return best ? +best[0] : 3.5;
}

function otherEnd(t) {
  // where the other wall of a corner or tee meets this one, in its own coordinates
  const o = wallById(t.other);
  return o && { wall: o.id, u: o.end_meets === t.wall ? o.length : 0, v0: 0, v1: o.height };
}

function renderTarget3d() {
  // what the current step's rule matched, on the wall's surface: strong at the trigger, an outline at the output
  clear(targetGroup);
  const s = current();
  const t = s?.target;
  if (!t || t.kind === "member") return;
  const c = st.colors[s.rule], trig = trigger();
  const mark = (wid, u0, u1, v0, v1, face) => {
    const w = wallById(wid);
    if (!w) return;
    const M = wallMatrix(w, face === "inner" ? -(depthOf(wid) + 0.3) * S : 0.008);
    if (u1 - u0 > 1e-6) {
      const pts = [[u0, v0], [u1, v0], [u1, v1], [u0, v1]].map(([u, v]) => new THREE.Vector3(u * S, v * S, 0));
      if (trig) {
        const plane = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(pts.map((p) => new THREE.Vector2(p.x, p.y)))),
          new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.45, side: THREE.DoubleSide, depthWrite: false }));
        plane.applyMatrix4(M);
        targetGroup.add(plane);
      }
      const loop = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color: c, transparent: true, opacity: trig ? 1 : 0.6, depthTest: false }));
      loop.applyMatrix4(M);
      loop.renderOrder = 5;
      targetGroup.add(loop);
      if (face === "inner") {
        const l = new CSS2DObject(Object.assign(document.createElement("div"), { className: "lbl target", textContent: "inside face" }));
        l.position.copy(new THREE.Vector3(((u0 + u1) / 2) * S, ((v0 + v1) / 2) * S, 0).applyMatrix4(M));
        targetGroup.add(l);
      }
    } else {
      const post = new THREE.Mesh(new THREE.BoxGeometry(2.5 * S, (v1 - v0) * S, 2.5 * S),
        new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: trig ? 0.9 : 0.4, depthTest: !trig }));
      post.position.set(u0 * S, ((v0 + v1) / 2) * S, -1.5 * S);
      post.applyMatrix4(M);
      post.renderOrder = 5;
      targetGroup.add(post);
    }
  };
  mark(t.wall, t.u0, t.u1, t.v0, t.v1, t.face);
  if (t.other) {
    const o = otherEnd(t);
    if (o) mark(o.wall, o.u, o.u, o.v0, o.v1);
  }
}

// ---------------------------------------------------------------- elevations

function renderElev() {
  const el = $("#elev");
  if (!st.data) return;
  if (!st.data.walls.length) {
    el.innerHTML = `<p class="empty">This house has no walls.</p>`;
    return;
  }
  const keep = el.scrollTop;
  const rel = related();
  const span = Math.max(...st.data.walls.map((w) => w.length));
  const k = span / 1000;   // drawing unit: sizes below scale with the drawing, whatever the model's units
  const pad = 20 * k;
  const done = finished();
  const cur = current();
  const showFaults = $("#showFaults").checked && done;
  const showSurf = $("#showSurfaces").checked;
  const surfOp = st.at === 0 ? 0.42 : done ? 0.12 : 0.2;
  el.innerHTML = st.data.walls.map((w) => {
    const L = w.length, H = w.height;
    const active = cur && (cur.wall === w.id || cur.target?.other === w.id);
    const own = st.data.members.filter((m) => m.surface === w.id && !st.hidden.has(m.rule) && (present(m.id) || goneNow(m.id)));
    const rects = own.map((m) => {
      const [lo, hi] = m.local;
      const r = rel?.get(m.id);
      const gone = goneNow(m.id);
      const isNow = placedNow(m.id);
      const hit = matchedMember(m.id);
      const cls = ["m", rel && !r ? "dim" : "", r === "self" ? "sel" : "", showFaults && st.faulty.has(m.id) ? "fault" : "",
        isNow || (hit && trigger()) ? "now" : "", gone ? "gone" : ""].join(" ");
      const fillc = r && REL[r] ? REL[r] : gone ? "none" : hit ? st.colors[cur.rule] : done || isNow || r === "rule" ? st.colors[m.rule] : PAST;
      return `<rect class="${cls}" data-id="${m.id}" x="${lo[0]}" y="${-hi[1]}" width="${hi[0] - lo[0]}" height="${hi[1] - lo[1]}" fill="${fillc}"><title>${m.id} ${esc(m.role || "")}, ${esc(m.rule)}, ${esc(m.section)}${gone ? ", removed at this step" : ""}</title></rect>`;
    }).join("");
    const nbs = w.neighbours.filter((b) => present(b.id)).map((b) =>
      `<rect class="nb" data-id="${b.id}" x="${b.lo[0]}" y="${-b.hi[1]}" width="${b.hi[0] - b.lo[0]}" height="${b.hi[1] - b.lo[1]}"><title>${b.id}, on another wall</title></rect>`).join("");
    const holes = w.openings.map((o) => `M${o.u0} ${-o.v1}h${o.u1 - o.u0}v${o.v1 - o.v0}h${o.u0 - o.u1}z`).join("");
    const surf = showSurf ? `<path class="surf" d="M0 ${-H}h${L}v${H}h${-L}z${holes}" fill="${SURF}" fill-opacity="${surfOp}" fill-rule="evenodd"/>` : "";
    const ops = w.openings.map((o) =>
      `<rect class="op" x="${o.u0}" y="${-o.v1}" width="${o.u1 - o.u0}" height="${o.v1 - o.v0}"/>` +
      `<text x="${(o.u0 + o.u1) / 2}" y="${-(o.v0 + o.v1) / 2}" text-anchor="middle" font-size="${17 * k}">${esc(o.id)} ${esc(o.kind)}</text>` +
      `<text x="${(o.u0 + o.u1) / 2}" y="${-(o.v0 + o.v1) / 2 + 20 * k}" text-anchor="middle" font-size="${15 * k}">${ftin(o.u1 - o.u0)} x ${ftin(o.v1 - o.v0)}</text>`).join("");
    const a = 7 * k;
    const marks = showFaults ? st.data.faults.filter((f) => f.wall === w.id && f.u != null && f.check !== "backing").map((f) =>
      `<g class="mark ${f.hard ? "" : "soft"}"><title>${esc(f.message)}</title>
        <line x1="${f.u - a}" y1="${-f.v - a}" x2="${f.u + a}" y2="${-f.v + a}"/><line x1="${f.u - a}" y1="${-f.v + a}" x2="${f.u + a}" y2="${-f.v - a}"/></g>`).join("") : "";
    const gaps = showFaults ? w.gaps.map((g) =>
      `<rect class="gap" x="${g.u0}" y="${-g.v1}" width="${g.u1 - g.u0}" height="${g.v1 - g.v0}" stroke="${FACE[g.face]}" fill="url(#hatch-${g.face}-${w.id})"><title>${FACE_NAME[g.face]}: ${g.kind} gap ${ftin(g.u1 - g.u0)} wide, the board has nothing behind it</title></rect>`).join("") : "";
    const tees = w.tees.map((t) => `<g class="tee"><title>${esc(t.wall)} meets this wall here</title>
      <line x1="${t.u}" x2="${t.u}" y1="0" y2="${-H}"/><text x="${t.u}" y="${-H - 5 * k}" text-anchor="middle" font-size="${16 * k}">${esc(t.wall)}</text></g>`).join("");
    const hatch = (face, angle) => `<pattern id="hatch-${face}-${w.id}" patternUnits="userSpaceOnUse" width="${8 * k}" height="${8 * k}" patternTransform="rotate(${angle})">
          <line x1="0" y1="0" x2="0" y2="${8 * k}" stroke="${FACE[face]}" stroke-width="${1.4 * k}"/></pattern>`;
    const tag = !active ? "" : `<span class="steptag">${pill(cur.rule, st.colors[cur.rule])} ${cur.wall !== w.id ? `matched ${esc(cur.match)} on ${esc(cur.wall)}, which meets this wall`
      : trigger() ? `matched ${esc(cur.match)}` : `placed ${cur.placed.length} here`} at step ${stepNo()}</span>`;
    return `<div class="wall ${active ? "active" : ""} ${cur && !active ? "rest" : ""}" id="wall-${w.id}">
      <div class="cap"><b>${w.id}</b> ${w.role === "interior" ? "partition, " : ""}${ftin(L)} long, ${ftin(H)} high,
        seen from ${w.role === "interior" ? "its face side" : "outside"}, its start on the left.
        Meets ${w.start_meets ?? "nothing"} at its start, ${w.end_meets ?? "nothing"} at its end. ${tag}</div>
      <svg viewBox="${-pad} ${-(H + pad)} ${span + 2 * pad} ${H + 2 * pad}">
        <defs>${hatch("outer", 45)}${hatch("inner", -45)}</defs>
        ${surf}<rect class="outline" x="0" y="${-H}" width="${L}" height="${H}"/>
        ${nbs}${rects}${tees}${ops}${gaps}${marks}${active ? targetSvg(w, k) : ""}
      </svg></div>`;
  }).join("") + `<div class="legend"><span style="--c:${SURF}">wall surface (the input)</span>
     <span style="--c:${PAST}">placed by earlier steps</span>
     <span style="--c:${REL.bears}">the selection bears on it</span>
     <span style="--c:${REL.carries}">it bears on the selection</span><span style="--c:${REL.side}">beside the selection</span>
     <span style="--c:#e4e2dd">member of another wall</span>
     <span style="--c:${FACE.outer}">no backing, outside face</span><span style="--c:${FACE.inner}">no backing, inside face</span></div>`;
  el.scrollTop = keep;
}

function targetSvg(w, k) {
  // what the current step's rule matched on this wall: filled at the trigger, outlined at the output
  const s = current(), t = s.target;
  if (!t || t.kind === "member") return "";
  const c = st.colors[s.rule], trig = trigger();
  const at = t.wall === w.id ? t : t.other === w.id ? { ...otherEnd(t), u0: otherEnd(t).u, u1: otherEnd(t).u } : null;
  if (!at) return "";
  const cls = `target ${trig ? "trig" : "out"}`;
  if (at.u1 - at.u0 < 1e-6) return `<line class="${cls}" x1="${at.u0}" x2="${at.u0}" y1="${-at.v0}" y2="${-at.v1}" stroke="${c}"/>`;
  const face = t.face === "inner" ? `<text x="${(at.u0 + at.u1) / 2}" y="${-at.v1 - 4 * k}" text-anchor="middle" font-size="${15 * k}">inside face</text>` : "";
  return `<rect class="${cls}" x="${at.u0}" y="${-at.v1}" width="${at.u1 - at.u0}" height="${at.v1 - at.v0}" stroke="${c}" fill="${c}"/>${face}`;
}

$("#elev").addEventListener("click", (e) => {
  const r = e.target.closest("rect[data-id]");
  select(r && st.byId[r.dataset.id] ? { kind: "member", id: r.dataset.id } : null);
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
    const ops = d.walls.reduce((a, w) => a + w.openings.length, 0);
    const parts = d.walls.filter((w) => w.role === "interior").length;
    const walls = `${d.walls.length - parts} walls${parts ? ` and ${parts} partition${parts === 1 ? "" : "s"}` : ""}`;
    el.innerHTML = `<div class="c-top">step 0 of ${n}</div>
      <div class="c-main">The bare house: ${walls} with ${ops} openings, no timber yet.</div>
      <div class="c-doc">Each wall is a surface: the plane of its framing's face. Press &#x2192; to fire the first rule.</div>`;
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
      <tr><td>wall</td><td>${m.surface ?? "-"}</td></tr>
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
  const w = d.wall, L = w.length, H = w.height, [SL, SH] = d.span;
  const pad = Math.max(SL, SH) / 50;
  const c = st.colors[d.rule] || "#888";
  const box = (b, cls, fillc) => `<rect class="${cls}" x="${b.u0}" y="${-b.v1}" width="${b.u1 - b.u0}" height="${b.v1 - b.v0}" fill="${fillc}"><title>${esc(b.id)} ${esc(b.role || b.rule)}</title></rect>`;
  const removed = new Set(d.removed.map((b) => b.id));
  const holes = w.openings.map((o) => `M${o.u0} ${-o.v1}h${o.u1 - o.u0}v${o.v1 - o.v0}h${o.u0 - o.u1}z`).join("");
  const before = d.before.filter((b) => !after || !removed.has(b.id));
  const t = d.target;
  return `<svg class="demo-svg" viewBox="${-pad - (SL - L) / 2} ${-(SH + pad)} ${SL + 2 * pad} ${SH + 2 * pad}">
    <path d="M0 ${-H}h${L}v${H}h${-L}z${holes}" fill="${SURF}" fill-opacity="0.18" fill-rule="evenodd"/>
    <rect class="outline" x="0" y="${-H}" width="${L}" height="${H}"/>
    ${d.neighbours.map((b) => box(b, "nb", "#e4e2dd")).join("")}
    ${before.map((b) => (t?.member === b.id ? box(b, `m now${after ? "" : " hit"}`, c) : box(b, "m", PAST))).join("")}
    ${after ? d.placed.map((b) => box(b, "m now", c)).join("") : d.removed.map((b) => box(b, "m gone", "none")).join("")}
    ${w.openings.map((o) => `<rect class="op" x="${o.u0}" y="${-o.v1}" width="${o.u1 - o.u0}" height="${o.v1 - o.v0}"/>`).join("")}
    ${w.tees.map((t) => `<g class="tee"><line x1="${t.u}" x2="${t.u}" y1="0" y2="${-H}"/><text x="${t.u}" y="${-H - pad / 4}" text-anchor="middle" font-size="${pad * 0.9}">${esc(t.wall)}</text></g>`).join("")}
    ${t && t.kind !== "member" ? (t.u1 - t.u0 < 1e-6
      ? `<line class="target ${after ? "out" : "trig"}" x1="${t.u0}" x2="${t.u0}" y1="${-t.v0}" y2="${-t.v1}" stroke="${c}"/>`
      : `<rect class="target ${after ? "out" : "trig"}" x="${t.u0}" y="${-t.v1}" width="${t.u1 - t.u0}" height="${t.v1 - t.v0}" stroke="${c}" fill="${c}"/>`) : ""}
  </svg>`;
}

function demoHtml(d) {
  if (!d.wall) {
    return `<p class="empty demo-none">${esc(d.message || "This rule did nothing on the toy house.")}</p>
      ${d.errors?.length ? `<p class="bad">${esc(d.errors[0])}</p>` : ""}`;
  }
  const c = st.colors[d.rule] || "#888";
  const n = d.placed.length, r = d.removed.length;
  const what = [n ? `placed ${n} member${n === 1 ? "" : "s"}` : "", r ? `removed ${r}` : ""].filter(Boolean).join(", ") || "changed nothing visible";
  const many = d.firings.length > 1;
  const nav = many ? `<span class="dnav" title="other firings of this rule on the toy house"><button data-firing="${d.firing - 1}" ${d.firing === 0 ? "disabled" : ""} title="previous firing">&#x2039;</button>
      firing ${d.firing + 1} of ${d.firings.length}
      <button data-firing="${d.firing + 1}" ${d.firing >= d.firings.length - 1 ? "disabled" : ""} title="next firing">&#x203A;</button></span>` : "";
  return `<div class="demo">
    <div class="dlab">Trigger: matched ${esc(d.match || "")} ${nav}</div>${demoSvg(d, false)}
    <div class="darrow">&#x2193; ${pill(d.rule, c)}</div>
    <div class="dlab">Output</div>${demoSvg(d, true)}
    <p class="dcap">On the toy house, wall ${esc(d.wall.id)}${d.target?.other ? ` where it meets ${esc(d.target.other)}` : ""}${d.target?.face === "inner" ? ", inside face" : ""},
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
    const w = e.target.closest("[data-wall]");
    if (w) {
      showTab("elev");
      document.getElementById(`wall-${w.dataset.wall}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
}

// ---------------------------------------------------------------- faults and report

function renderFaults() {
  const d = st.data;
  const groups = new Map();
  for (const f of d.faults) {
    const k = `${f.hard ? 0 : 1}|${f.check}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(f);
  }
  const keys = [...groups.keys()].sort((a, b) => a[0] - b[0] || groups.get(b).length - groups.get(a).length);
  const intro = `<p class="hint">Hard faults make the frame unbuildable; soft faults break code or good practice.
    Click a fault to see its wall, a member or rule to select it.</p>`;
  $("#faults").innerHTML = intro + (keys.map((k) => {
    const fs = groups.get(k);
    const f0 = fs[0];
    return `<div class="group"><h4><span class="tag ${f0.hard ? "" : "soft"}">${f0.hard ? "hard" : "soft"}</span>
        ${esc(f0.check)} <small>${fs.length}, ${esc(d.checks[f0.check] || "")}</small></h4>` +
      fs.map((f) => `<div class="fault" ${f.wall ? `data-wall="${f.wall}"` : ""} style="cursor:pointer">${esc(f.message)}
        <div>${f.members.filter((id) => st.byId[id]).map(chip).join("")}${f.rules.map((r) =>
          `<span class="chip" data-rule="${esc(r)}"><i style="background:${st.colors[r] || "#999"}"></i>${esc(r)}</span>`).join("")}</div></div>`).join("") +
      `</div>`;
  }).join("") || `<p class="empty">No faults: the current checks find nothing wrong with this frame.</p>`);
}

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

$("#src").addEventListener("input", editState);
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
$("#edRevert").addEventListener("click", () => { $("#src").value = st.saved; st.origin = null; editState(); build(); });
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

async function enterRuns() {
  try {
    await pollJobs();
    await loadRunsList();
    await loadRun();
  } catch (e) { status(e.message, true); }
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
  if (r.running.some((j) => j.kind === "evolve") || r.ended.length) {
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
      <b>${esc(r.name)}</b>${runningSearch(r.name) ? ` <span class="live">searching</span>` : ""}
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
  const key = JSON.stringify([rs.name, run?.iterations.length, run?.candidates.length, job?.id, rs.creds?.ok, rs.sel]);
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
      ${steerHtml(run, job)}</div>
    <section><h3>Progress <small>the best grammar so far, summed over the ${run.houses.length} training houses</small></h3>${progressSvg(run)}</section>
    <section><h3>Score per house <small>rows are the grammars kept, columns the training houses; click a row to see the grammar</small></h3>${paretoTable(run)}</section>
    <section><h3>Iterations <small>newest first; click one to see what the proposer saw and did</small></h3>${iterList(run)}</section>`;
}

function steerHtml(run, job) {
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
  const cand = e.target.closest("[data-cand]");
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
    hideTip();
    xh?.setAttribute("visibility", "hidden");
  }
});
$("#runsMain").addEventListener("pointerleave", hideTip);

function paretoTable(run) {
  const H = run.houses;
  const best = {};
  for (const h of H) {
    const sc = run.candidates.map((c) => c.scores[h]).filter(Boolean);
    best[h] = sc.length ? sc.reduce((a, b) => (lt(b, a) < 0 ? b : a)) : null;
  }
  const same = (a, b) => a && b && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  const rows = run.candidates.map((c) => {
    const wins = run.pareto[c.id]?.length || 0;
    const sel = rs.sel?.kind === "cand" && rs.sel.id === c.id;
    return `<tr data-cand="${esc(c.id)}" class="${sel ? "sel" : ""}">
      <th title="${esc(c.note)}"><b>${esc(c.id)}</b>${wins ? `<span class="pbadge" title="in the Pareto set: best on ${wins} of ${H.length} houses">best on ${wins}</span>` : ""}</th>
      ${H.map((h) => {
        const s = c.scores[h];
        if (!s) return `<td>-</td>`;
        return `<td class="${same(s, best[h]) ? "best" : ""}" data-tip="${esc(`<b>${c.id}</b> on ${h}: ${fmtScore(s)}${same(s, best[h]) ? ", the best on this house" : ""}`)}">
          ${s[0] ? `<span class="hardn">${s[0]}</span>` : ""}<b>${Math.round(s[2])}</b><small>${s[1]} soft</small></td>`;
      }).join("")}
      <td class="tot"><b>${Math.round(c.total[2])}</b><small>${c.total[0] ? `<span class="bad">${c.total[0]} hard</span> ` : ""}${c.total[1]} soft</small></td></tr>`;
  }).join("");
  return `<div class="tablewrap"><table class="pareto"><thead><tr><th>grammar</th>${H.map((h) => `<th>${esc(h)}</th>`).join("")}<th>total</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <p class="hint">Each cell: cost in linear ft (big), soft faults (small), hard faults in red when there are any.
    Green: the best grammar on that house. "best on" marks the Pareto set, from which parents are picked.</p>`;
}

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
    el.innerHTML = `<div class="dhead"><h2>${esc(c.id)}</h2>${wins.length ? `<span class="pbadge">Pareto set: best on ${wins.length} of ${run.houses.length} houses</span>` : `<span class="muted">not best on any house</span>`}</div>
      ${c.note ? `<p class="note">${esc(c.note)}</p>` : ""}
      <table class="kv">
        <tr><td>made in</td><td>${c.iteration ? `iteration <a href="#" data-it="${c.iteration}">${c.iteration}</a>` : "the start: the seed grammar"}</td></tr>
        <tr><td>lineage</td><td>${lineage(c.id).map(candChip).join(" &#x2192; ")}</td></tr>
        <tr><td>total</td><td>${fmtScore(c.total)}</td></tr>
        ${parent ? `<tr><td>vs ${esc(parent.id)}</td><td>${c.total[1] - parent.total[1]} soft, ${num(c.total[2] - parent.total[2])} ft cost</td></tr>` : ""}
        ${wins.length ? `<tr><td>best on</td><td>${wins.map(esc).join(", ")}</td></tr>` : ""}
      </table>
      <div class="actions"><button class="primary" data-open="${esc(c.id)}">Open in workbench</button><span class="muted">${openHint()}</span></div>
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
  if (open) return openInWorkbench(await runGrammar(open.dataset.open), `run ${rs.name}, ${open.dataset.open}`);
  const op = e.target.closest("button[data-openprop]");
  if (op && rs.proposed?.n === +op.dataset.openprop) return openInWorkbench(rs.proposed.source, `run ${rs.name}, proposal of iteration ${op.dataset.openprop}`);
  const ja = e.target.closest("button[data-jact]");
  if (ja && rs.sel?.kind === "job") {
    try { await api("POST", `/api/job/${rs.sel.id}/${ja.dataset.jact}`); await tick(); renderRunsDetail(); } catch (err) { status(err.message, true); }
  }
});

async function openInWorkbench(source, label) {
  $("#src").value = source;
  st.origin = label;
  editState();
  showTab("view3d");
  showTab("faults");
  if (await build()) status(`${label}, built on ${$("#house").value} from unsaved edits. Revert in the Grammar tab goes back.`);
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
$("#rebuild").addEventListener("click", build);
$("#house").addEventListener("change", () => { remember("house", $("#house").value); build(); });
$("#grammar").addEventListener("change", async () => {
  remember("grammar", $("#grammar").value);
  st.hidden.clear();
  st.sel = null;
  await loadGrammar();
  build();
});
$("#newHouse").addEventListener("click", async () => {
  try {
    const { id } = await api("POST", "/api/houses", {});
    await loadLists(id);
    remember("house", id);
    if (runsMode()) showTab("view3d");
    await build();
    status(`new house ${id}, built`);
  } catch (e) { status(e.message, true); }
});
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); build(); }
  const typing = ["TEXTAREA", "INPUT", "SELECT"].includes(document.activeElement?.tagName);
  if (typing || runsMode()) return;
  if (e.key === "Escape") select(null);
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
    await loadLists();
    await loadGrammar();
    await build();
    await pollJobs();
  } catch (e) {
    status(e.message, true);
  }
})();
