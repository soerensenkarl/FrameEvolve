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
  wall, floor (and ceiling), roof, seam (where two roof planes meet), opening, corner, tee, bearer, load,
  gap (a stretch of face with no backing), member.
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

- A placeholder for the codes: simplified readings of IRC chapter 6 and the WFCM, with limits marked
  as placeholders in `verifier.py` until each is checked against the tables.
- Hard faults (unbuildable): rule error, too long, opening, clash, floating, span, overhang, bearing,
  backing, head, sill, insulation, thrust.
- Backing is checked on every boarded face: sheathing and drywall on walls, subfloor and ceiling on floors,
  the ceiling under a roof, roof sheathing. A face's boards stop where another wall's framing meets it,
  or where any framing passes through it, so those edges need backing too. Members square to the surface
  back it by their boxes; anything else by where it is cut by the face, so a sloped rafter backs only the
  strip it covers.
- Rafters: level span between what they rest on and the ridge they butt (IRC rafter table, 40 psf ground
  snow for Cambridge); a tie (something level nailed to the rafter's side in the lower third of its rise)
  unless the rafter also rests on something high up (a gable wall, a beam). Tie continuity across the
  house (lapped or spliced joists) is not checked yet. Ceiling joists have their own span table.
- Every fault carries where it is (wall, u, v, world point), the members involved, and the rules that
  placed them. A missing member has no rule to blame, and the report says so.
- Score per house: (hard faults, soft faults, cost), compared in that order. Reason: with soft faults
  outside the score, the search would never spend timber to fix a single top plate. Cost is timber bought (first fit decreasing into stock lengths,
  deeper sections weighted by depth) plus a fixed cost per piece.
- The report also comes as text, which is what the proposer will read.

## Build history

- The builder records every rule firing that changed something, in order: the rule, the match, where
  the match is, and the members placed and removed. Removed members are kept so the build can be
  replayed, trigger then output.
- Reason: to see how a grammar builds a frame, step by step, not only the result.

## Search

- optimize_anything / GEPA style. A pool of grammars, each scored on every training house. The Pareto
  set is every grammar that is best on at least one house. A parent is drawn from it, weighted by the
  number of houses it wins.
- Each iteration takes a minibatch of training houses (default 3). The proposer sees the parent on
  those houses and returns a child. The child is kept only if its summed score on the minibatch beats
  the parent's; then it is scored on every training house and joins the pool.
- A size limit keeps rules atomic: no function in a grammar may exceed the run's `max_lines` code lines
  (default 12; docstrings, blanks and comments do not count). An oversized proposal is refused before it
  is evaluated, and the proposer's check tool reports it. Reason: the first real run merged jobs into
  32-line rules; small rules read better, give finer credit, and step more clearly.
- Grammars are evaluated in a separate process with a timeout, since a proposed grammar is code no
  person has read. A crash or timeout scores as failed.
- Everything goes to `runs/<name>/`: config, candidates, grammars, one line per iteration, and per
  iteration what the proposer saw and did. The run folder is the truth; the workbench reads it.
- `uv run python -m frameevolve evolve runs/<name> --iterations N` creates or continues a run.
  `--dry` uses a scripted proposer instead of Claude, for testing.

## Proposer

- A Claude agent (default `claude-opus-5-5`, effort medium). Two ways in, same prompt and tools: Claude Code
  through the Claude Agent SDK, signed in with a Claude subscription (the default, `--via subscription`),
  or the Anthropic API's tool runner (`--via api`).
- It sees: the parent grammar, the parent's scores on every training house, the verifier's text reports
  on the minibatch, and one elevation picture per minibatch house with hard faults marked.
- Its tools: view the draft, replace one exact piece of text, replace the whole file, and check the
  draft on the minibatch (a limited number of times, default 3). It ends with a note saying what it
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
  the slope, w square into the framing; its outline is any polygon in its plane. Where two planes share an
  edge they make a seam (ridge or hip), derived like corners. A box house gets a gable roof: two planes,
  a 9" raised heel, a 12" eave overhang, a pitch from 6 to 12 in 12 chosen so rafters fit 20 ft stock;
  its end walls become gable walls whose outline reaches up to the roof planes (balloon framed); and a
  ceiling (a floor with role "ceiling", framing above its underside) sits on the top storey's walls.
- Next: roofs over L, T, ell and U houses (planes clipped where they meet, valleys), hips, sheds and
  dormers; then angled bays, turrets and porches. See the reference photos in `reference_houses/`.

## Scope now

- Houses: two or three storeys; box, L, T, ell and U plans; partitions, stairs, doors and windows; gable
  roofs on box houses. Twenty training houses, h000 to h019 in `data/houses`.
- Verifier: a simplified placeholder of the codes (support, clashes, backing, spans, thrust, cost).
- Search: Pareto set over houses with a Claude proposer. No run yet on the current houses; the first two
  runs (one-storey houses) are summarised in the journal and were deleted.

## Workbench

- The main place to look at and work on the project: `uv run python -m frameevolve serve`, then
  http://localhost:8765. Standard library server, one page with Three.js from a CDN.
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
