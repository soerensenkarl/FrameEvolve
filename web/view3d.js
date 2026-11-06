// The 3D view: the scene and its input (orbit, pan, zoom, pick), member meshes added one by one or all at
// once, the house's surfaces, fault marks and backing gaps, the current step's target, a chosen fault's
// evidence, the measure tool, and `look3d`, which recolours everything for the selection and the step shown.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { $, esc, ftin, S, SURF, FACE, GUIDE, st, finished, current, trigger, present, placedNow, goneNow, matchedMember,
  surfaceList, isWall, kindName, faceName, shown3d, isActive, memberColour, byPanel, panelOf, guideShown, showTip,
  hideTip } from "./state.js";
import { select, showTab } from "./app.js";
import { evidence, chosenFault } from "./inspect.js";

export let renderer, labeler, scene, camera, controls, group, gapGroup, markGroup, surfGroup, targetGroup, evGroup, guideGroup;
export const meshes = new Map();   // member id -> its mesh in `group`
export let surfs = [];   // per surface: {surface, mesh, line, label, opLabels}

export function setup3d() {
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
  // drag pans, Cmd/Ctrl + right drag zooms; wheel and trackpad are handled in bindViewInput
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
  guideGroup = new THREE.Group();
  scene.add(group, gapGroup, markGroup, surfGroup, targetGroup, evGroup, guideGroup);

  new ResizeObserver(resize).observe(el);
  bindViewInput(renderer.domElement);
  (function loop() {
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
    labeler.render(scene, camera);
  })();
}

