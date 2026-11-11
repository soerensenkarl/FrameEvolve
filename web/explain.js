// The About tab: the project as one figure, inputs -> the loop -> output, drawn from the house and grammar open
// now (and the latest search run). The loop: the proposer (Claude) edits the grammar; the builder frames the house
// with it; the verifier scores the frame; the search keeps what improves and hands a parent back to the proposer.
// Click any box for what it is, with the real thing below: the grammar's rules, the build's steps, a framed wall,
// the faults, the run's progress, a proposer's lesson.
import { $, esc, st, houseList, PALETTE, ftin } from "./state.js";
import { showTab } from "./app.js";
import { rs } from "./runs.js";

let chosen = "grammar", timer = null, leg = 0, run = null, runFor = null;
const TOUR = ["house", "grammar", "builder", "frame", "verifier", "search", "proposer", "grammar", "output"];

// ---------------------------------------------------------------- what the figure draws from

const house = () => houseList.find((x) => x.id === st.data?.house);
const rules = () => (st.data?.rules || []).filter((r) => r.name);
const source = () => $("#src")?.value || "";

function wall() {
  // the framed wall to show: on the ground storey, the exterior one with the most openings, then the longest
  const ws = (st.data?.walls || []).filter((w) => w.role === "exterior");
  const low = Math.min(...ws.map((w) => st.level[w.id] ?? 1));
  return ws.filter((w) => (st.level[w.id] ?? 1) === low)
    .sort((a, b) => b.openings.length - a.openings.length || b.size[0] - a.size[0])[0];
}

function elevation(w, x, y, W, H, colour) {
  // a wall's members as an elevation fitted in W x H at x, y; colour(m) fills each member
  if (!w) return "";
  const [U, V] = w.size, k = Math.min(W / U, H / V), ox = x + (W - U * k) / 2, oy = y + H - (H - V * k) / 2;
  const ms = st.data.members.filter((m) => m.surface === w.id && m.local);
  const shape = (m) => {
    if (m.poly) return `<path d="${m.poly.map((p) => `M${p.map(([u, v]) => `${ox + u * k} ${oy - v * k}`).join("L")}z`).join("")}" fill="${colour(m)}"/>`;
    const [lo, hi] = m.local;
    return `<rect x="${ox + lo[0] * k}" y="${oy - hi[1] * k}" width="${(hi[0] - lo[0]) * k}" height="${(hi[1] - lo[1]) * k}" fill="${colour(m)}"/>`;
  };
  return `<g class="ex-wall">${w.openings.map((o) => `<rect class="ex-op" x="${ox + o.u0 * k}" y="${oy - o.v1 * k}" width="${(o.u1 - o.u0) * k}" height="${(o.v1 - o.v0) * k}"/>`).join("")}
    ${ms.map(shape).join("")}</g>`;
}

const byRule = (m) => st.colors[m.rule] || "#999";
const panelHue = {};
const byPanel = (m) => (m.panel ? panelHue[m.panel] ||= PALETTE[Object.keys(panelHue).length % PALETTE.length] : "#c9c5bc");

function modules() {
  // faults by verifier module, in the verifier's order: [question, hard, soft]
  const of = Object.fromEntries((st.vinfo?.checks || []).map((c) => [c.name, c.module]));
  return (st.vinfo?.modules || []).filter((m) => m.checks.length).map((m) => {
    const fs = (st.data?.faults || []).filter((f) => of[f.check] === m.name);
    return [m.question, fs.filter((f) => f.hard).length, fs.filter((f) => !f.hard).length, m.name];
  });
}

async function loadRun() {
  // the most recent search run, for the search and the proposer
  const name = rs.list?.[0]?.name;
  if (!name || runFor === name) return;
  runFor = name;
  try { run = await (await fetch(`/api/run/${encodeURIComponent(name)}`)).json(); } catch { run = null; }
  renderExplain();
}

