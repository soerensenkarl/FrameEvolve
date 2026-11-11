// The About tab: the project in one diagram. Seven stages on a loop (a house comes in; the grammar, the builder,
// the frame, the verifier, the search and the proposer go round); click a stage for what it is, with the
// numbers of the house and grammar open now and a way to the tab that shows it; Play walks one iteration.
import { $, esc, st, houseList } from "./state.js";
import { showTab } from "./app.js";

const W = 150, H = 62;   // a stage's box

// each stage: where it is, what it says, and what it is in words; `facts` reads the frame open now
const STAGES = [
  { id: "house", x: 10, y: 60, title: "House", sub: "surfaces, no timber",
    text: `The input. A house is labelled surfaces: walls with their doors and windows, floors, ceilings and roof planes.
      Nothing is framed yet. The houses are generated: boxes, L, T and U shapes, one to three storeys.
      Before any timber is placed, the loads are taken down on these surfaces, top to bottom: what lands on each wall,
      where an opening gathers load into a point, and how hard the wind racks each wall. Rules can read all of it.`,
    facts: () => { const h = houseList.find((x) => x.id === st.data?.house);
      return [[houseList.length, "houses to choose from"], ...(h ? [[h.storeys, h.storeys > 1 ? "storeys in this one" : "storey in this one"], [h.openings, "openings"]] : [])]; },
    go: ["view3d", "See this house in 3D"] },
  { id: "grammar", x: 260, y: 250, title: "Grammar", sub: "small rules, in Python",
    text: `What is being learned. A grammar is a file of small rules. Each rule says what it matches (a wall, an opening,
      a corner, a point load ...), when, and what to do there: place a member, cut it, lay out a guide, put it in a
      prefab panel. The search starts from a bare-bones seed that knows only the obvious first moves of a framer.`,
    code: `@rule(61, match="wall")
def studs(s, w):
    """A stud at each end, and every 24" between."""
    for u in every(24, w.length):
        s.place("2x6", u, u + 1.5, 1.5, top(s) - 1.5)`,
    facts: () => [[st.data?.rules.length ?? "-", "rules in the grammar open now"]],
    go: ["editor", "Read and edit the grammar"] },
  { id: "builder", x: 260, y: 60, title: "Builder", sub: "applies the rules",
    text: `Applies the grammar to a house. Rule by rule, in priority order, it finds every match and fires the rule once
      on each; passes repeat until nothing changes, so a rule can react to what others built. Every step is recorded:
      which rule fired, on what, and what it placed. The order of rules is not prescribed. It is part of what is learned.`,
    facts: () => [[st.data?.steps.length ?? "-", "steps to build this frame"]],
    go: ["view3d", "Step through the build"] },
  { id: "frame", x: 495, y: 60, title: "Frame", sub: "members in panels",
    text: `The output: every piece of timber, exact, each knowing the rule that placed it. From their geometry comes a
      contact graph (what rests on what, down to the ground). Members are grouped into prefab panels, wall panels and
      floor cassettes built flat in a shop, trucked, and lifted into place from the bottom up.`,
    facts: () => { const s = st.data?.stats; return s ? [[s.members, "members"], [s.panels ?? 0, "prefab panels"], [s.site_pieces ?? 0, "pieces built on site"]] : []; },
    go: ["view3d", "Look at the frame"] },
  { id: "verifier", x: 730, y: 60, title: "Verifier", sub: "deterministic checks",
    text: `Scores the frame with no LLM involved. It asks what an inspector, an engineer and a panel shop would: can it
      stand, will it hold its loads and the wind, can it be skinned, would it pass the building code, can it be built as
      panels and cut by a saw, what does it cost. Hard faults make a frame unbuildable or unsafe; soft faults are
      details. The score is (hard, soft, cost), compared in that order.`,
    facts: () => { const s = st.data?.stats; return [[st.vinfo?.checks.length ?? "-", "checks"], ...(s ? [[s.hard, "hard faults on this frame"], [s.soft, "soft faults"]] : [])]; },
    go: ["verifier", "See every check and fault"] },
  { id: "search", x: 730, y: 250, title: "Search", sub: "keeps what improves",
    text: `Decides what survives. A new grammar is kept only if it beats its parent on the houses it was shown. Kept
      grammars are scored on separate validation houses, and the search holds on to every grammar that is the best at
      some house (a Pareto set), so different strengths survive and get combined later. Test houses stay unseen
      to the end.`,
    facts: () => [],
    go: ["runs", "Open the search runs"] },
  { id: "proposer", x: 495, y: 250, title: "Proposer", sub: "Claude edits the grammar",
    text: `The only LLM in the loop. Each iteration a fresh Claude gets a parent grammar, the verifier's reports on a few
      houses, pictures of the frames, and a notebook of lessons from the proposers before it. It works like a designer
      at a CAD station: tries variations on a house in seconds, looks at pictures, reads the frame member by member,
      then proposes an edit and writes down what it learned.`,
    facts: () => [],
    go: ["runs", "See what proposers did"] },
];

