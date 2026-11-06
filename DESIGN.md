# FrameEvolve design notes

Decisions and the reasons for them. Newest decisions at the bottom of each section.

## Idea

Light timber frames are produced by local rules. We evolve those rules instead of writing them by hand.
An LLM proposer edits a grammar, a deterministic verifier scores the frames the grammar builds, and a
Pareto search keeps the grammars that do well across many houses.

## Vocabulary

- **House**: the input. Labelled surfaces only: walls (later floors and roof planes) with openings.
  Nothing about structure.
- **Member**: one piece of timber.
- **Frame**: the members built for one house.
- **Design state**: the house plus every member placed so far. What rules look at.
- **Rule**: a function that looks at the design state and places or removes members. Has a priority.
- **Grammar**: a set of rules, in one Python file. The evolved artifact.
- **Builder**: applies a grammar to a house until nothing changes.
- **Graph**: the contacts in a frame: what bears on what, what touches side to side, what clashes.
- **Verifier**: deterministic, no LLM. Turns a frame into a report.
- **Report**: scores, located faults with the rules that caused them, summary text, pictures.
- **Proposer**: the LLM that reads reports and edits the grammar.
- **Pareto set**: the grammars that are best on at least one house.

## Project

- Small and tidy: delete rather than keep dead code. References (codes, guides, papers) live in
  `references/`, outside version control because they are copyrighted.

## Geometry

- Inches, z up, ground at z = 0. Reason: the numbers then match the IRC tables and the Cambridge (MA)
  code directly. Reports write lengths as feet and inches.
- A member is an oriented box (centreline start and end, a section, an up vector for the direction its
  depth faces), trimmed by cut planes, less notches (convex regions). Any member, at any angle. Reason:
  every framing member is a box with cut ends and notches, so the representation is exact and small, and
  an LLM can read it. No meshes or NURBS in the core.
- A cut member's solid is kept as convex pieces (a box clipped by its cuts, split around each notch), so
  overlap volumes and contact areas between any two members are exact, by clipping (`solid.py`). Plain
  axis-aligned boxes keep the fast box path. A notch turns an overlap into a joint: a birdsmouth over a
  plate becomes a seat that bears on it.