function progress() {
  // the run's best hard faults on its validation houses as it went: one value per kept candidate, in order
  if (!run?.candidates) return [];
  const sum = (c) => Object.values(c.scores || {}).reduce((t, s) => t + s[0], 0);
  let best = Infinity;
  return run.candidates.map((c) => (best = Math.min(best, sum(c))));
}

const lastLesson = () => [...(run?.iterations || [])].reverse().find((it) => it.lessons?.length);

// ---------------------------------------------------------------- the boxes' pictures

function grammarLines(x, y, n) {
  return rules().slice(0, n).map((r, i) => `<g transform="translate(${x} ${y + i * 15})"><rect width="8" height="8" y="-7" rx="2" fill="${st.colors[r.name] || "#999"}"/>
    <text class="ex-mono" x="13">@rule(${r.priority}) ${esc(r.name.length > 13 ? r.name.slice(0, 12) + "…" : r.name)}</text></g>`).join("") +
    (rules().length > n ? `<text class="ex-small" x="${x}" y="${y + n * 15}">+ ${rules().length - n} more rules</text>` : "");
}

function stepStrip(x, y, W) {
  const steps = st.data?.steps || [];
  if (!steps.length) return "";
  const w = W / steps.length;
  return steps.map((s, i) => `<rect x="${x + i * w}" y="${y}" width="${Math.max(w, .6)}" height="10" fill="${st.colors[s.rule] || "#999"}"/>`).join("");
}

const SHORT = { physical: "stand", analysis: "hold", boards: "skin", code: "code", prefab: "panels", design: "design" };

function bars(x, y, W) {
  // faults by module: one short word for the question each asks, a bar of hard (red) and soft (amber) faults
  const ms = modules(), most = Math.max(1, ...ms.map(([, h, s]) => h + s)), L = 44, B = W - L;
  return ms.map(([q, h, s, name], i) => `<g transform="translate(${x} ${y + i * 16})"><title>${esc(q)} ${h} hard, ${s} soft</title>
    <text class="ex-small" x="0" y="0">${esc(SHORT[name] || name)}</text>
    <rect x="${L}" y="-8" width="${B * h / most}" height="8" fill="var(--err)"/>
    <rect x="${L + B * h / most}" y="-8" width="${B * s / most}" height="8" fill="var(--soft)"/></g>`).join("");
}

function curve(x, y, W, H) {
  const p = progress();
  if (p.length < 2) return `<text class="ex-small" x="${x}" y="${y + H / 2}">no search run yet</text>`;
  const hi = p[0], lo = Math.min(...p), sx = (i) => x + W * i / (p.length - 1), sy = (v) => y + H - H * (v - lo) / Math.max(1, hi - lo);
  return `<path class="ex-curve" d="${p.map((v, i) => `${i ? "L" : "M"}${sx(i)} ${sy(v)}`).join("")}"/>
    ${p.map((v, i) => `<circle cx="${sx(i)}" cy="${sy(v)}" r="2.5" class="ex-pt"/>`).join("")}
    <text class="ex-small" x="${x}" y="${y + H + 12}">hard faults, ${hi} to ${p.at(-1)}</text>`;
}

const chips = (x, y, names) => {
  let cx = x;
  return names.map((n) => { const w = 7 * n.length + 12, g = `<g transform="translate(${cx} ${y})"><rect width="${w}" height="16" rx="8" class="ex-chip"/><text class="ex-small" x="${w / 2}" y="11.5" text-anchor="middle">${n}</text></g>`; cx += w + 4; return g; }).join("");
};

// ---------------------------------------------------------------- the figure

const BOX = {   // id: x, y, w, h, title
  house:    [20, 70, 200, 150, "House"],
  seed:     [20, 268, 200, 168, "Seed grammar"],
  proposer: [425, 52, 270, 112, "Proposer (Claude)"],
  search:   [770, 52, 130, 112, "Search"],
  grammar:  [300, 248, 170, 168, "Grammar"],
  frame:    [520, 248, 170, 168, "Frame"],
  verifier: [740, 248, 155, 168, "Verifier"],
  output:   [960, 150, 170, 200, "Best grammar"],
};