function bindViewInput(canvas) {
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
  // by panel, the member under the pointer names its panel
  let hoverAt = null;
  canvas.addEventListener("pointermove", (e) => {
    if (!byPanel() || measure.on || e.buttons) { if (hoverAt !== null) { hoverAt = null; hideTip(); } return; }
    if (hoverAt) { hoverAt = e; return; }
    hoverAt = e;
    requestAnimationFrame(() => {
      const ev = hoverAt;
      hoverAt = false;
      if (!ev || !byPanel()) return;
      const id = pick(ev).hit?.object.userData.id, m = id && st.byId[id];
      if (!m) return hideTip();
      const p = panelOf(m);
      showTip(`${esc(m.id)} ${esc(m.role || m.rule)}: ${p ? `panel <b>${esc(p)}</b>` : "built on site"}`,
        { left: ev.clientX, top: ev.clientY - 8, width: 0, bottom: ev.clientY }, "above");
    });
  });
  canvas.addEventListener("pointerleave", () => { hoverAt = null; hideTip(); });
  canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY, e.button]; });
  canvas.addEventListener("pointerup", (e) => {
    if (zoomDrag) { zoomDrag = null; return; }
    if (!down || down[2] !== 0 || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    if (measure.on) return measureClick(e);
    const { hit } = pick(e);
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
}

function pick(e) {
  // a ray from the camera through the pointer: the canvas rectangle, the pointer in normalised device
  // coordinates, the raycaster, and the nearest visible member it hits (or undefined)
  const rect = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
  const ray = new THREE.Raycaster();
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObjects([...meshes.values()].filter((m) => m.visible), false)[0];
  return { rect, ndc, ray, hit };
}

const groundPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);

// ---------------------------------------------------------------- measure: click two points, snapping to members

const measure = { on: false, first: null, group: null, marker: null };
export const measuring = () => measure.on;

export function setMeasure(on) {
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
  const { rect: r, ndc, ray, hit } = pick(e);
  if (!hit) {
    const g = ray.ray.intersectPlane(groundPlane, new THREE.Vector3());
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

// ---------------------------------------------------------------- the camera

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
  const { ray, hit } = pick(e);
  const focus = hit?.point
    || ray.ray.intersectPlane(groundPlane, new THREE.Vector3())
    || ray.ray.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(
      camera.getWorldDirection(new THREE.Vector3()), controls.target), new THREE.Vector3())
    || controls.target.clone();
  if (factor < 1 && camera.position.distanceTo(controls.target) < 0.3) return;
  camera.position.sub(focus).multiplyScalar(factor).add(focus);
  controls.target.sub(focus).multiplyScalar(factor).add(focus);
}

export function zoomTo(p) {
  // keep the viewing direction, come within about ten feet of a point
  showTab("view3d");
  const t = new THREE.Vector3(...p.map((x) => x * S));
  const dir = camera.position.clone().sub(controls.target).normalize();
  controls.target.copy(t);
  camera.position.copy(t).addScaledVector(dir, 3);
}

export function fit() {
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

export function resize() {
  const el = $("#view3d");
  if (!el.clientWidth || !el.clientHeight) return;
  renderer.setSize(el.clientWidth, el.clientHeight);
  labeler.setSize(el.clientWidth, el.clientHeight);
  camera.aspect = el.clientWidth / el.clientHeight;
  camera.updateProjectionMatrix();
}

// ---------------------------------------------------------------- what is in the scene

function dispose(o) {
  o.traverse((c) => { c.geometry?.dispose(); c.material?.dispose?.(); });
}

export function clear(g) {
  for (const o of [...g.children]) {
    dispose(o);
    g.remove(o);
  }
}

// every surface maps its (u, v, w) to the world through its own axes
export function surfMatrix(s, out = 0) {
  // `out` pushes the plane out of the framing (outside a wall, above a floor), in metres
  const [eu, ev, ew] = [s.eu, s.ev, s.ew].map((a) => new THREE.Vector3(...a));
  const o = new THREE.Vector3(...s.origin).multiplyScalar(S).addScaledVector(ew, -out);
  return new THREE.Matrix4().makeBasis(eu, ev, ew).setPosition(o);
}

export function toLocal(s, p) {
  // a world point (inches) in a surface's u, v, w
  const q = [0, 1, 2].map((k) => p[k] - s.origin[k]);
  return [s.eu, s.ev, s.ew].map((a) => a[0] * q[0] + a[1] * q[1] + a[2] * q[2]);
}

export function label(text, cls, pos, groupTo = surfGroup) {
  const div = document.createElement("div");
  div.className = "lbl " + cls;
  div.innerHTML = text;
  const o = new CSS2DObject(div);
  o.position.copy(pos);
  groupTo.add(o);
  return o;
}

const v2 = (u, v) => new THREE.Vector2(u * S, v * S);

export function renderSurfaces(list = surfaceList()) {
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
    const lbl = label(`${esc(s.id)} <i>${name ? name + ", " : ""}${ftin(U)}${isWall(s) ? "" : ` x ${ftin(V)}`}</i>`, "surf", at.applyMatrix4(M));
    const ol = s.openings.map((o) => label(`${esc(o.kind)} ${ftin(o.u1 - o.u0)} x ${ftin(o.v1 - o.v0)}`, "op",
      new THREE.Vector3(((o.u0 + o.u1) / 2) * S, ((o.v0 + o.v1) / 2) * S, 0).applyMatrix4(M)));
    surfs.push({ surface: s.id, mesh, line, label: lbl, opLabels: ol });
  }
}

export function renderMarks() {
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
    s.userData.surface = f.surface;
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

export const edgeMaterial = () => new THREE.LineBasicMaterial({ color: 0x1d1d1b, transparent: true, opacity: 0.35 });

export function addMember(m, mat, edgeMat) {
  // a member's mesh in the scene; a member already there (one a later rule cut or notched) is replaced
  removeMember(m.id);
  const mesh = memberMesh(m, mat, edgeMat);
  group.add(mesh);
  meshes.set(m.id, mesh);
}

export function removeMember(id) {
  const x = meshes.get(id);
  if (!x) return;
  group.remove(x);
  dispose(x);
  meshes.delete(id);
}

export function startLiveDraw() {
  // the view while a build streams in: no members, no marks, no guides; the surfaces come with the stream's first line
  clear(group);
  clear(guideGroup);
  meshes.clear();
  gapGroup.visible = markGroup.visible = false;
}

export function render3d() {
  clear(group);
  meshes.clear();
  const edgeMat = edgeMaterial();
  for (const m of st.data.members) addMember(m, new THREE.MeshStandardMaterial({ roughness: 0.85, transparent: true }), edgeMat);
  renderMarks();
  renderSurfaces();
  renderGuides();
  if (st.fitFor !== st.data.house) {
    st.fitFor = st.data.house;
    fit();
  }
  look3d();
}

export function related() {
  // id -> relation to the selection: "self", "bears", "carries", "side", "rule"; null when nothing is selected.
  // A fault chosen in the Verifier tab works like a selection: its members, and what holds them.
  const sel = st.sel, f = chosenFault();
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

export function look3d() {
  if (!st.data) return;
  const rel = related();
  const done = finished();
  for (const [id, mesh] of meshes) {
    const m = st.byId[id];
    const r = rel?.get(id);
    const gone = goneNow(id);
    mesh.visible = !st.hidden.has(m.rule) && (present(id) || gone) && shown3d(m.surface);
    const mat = mesh.material;
    const isNow = placedNow(id);
    const hit = matchedMember(id);
    const c = memberColour(m, r);
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
    const active = isActive(s.surface);
    const vis = on && shown3d(s.surface);
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
  const guides = $("#showGuides").checked;
  guideGroup.visible = guides;
  if (guides) for (const o of guideGroup.children) o.visible = guideShown(o.userData.guide) && shown3d(o.userData.guide.surface);
  renderTarget3d();
  renderEvidence3d();
}

function renderGuides() {
  // guide lines, thin and dashed, a hair off the surface they lie on (plan guides just above the ground)
  clear(guideGroup);
  const mats = {};
  const mat = (kind) => mats[kind] || (mats[kind] = new THREE.LineDashedMaterial({ color: GUIDE[kind] || GUIDE.grid,
    dashSize: 0.1, gapSize: 0.07, transparent: true, opacity: kind === "panel joint" ? 0.9 : 0.45 }));
  for (const g of st.data.guides) {
    const s = st.surf[g.surface];
    const off = s ? new THREE.Vector3(...s.ew).multiplyScalar(-0.006) : new THREE.Vector3(0, 0, 0.003);
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(g.world.map((p) =>
      new THREE.Vector3(...p.map((x) => x * S)).add(off))), mat(g.kind));
    line.computeLineDistances();
    line.userData.guide = g;
    line.renderOrder = 4;
    guideGroup.add(line);
  }
}

// ---------------------------------------------------------------- marks on a surface: the step's target, a fault's evidence

function depthOf(id) {
  // how far a surface's framing reaches in from it: the commonest reach of its members
  const n = {};
  for (const m of st.data.members) if (m.surface === id && m.local && present(m.id)) n[m.local[1][2]] = (n[m.local[1][2]] || 0) + 1;
  const best = Object.entries(n).sort((a, b) => b[1] - a[1])[0];
  return best ? +best[0] : st.surf[id]?.depth || 3.5;
}

export function otherEnd(t) {
  // where the other wall of a corner or tee meets this one, in its own coordinates
  const o = (t.kind === "corner" || t.kind === "tee") && st.surf[t.other];
  return o ? { surface: o.id, u0: o.end_meets === t.surface ? o.length : 0, u1: o.end_meets === t.surface ? o.length : 0, v0: 0, v1: o.height } : null;
}

export const isLine = (t) => t.u1 - t.u0 < 1e-6 || t.v1 - t.v0 < 1e-6;

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
  markOn(targetGroup, t.surface, t, c, trig, t.face);
  const o = otherEnd(t);
  if (o) markOn(targetGroup, o.surface, o, c, trig);
}

const EV = "#d8342c";   // evidence drawn for the chosen fault

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