- Section inventory: 2x4 to 2x12 by nominal name, at actual sizes (1 1/2" x 3 1/2" to 11 1/4").
  Stock lengths 8 to 20 ft.

## Walls

- A wall is a vertical surface; its framing lies to the left of start to end. For an exterior wall the
  surface is the outer face (footprints are counter-clockwise, so left is inward). A partition is the same:
  one face, framing to its left, drawn from one exterior wall's outer face to another's.
- Local coordinates: u along the wall from its start, v up from its base, w into the framing.
- Junctions are derived from the geometry, never stored: an end on another wall's end is a corner, an end
  along another wall is a T (the host wall lists it in `tees`).
- Rules choose depth and where framing stops at corners and Ts. The house says nothing about them.

## Builder

- A rule declares what it matches and when: `@rule(priority, match="opening", when=...)`. Match kinds:
  house (once), guide, wall, floor (and ceiling), roof, seam (where two roof planes meet), opening, corner,
  tee, bearer, load, gap (a stretch of face with no backing), member.
- Guides: lines a rule lays out to frame by, not timber (`s.guide`): a grid over the plan, panel joints.
  Later rules read them (`s.guides`, `s.crossings`: where they cross the current surface) or match them.
  Reason: framers lay out from a global grid and mark where panels break before cutting anything; making
  that a step of its own puts the layout in one readable rule instead of arithmetic repeated in many.
- Prefab panels: `s.assign(m, panel)` builds a member into a named panel (a wall panel, a floor cassette,
  a roof panel); members without one are built on site. The verifier checks the panels and charges site
  work and crane lifts. Reason: the frames are meant to be prefabricated as flat panels, trucked and lifted.
- A rule acts through `s`: place (by a rectangle on the current surface), put (a centreline at any angle),
  cut (by a plane), trim (back to the face of another member it runs into), notch (around another member,
  optionally everything under it too: a seat cut), remove. Reason: these are the carpenter's operations; a
  cut or notch is a property of the member, so a joint is exact and readable.
- The builder goes rule by rule in priority order. For each rule it lists every match of its kind in the
  current design state and fires the rule once per match whose condition holds. Passes repeat until a
  pass changes nothing (cap 10), so a condition that becomes true later still fires.
- Reason: rule by rule keeps the coarse-to-fine order; declared matches make the trigger visible (what,
  where, how often), give exact before/after rule diagrams, and give credit to (rule, match). This is
  the shape-grammar and CGA idea of an explicit left-hand side, with priority-ordered sweeps.
- Every member records the rule that placed it; every step records the rule, the match and its geometry.
- `role` on a member is a free label for reading. The verifier never trusts it.

## Graph

- The frame's contact graph is the main representation for reasoning, for both rules and proposer.
  Reason: rules should ask framing questions ("what does this header bear on") rather than search
  coordinates within a tolerance; and LLMs reason well about relations, badly about raw coordinates.
- Edges: bears (a face resting on another, closer to level than plumb, with area), side (faces touching
  otherwise, with area and direction), clash (solids overlap). Every contact keeps where it is. The ground
  is a node.
- Held up: a chain of bearing to the ground, or nailed between held members on opposite faces (blocking
  between studs, a ridge board between rafters). Upright members must bear.

## Verifier

- A package read in order (`frameevolve/verifier/__init__.py` lists every check), one module per question,
  each opening with what it checks in plain words and its limits at the top, each citing its source:
  - `physical.py`, can it stand: rule errors, stock length, openings, clashes, support down to the ground,
    spans and bearing by the IRC tables (Spruce-Pine-Fir No. 2, by spacing: a member's spacing is measured to
    its neighbours), rafters' level span (50 psf snow table, the one above Cambridge's 40) and a tie in the
    lower third that reaches across to the rafters on the other slope (lapped 3", or butted over a bearing).
  - `analysis.py`, will it hold: a simple gravity structural analysis. Area loads on floors, ceilings and
    roofs; taken down through the contact graph as simply supported reactions; bending, compression with
    column stability, bearing across the grain and deflection against NDS values for SPF No. 2.
  - `boards.py`: backing for every board, heads and sills, room for R-20 insulation.
  - `code.py`, the IRC's prescriptive rules: stud spacing and height by size and load (Table R602.3(5)),
    studs in one piece plate to plate, headers by plies with their jacks (Table R602.7(1)) and kings
    (Table R602.7.5, soft), bearing walls over the floor below within the joist depth (R502.4), notches
    (R502.8.1, R802.7.1: a birdsmouth at most a quarter of the depth), in-line framing on a single top plate
    (R602.3.2), ridges, hips and valleys as deep as the rafter cut ends (R802.3), lateral restraint (soft).
  - `prefab.py`, can it be built: panels flat on one surface, one piece, framed at both ends, at most 40 ft
    by 11'-6" (a drop-deck trailer) and 3,000 lb (a boom truck); pieces a standard automated saw cuts
    (6" or longer, miter to 60 degrees, bevel to 45, no rips, notches of up to three faces); and an erection
    order, bottom up, where everything rests on what is already up and every panel is lowered straight down
    without passing through anything already up.
  - `cost.py`: timber bought in stock lengths, a cost per piece (three times as much on site as in a
    panel), and a crane lift per panel.
- Checks read geometry and the contact graph, never role labels. Hard faults: unbuildable or unsafe.
  Soft: details a good grammar also gets right.
- Every fault carries where it is (surface, u, v, world point), the members involved, and the rules that
  placed them. A missing member has no rule to blame, and the report says so.
- Score per house: (hard faults, soft faults, cost), compared in that order. Reason: with soft faults
  outside the score, the search would never spend timber to fix a single top plate.
- The report also comes as text, which is what the proposer reads, with two pictures: the frame in 3D, and
  the six surfaces with the most faults, panels outlined.

## Build history

- The builder records every rule firing that changed something, in order: the rule, the match, where
  the match is, and the members placed and removed. Removed members are kept so the build can be
  replayed, trigger then output.
- Reason: to see how a grammar builds a frame, step by step, not only the result.

## Search

- optimize_anything / GEPA style. Houses come in three sets: train (the proposer reads reports on these;
  minibatches come from them), val (decides the Pareto set, the parents and the final grammar; its reports
  are never shown) and test (scored only for the final grammar, into `test.json`). Default: h000-h009
  train, h010-h019 val, no test. Reason: with one set, a result cannot be told from overfitting (GEPA
  keeps its feedback and Pareto sets apart). A run without val uses train for both, as the first runs did.
- A pool of grammars, each scored on every training and validation house. The Pareto set is every grammar
  that is best on at least one validation house, less those dominated by another such grammar (GEPA,
  Algorithm 2), so near-copies do not crowd the draw. A parent is drawn from it, weighted by the number of
  houses it wins. The final grammar is the best total over validation.
- Each iteration takes a minibatch of training houses (default 3). The proposer sees the parent on
  those houses and returns a child. The child is kept only if its summed score on the minibatch beats
  the parent's; then it is scored on every training and validation house and joins the pool.
- Cheap checks first (AlphaEvolve's evaluation cascade): a child must compile and pass the size limit, then
  a smoke test on the smallest minibatch house refuses it if it crashes or raises more rule errors than the
  parent there. That build is cached, so a child that passes costs nothing extra.
- A size limit keeps rules atomic: no function in a grammar may exceed the run's `max_lines` code lines
  (default 12; docstrings, blanks and comments do not count). An oversized proposal is refused before it
  is evaluated, and the proposer's check tool reports it. Reason: the first real run merged jobs into
  32-line rules; small rules read better, give finer credit, and step more clearly.
- Grammars are evaluated in separate processes with a timeout, since a proposed grammar is code no
  person has read. A crash or timeout scores as failed. Houses are split over one process per core
  (20 houses: 14 s to 3 s). Results and elevations are cached in `runs/<name>/cache/` by a hash of the
  grammar, the house and the framework's code (optimize_anything), so a parent is never built twice and a
  change to the builder or verifier never reuses old results. Failures are not cached.
- Everything goes to `runs/<name>/`: config, candidates, grammars, one line per iteration, and per
  iteration what the proposer saw and did. The run folder is the truth; the workbench reads it.
- `uv run python -m frameevolve evolve runs/<name> --iterations N` creates or continues a run.
  `--dry` uses a scripted proposer instead of Claude, for testing.

## Proposer

- A Claude agent (default `claude-opus-5-5`, effort medium). Two ways in, same prompt and tools: Claude Code
  through the Claude Agent SDK, signed in with a Claude subscription (the default, `--via subscription`),
  or the Anthropic API's tool runner (`--via api`).
- It sees: the parent grammar, the parent's scores on every training house, the verifier's text reports
  on the minibatch, and two pictures per minibatch house with hard faults marked: the whole frame in 3D
  from two opposite corners (roofs and floors are hard to judge from elevations), then the wall and roof
  elevations. A picture that fails to draw is left out; it never fails the evaluation.
- It also sees the last three children of this parent that were not kept, with why and their notes, so it
  does not repeat them; and up to two inspirations (AlphaEvolve): other grammars in the Pareto set that beat
  the parent on the most validation houses, with their code, notes and training scores. `--inspirations 0`
  turns them off, for an ablation.
- Its tools: view the draft, replace one exact piece of text, replace the whole file; try_on (build and verify
  the draft, or a variation of it with one replacement, on one house in seconds, against the parent's score
  there; 16 per proposal); look (a picture of the draft or a variation on one house: the whole frame in 3D, or
  chosen walls, floors and roofs square on, coloured by rule or by panel, hard faults marked; 8 per proposal);
  and check the draft on the whole minibatch (a limited number of times, default 3). Reason: a designer at a
  CAD station tries variations and looks at them before committing; a frame can score well and look wrong. It ends with a note saying what it
  changed and why; the note is kept with the candidate.
- The rules API it is told about is generated from the builder's own signatures and docstrings, so it
  cannot drift from the code.
- Server-side refusal fallbacks are on (`fallbacks: "default"`); `ClaudeProposer(fallbacks=False)`
  turns them off.
- Credentials: the subscription needs Claude Code signed in (found on the path, at CLAUDE_CLI, or inside the
  Claude desktop app). The API needs an `ANTHROPIC_API_KEY` or an `ant auth login` profile.

## Houses

- Complete houses of varying complexity, composed of rectangular blocks: a box, an L, a T, a colonial ell
  (a lower wing to one side) or a U, two or three storeys, wings with their own storey counts.
- Exterior walls trace the outline of the blocks reaching each storey, split where one block meets another;
  junction walls stand where two blocks meet inside. Deep blocks get a spine; the main block gets cross
  partitions; one stair opening goes through every floor. Openings are placed last, clear of junctions.
- Floors are polygons (the outline of the blocks above). Every surface has an outline in its own u, v, and
  the backing check scans that outline, so floors of any shape and later gable walls work the same way.
- Walls that continue in the same line do not "meet" each other; only crossing walls make corners and Ts.
- Roofs are surfaces like walls and floors: a roof plane is the top of its rafters, u along the eave, v up
  the slope, w square into the framing; its outline is any polygon in its plane. Where two planes share (part
  of) an edge they make a seam: a ridge, a hip or a valley, derived like corners. Every house is complete:
  each block gets a gable roof (9" raised heel, 12" eave overhang, pitch 6 to 12 in 12 so rafters fit 20 ft
  stock), gable walls at its free ends (balloon framed, outline up to the roof) and a ceiling on its top
  storey (a floor with role "ceiling", framing above its underside, turned so its joists run with the
  rafters). The main ridge runs along x; a wing's ridge runs away from the main block. A wing as tall as the
  main block meets its roof in valleys (the main back plane gives way under the wing's planes: the true upper
  envelope); a lower wing's roof stops against the main wall, pitched to stay under the main eave. The taller
  block (or the main block) owns the junction wall, as the wall that rises past the other.
- Next: hips, sheds and dormers; then angled bays, turrets and porches. See the reference photos in
  `reference_houses/`.

## Scope now

- Houses: two or three storeys; box, L, T, ell and U plans; partitions, stairs, doors and windows; gable
  roofs on box houses. Twenty training houses, h000 to h019 in `data/houses`.
- Verifier: a simplified placeholder of the codes (support, clashes, backing, spans, thrust, cost).
- Search: Pareto set over houses with a Claude proposer. No run yet on the current houses; the first two
  runs (one-storey houses) are summarised in the journal and were deleted.

## Workbench

- The main place to look at and work on the project: `uv run python -m frameevolve serve`, then
  http://localhost:8765. Standard library server; one page of ES modules (one per concern, see CLAUDE.md)
  with Three.js from a CDN. Every build streams: the house's surfaces first, then each step's pieces as the
  builder places them, then the frame with its verification; the page draws pieces as they arrive.
- Shows a house built by a grammar in 3D and as wall elevations, the rules with their member counts,
  a member's contacts from the graph, the faults, the builder log, and an editor for the grammar.
  Builds use unsaved edits, so a rule can be tried before it is saved.
- Reason: the project is spatial, and both of us need to see a frame and its graph, not read it.

## Planned ablations

Each varies one thing in the loop, same houses, same budget; compare learning curves, held-out scores and
the readability of the final grammar.

- Rule size: no limit; code lines per function (current, 12); one job per rule (one role per firing,
  scored as a soft fault); a complexity cap; grammar size as a last tiebreak in the score.
- Feedback: text reports only; text plus elevations (current); plus the contact graph around faults.
- Proposer: Opus vs Sonnet vs Haiku; effort low, medium, high; draft checks 0 vs 3.
- Selection: Pareto set (current) vs greedy best.
- Start: minimal grammar vs hand-written seed.
- Baseline: a frontier model framing each house directly, zero-shot, scored by the same verifier.