function box(id, inner, sub = "", stage = id) {
  const [x, y, w, h, title] = BOX[id];
  return `<g class="ex-node ${chosen === stage ? "sel" : ""}" data-stage="${stage}" tabindex="0" role="button" aria-label="${esc(title)}">
    <text class="ex-title" x="${x + w / 2}" y="${y - 8}" text-anchor="middle">${esc(title)}</text>
    <rect class="ex-box" x="${x}" y="${y}" width="${w}" height="${h}" rx="8"/>${inner}
    ${sub ? `<text class="ex-small ex-sub" x="${x + w / 2}" y="${y + h - 8}" text-anchor="middle">${esc(sub)}</text>` : ""}</g>`;
}

function arrow(d, label, lx, ly, on, anchor = "middle") {
  return `<path class="ex-arrow ${on ? "on" : ""}" d="${d}" marker-end="url(#ex-head${on ? "-on" : ""})"/>
    ${label ? `<text class="ex-label ${on ? "on" : ""}" x="${lx}" y="${ly}" text-anchor="${anchor}">${label}</text>` : ""}`;
}

function figure() {
  const h = house(), w = wall(), is = (...ids) => ids.includes(chosen);
  const [hx, hy] = BOX.house, [fx, fy] = BOX.frame, [ox, oy] = BOX.output, [px, py] = BOX.proposer, [sx, sy] = BOX.search;
  const [gx, gy] = BOX.grammar, [vx, vy] = BOX.verifier, [sdx, sdy] = BOX.seed;
  return `<svg class="ex-svg" viewBox="0 0 1150 470" role="img" aria-label="FrameEvolve: inputs, the loop, the output">
    <defs>${["", "-on"].map((k) => `<marker id="ex-head${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0L10 5L0 10z" class="ex-head${k}"/></marker>`).join("")}</defs>
    <text class="ex-col" x="120" y="22" text-anchor="middle">INPUTS</text>
    <text class="ex-col" x="597" y="22" text-anchor="middle">THE LOOP</text>
    <text class="ex-col" x="1045" y="22" text-anchor="middle">OUTPUT</text>
    <rect class="ex-env" x="282" y="218" width="632" height="232" rx="12"/>
    <text class="ex-envlabel" x="296" y="440">deterministic: the same grammar on the same house always gives the same frame and score</text>

    ${box("house", h ? `<image href="/api/house/${encodeURIComponent(h.id)}/thumb.svg" x="${hx + 25}" y="${hy + 14}" width="150" height="96"/>` : "", h ? `${h.id}: ${ftin(h.size[0])} x ${ftin(h.size[1])}, ${h.storeys} storey${h.storeys > 1 ? "s" : ""}` : "")}
    ${box("seed", `<text class="ex-mono" x="${sdx + 12}" y="${sdy + 24}">plates, studs at 24",</text>
      <text class="ex-mono" x="${sdx + 12}" y="${sdy + 40}">kings and headers, joists,</text>
      <text class="ex-mono" x="${sdx + 12}" y="${sdy + 56}">rafters, a panel a wall</text>
      <text class="ex-small" x="${sdx + 12}" y="${sdy + 84}">the obvious first moves of a</text>
      <text class="ex-small" x="${sdx + 12}" y="${sdy + 98}">framer; everything else</text>
      <text class="ex-small" x="${sdx + 12}" y="${sdy + 112}">is left to the search</text>`, "", "grammar")}
    ${box("proposer", `<text class="ex-mono" x="${px + 14}" y="${py + 26}">reads the reports, looks at the</text>
      <text class="ex-mono" x="${px + 14}" y="${py + 41}">frame, tries variations, edits</text>
      ${chips(px + 14, py + 54, ["try_on", "look", "frame", "trace", "edit"])}`, "the only LLM in the loop")}
    ${box("search", `<g>${curve(sx + 14, sy + 16, BOX.search[2] - 28, 46)}</g>`, "")}
    ${box("grammar", grammarLines(gx + 12, gy + 22, 7), `${rules().length} rules`)}
    ${box("frame", elevation(w, fx + 10, fy + 12, BOX.frame[2] - 20, 120, byRule), w ? `${st.data.stats.members} members; wall ${w.id}` : "")}
    ${box("verifier", `<g>${bars(vx + 10, vy + 24, BOX.verifier[2] - 20)}</g>`, st.data ? `${st.data.stats.hard} hard, ${st.data.stats.soft} soft` : "")}
    ${box("output", elevation(w, ox + 10, oy + 12, BOX.output[2] - 20, 120, byPanel) +
      `<text class="ex-small" x="${ox + 12}" y="${oy + 150}">framed as prefab panels,</text>
       <text class="ex-small" x="${ox + 12}" y="${oy + 164}">scored on unseen houses</text>`)}

    <g class="ex-node ${chosen === "builder" ? "sel" : ""}" data-stage="builder" tabindex="0" role="button" aria-label="Builder">
      ${arrow(`M${gx + 170} ${gy + 84}L${fx} ${fy + 84}`, "", 0, 0, is("builder", "grammar", "frame"))}
      <rect class="ex-pill" x="${gx + 172}" y="${gy + 50}" width="46" height="18" rx="9"/>
      <text class="ex-small" x="${gx + 195}" y="${gy + 63}" text-anchor="middle">builder</text>
      ${stepStrip(gx + 172, gy + 96, 46)}
    </g>
    ${arrow(`M${fx + 170} ${fy + 84}L${vx} ${vy + 84}`, "", 0, 0, is("frame", "verifier"))}
    ${arrow(`M${sx + 65} ${vy}L${sx + 65} ${sy + 112}`, "the score", sx + 71, vy - 40, is("verifier", "search"), "start")}
    ${arrow(`M${sx} ${sy + 56}L${px + 270} ${py + 56}`, "a parent", sx - 37, sy + 48, is("search", "proposer"))}
    <text class="ex-label ${is("search", "proposer") ? "on" : ""}" x="${sx - 37}" y="${sy + 72}" text-anchor="middle">+ faults</text>
    ${arrow(`M${px + 40} ${py + 112}L${px + 40} ${gy - 32}L${gx + 145} ${gy - 32}L${gx + 145} ${gy}`, "an edit", px + 46, py + 136, is("proposer", "grammar"), "start")}
    ${arrow(`M${hx + 200} ${hy + 75}C${hx + 300} ${hy + 75} ${fx + 40} ${hy + 120} ${fx + 40} ${fy}`, "surfaces + loads", hx + 214, hy + 66, is("house", "builder", "frame"), "start")}
    ${arrow(`M${sdx + 200} ${sdy + 84}L${gx} ${sdy + 84}`, "", 0, 0, is("grammar"))}
    <path class="ex-big" d="M918 290h28v-12l18 22-18 22v-12h-28z"/>
  </svg>`;
}

