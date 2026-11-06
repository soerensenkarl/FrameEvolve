// The Runs view: the search and steering it. The side lists runs, jobs and tests; the main pane shows the
// selected run (progress, the Pareto set, lineage, trade-off, iterations); the detail pane shows a kept
// grammar with its diff, an iteration's proposal, a job's log, or the new-run form.
import { $, esc, num, ago, plain, st, api, status, remember, recall, runsMode, grammarList, loadLists, showTip,
  hideTip } from "./state.js";
import { build, showTab } from "./app.js";
import { loadGrammar, editState } from "./editor.js";
import { lv, startLive, setFollow, renderRunLive } from "./live.js";

export const rs = {
  list: [], name: recall("run"), run: null, sel: null, src: {}, jobs: [], creds: null,
  anyRunning: false, watch: new Set(), mainKey: "", form: null,
};

export async function loadRunsList() {
  rs.list = await api("GET", "/api/runs");
  if (!rs.list.some((r) => r.name === rs.name) && !runningSearch(rs.name)) rs.name = rs.list[0]?.name ?? null;
}

async function loadRun() {
  rs.run = null;
  if (rs.name && rs.list.some((r) => r.name === rs.name)) {
    try { rs.run = await api("GET", `/api/run/${rs.name}`); } catch (e) { status(e.message, true); }
  }
}

export async function pollJobs() {
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

export async function enterRuns() {
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

export const fmtScore = (s) => `${s[0]} hard, ${s[1]} soft, cost ${num(s[2])} ft`;
export const lt = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

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

export function diffHtml(a, b, ctx = 3) {
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