// the arrows, in the order one iteration goes round; the first only feeds the loop
const FLOW = [
  ["house", "builder", "house + loads"], ["grammar", "builder", "rules"], ["builder", "frame", ""],
  ["frame", "verifier", ""], ["verifier", "search", "(hard, soft, cost)"], ["search", "proposer", "a parent"],
  ["proposer", "grammar", "an edit"],
];
const TOUR = ["house", "grammar", "builder", "frame", "verifier", "search", "proposer", "grammar"];

let chosen = "grammar", timer = null, leg = 0;
let dotAt = chosen;      // where the dot was drawn last, so it glides to the chosen stage
const stage = (id) => STAGES.find((s) => s.id === id);
const at = (id) => `translate(${stage(id).x + W / 2}px, ${stage(id).y - 10}px)`;

function ends(a, b) {
  // an arrow from box a to box b: between the nearest sides, straight
  const A = stage(a), B = stage(b);
  if (A.y === B.y) return A.x < B.x ? [A.x + W, A.y + H / 2, B.x, B.y + H / 2] : [A.x, A.y + H / 2, B.x + W, B.y + H / 2];
  return A.y < B.y ? [A.x + W / 2, A.y + H, B.x + W / 2, B.y] : [A.x + W / 2, A.y, B.x + W / 2, B.y + H];
}

function diagram() {
  const arrows = FLOW.map(([a, b, label]) => {
    const [x1, y1, x2, y2] = ends(a, b), on = chosen === a || chosen === b;
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, vertical = x1 === x2;
    return `<line class="ex-arrow ${on ? "on" : ""}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" marker-end="url(#ex-head${on ? "-on" : ""})"/>
      ${label ? `<text class="ex-label" x="${vertical ? mx + 8 : mx}" y="${vertical ? my + 4 : my - 8}" text-anchor="${vertical ? "start" : "middle"}">${esc(label)}</text>` : ""}`;
  }).join("");
  const boxes = STAGES.map((s) => `<g class="ex-node ${chosen === s.id ? "sel" : ""}" data-stage="${s.id}" tabindex="0" role="button" aria-label="${esc(s.title)}">
      <rect x="${s.x}" y="${s.y}" width="${W}" height="${H}" rx="10"/>
      <text class="t" x="${s.x + W / 2}" y="${s.y + 26}" text-anchor="middle">${esc(s.title)}</text>
      <text class="s" x="${s.x + W / 2}" y="${s.y + 44}" text-anchor="middle">${esc(s.sub)}</text></g>`).join("");
  return `<svg class="ex-svg" viewBox="0 0 900 350" role="img" aria-label="The FrameEvolve loop">
    <defs>${["", "-on"].map((k) => `<marker id="ex-head${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0L10 5L0 10z" class="ex-head${k}"/></marker>`).join("")}</defs>
    <rect class="ex-loop" x="240" y="36" width="652" height="296" rx="18"/>
    <text class="ex-looplabel" x="570" y="196" text-anchor="middle">the loop: one iteration goes round once</text>
    ${arrows}${boxes}
    <circle class="ex-dot" r="6" cx="0" cy="0" style="transform: ${at(dotAt)}"/>
  </svg>`;
}

function detail() {
  const s = stage(chosen), facts = s.facts();
  return `<div class="ex-detail">
    <h2>${esc(s.title)} <small>${esc(s.sub)}</small></h2>
    <p>${s.text}</p>
    ${s.code ? `<pre class="ex-code">${esc(s.code)}</pre>` : ""}
    ${facts.length ? `<div class="ex-facts">${facts.map(([n, what]) => `<div><b>${esc(n)}</b><span>${esc(what)}</span></div>`).join("")}</div>` : ""}
    <button class="primary" data-go="${s.go[0]}">${esc(s.go[1])}</button>
  </div>`;
}

export function renderExplain() {
  $("#explain").innerHTML = `<div class="ex-wrap">
    <h1>FrameEvolve in one picture</h1>
    <p class="ex-lead">A language model edits a grammar of framing rules. A deterministic verifier scores the frames the
      grammar builds. A search keeps what improves. Timber framing, built as prefab panels, is the case study;
      the loop is the contribution. Click a stage, or play one iteration.</p>
    <div class="ex-tools"><button data-play>${timer ? "&#x23F8; Pause" : "&#x25B6; Play one iteration"}</button></div>
    ${diagram()}${detail()}</div>`;
  dotAt = chosen;
  requestAnimationFrame(() => { const dot = $("#explain .ex-dot"); if (dot) dot.style.transform = at(chosen); });
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
  }, 2600);
  renderExplain();
}

$("#explain").addEventListener("click", (e) => {
  const go = e.target.closest("[data-go]");
  if (go) {
    stop();
    if (go.dataset.go === "editor") showTab("view3d");     // the grammar is in the side panel, beside the 3D view
    return showTab(go.dataset.go);
  }
  if (e.target.closest("[data-play]")) return play();
  const node = e.target.closest("[data-stage]");
  if (node) { stop(); chosen = node.dataset.stage; renderExplain(); }
});
$("#explain").addEventListener("keydown", (e) => {
  const node = e.target.closest("[data-stage]");
  if (node && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); stop(); chosen = node.dataset.stage; renderExplain(); }
});