// ---------------------------------------------------------------- the panel under it: the real thing

const fact = (n, what) => `<div><b>${esc(n)}</b><span>${esc(what)}</span></div>`;

function ruleSource(n) {
  // the first n rules of the grammar open now, as written
  const lines = source().split("\n"), first = rules().slice().sort((a, b) => a.line - b.line).slice(0, n);
  return first.map((r) => lines.slice(r.line - 2, r.end).join("\n")).join("\n\n");
}

const DETAIL = {
  house: () => {
    const h = house(), d = st.data;
    return { title: "House", sub: "the input",
      text: `A house is labelled surfaces: walls with their doors and windows, floors, ceilings and roof planes. Nothing is
        framed. Before any timber is placed, the loads are taken down on these surfaces, roof to ground: what lands on
        each wall, where an opening gathers load into a point, how hard the wind racks each wall. Rules can read all of it.`,
      body: h ? `<div class="ex-row"><img class="ex-thumb" src="/api/house/${encodeURIComponent(h.id)}/thumb.svg" width="240" height="154" alt="">
        <div class="ex-facts">${fact(h.id, `${h.kind} house`)}${fact(d.walls.length, "walls")}${fact(d.floors.length, "floors and ceilings")}
        ${fact(d.roofs.length, "roof planes")}${fact(h.openings, "openings")}</div></div>` : "",
      go: ["view3d", "See this house in 3D"] };
  },
  grammar: () => ({ title: "Grammar", sub: "what is learned",
    text: `A file of small rules. Each says what it matches (a wall, an opening, a corner, a point load ...), when, and what
      to do there: place a member, cut it, lay out a guide, put it in a prefab panel. The order of rules is the grammar's
      own. The search starts from a bare-bones seed. These are the first rules of the grammar open now:`,
    body: `<pre class="ex-code">${esc(ruleSource(2))}</pre>
      <div class="ex-rules">${rules().map((r) => `<span><i style="background:${st.colors[r.name]}"></i>${r.priority} ${esc(r.name)} <small>${esc(r.match || "")}</small></span>`).join("")}</div>`,
    go: ["editor", "Read and edit the whole grammar"] }),
  builder: () => {
    const steps = st.data?.steps || [];
    return { title: "Builder", sub: "applies the rules",
      text: `Rule by rule, in priority order, the builder finds every match and fires the rule once on each; passes repeat
        until nothing changes, so a rule can react to what others built. Every step is recorded. The first steps of this build:`,
      body: `<ol class="ex-steps">${steps.slice(0, 8).map((s) => `<li><i style="background:${st.colors[s.rule]}"></i><b>${esc(s.rule)}</b>
        on ${esc(s.match)}: ${s.placed.length ? `placed ${s.placed.length}` : ""}${s.shaped?.length ? ` shaped ${s.shaped.length}` : ""}${s.assigned?.length ? ` put ${s.assigned.length} in panels` : ""}${s.guides?.length ? ` laid ${s.guides.length} guides` : ""}</li>`).join("")}</ol>
        <p class="ex-muted">... ${steps.length} steps in all.</p>`,
      go: ["view3d", "Step through the build"] };
  },
  frame: () => {
    const s = st.data?.stats, w = wall();
    return { title: "Frame", sub: "the output of one build",
      text: `Every piece of timber, exact, each knowing the rule that placed it, and grouped into prefab panels: wall panels
        and floor cassettes built flat in a shop, trucked, and lifted into place bottom up. One wall of it, coloured by rule:`,
      body: `<svg class="ex-big-wall" viewBox="0 0 800 260">${elevation(w, 0, 0, 800, 260, byRule)}</svg>
        <div class="ex-facts">${fact(s.members, "members")}${fact(s.panels ?? 0, "prefab panels")}${fact(s.site_pieces ?? 0, "pieces built on site")}${fact(`${Math.round(s.cost).toLocaleString()} ft`, "cost, as 2x4")}</div>`,
      go: ["view3d", "Look at the frame in 3D"] };
  },
  verifier: () => {
    const hard = (st.data?.faults || []).filter((f) => f.hard), seen = new Set();
    const examples = hard.filter((f) => !seen.has(f.check) && seen.add(f.check)).slice(0, 4);
    return { title: "Verifier", sub: "deterministic, no LLM",
      text: `It asks what an inspector, an engineer and a panel shop would. Hard faults make a frame unbuildable or unsafe;
        soft faults are details. The score is (hard, soft, cost), compared in that order. On this frame:`,
      body: `<table class="ex-table">${modules().map(([q, h, s]) => `<tr><td>${esc(q)}</td><td class="bad">${h || ""}</td><td class="warn">${s || ""}</td></tr>`).join("")}</table>
        <ul class="ex-faults">${examples.map((f) => `<li><span class="tag">${esc(f.check)}</span> ${esc(f.message)}</li>`).join("")}</ul>`,
      go: ["verifier", "See every check and fault"] };
  },
  search: () => {
    const p = progress();
    return { title: "Search", sub: "keeps what improves",
      text: `A new grammar is kept only if it beats its parent on the few houses it was shown. Kept grammars are scored on
        validation houses, and every grammar that is best at some house stays (a Pareto set), so different strengths survive.
        Test houses stay unseen to the end.${run ? ` The latest run, ${esc(runFor)}:` : ""}`,
      body: p.length > 1 ? `<svg class="ex-big-wall" viewBox="0 0 800 200">${curve(30, 20, 740, 140)}</svg>
        <div class="ex-facts">${fact(run.iterations.length, "iterations")}${fact(run.candidates.length, "grammars kept")}${fact(`${p[0]} → ${p.at(-1)}`, "hard faults on the validation houses")}</div>` : `<p class="ex-muted">No search run yet.</p>`,
      go: ["runs", "Open the search runs"] };
  },
  proposer: () => {
    const it = lastLesson();
    return { title: "Proposer", sub: "Claude, the only LLM in the loop",
      text: `Each iteration a fresh Claude gets a parent grammar, the verifier's reports on a few houses, and the lessons
        of the proposers before it. It works like a designer at a CAD station: tries variations on a house in seconds,
        looks at pictures, reads the frame member by member, then edits the grammar and writes down what it learned.`,
      body: it ? `<p class="ex-muted">A lesson from iteration ${it.iteration} of ${esc(runFor)}:</p><blockquote class="ex-quote">${esc(it.lessons[0])}</blockquote>
        ${it.usage ? `<div class="ex-facts">${fact(it.usage.tries ?? 0, "variations tried")}${fact(it.usage.looks ?? 0, "pictures looked at")}${fact(it.usage.turns ?? 0, "turns")}${fact(it.accepted ? "kept" : "dropped", "its edit")}</div>` : ""}` : "",
      go: ["runs", "See what the proposers did"] };
  },
  output: () => ({ title: "Best grammar", sub: "the result",
    text: `What a run gives: a grammar, readable rule by rule, that frames houses it never saw as prefab panels that pass the
      verifier. The same wall, now by prefab panel:`,
    body: `<svg class="ex-big-wall" viewBox="0 0 800 260">${elevation(wall(), 0, 0, 800, 260, byPanel)}</svg>`,
    go: ["runs", "Compare the grammars a run kept"] }),
};

function detail() {
  const d = DETAIL[chosen]();
  return `<div class="ex-detail"><h2>${esc(d.title)} <small>${esc(d.sub)}</small></h2><p>${d.text}</p>${d.body}
    <button class="primary" data-go="${d.go[0]}">${esc(d.go[1])}</button></div>`;
}

export function renderExplain() {
  if (!st.data) { $("#explain").innerHTML = `<p class="empty">Building...</p>`; return; }
  loadRun();
  $("#explain").innerHTML = `<div class="ex-wrap">
    <h1>FrameEvolve</h1>
    <p class="ex-lead">A language model edits a grammar of framing rules. A deterministic verifier scores the frames the
      grammar builds. A search keeps what improves. Timber framing, built as prefab panels, is the case study; the loop
      is the contribution. Everything below is drawn from the house and grammar open now. Click any box.</p>
    <div class="ex-tools"><button data-play>${timer ? "&#x23F8; Pause" : "&#x25B6; Play one iteration"}</button></div>
    ${figure()}${detail()}</div>`;
}

function stop() { clearInterval(timer); timer = null; }

function play() {
  if (timer) { stop(); return renderExplain(); }
  leg = 0;
  chosen = TOUR[0];
  timer = setInterval(() => {
    leg++;
    if (leg >= TOUR.length) stop(); else chosen = TOUR[leg];
    renderExplain();
  }, 3200);
  renderExplain();
}

function choose(id) { stop(); chosen = id; renderExplain(); }

$("#explain").addEventListener("click", (e) => {
  const go = e.target.closest("[data-go]");
  if (go) {
    stop();
    if (go.dataset.go === "editor") showTab("view3d");     // the grammar is in the side panel, beside the 3D view
    return showTab(go.dataset.go);
  }
  if (e.target.closest("[data-play]")) return play();
  const node = e.target.closest("[data-stage]");
  if (node) choose(node.dataset.stage);
});
$("#explain").addEventListener("keydown", (e) => {
  const node = e.target.closest("[data-stage]");
  if (node && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); choose(node.dataset.stage); }
});
