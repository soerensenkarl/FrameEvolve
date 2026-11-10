# Lab journal

Key decisions, implementation details and what test runs showed. Newest at the bottom. Reasons and the
full design live in DESIGN.md.

## 2026-11-04 Framing

- The contribution is the optimization loop: an LLM proposer edits a grammar, a deterministic verifier
  scores it, a Pareto set keeps the best per house. Timber framing is the case study; the loop should
  carry over to other assemblies of parts with a deterministic verifier.
- Search follows optimize_anything / GEPA: Pareto set over houses, parents weighted by houses won,
  minibatch acceptance, text reports as feedback. Diffs over rewrites, after AlphaEvolve.
- No LLM in the verifier. No GA baseline (unfair to a code-writing search).

## 2026-11-05 Build

- Geometry: members are oriented boxes; contact graph (bears, side, clash) on axis-aligned boxes.
- Units switched from mm to inches so numbers match the IRC tables and the Cambridge code.
- Partitions added. Junctions (corners, tees) are derived from geometry, not stored.
- Backing checked on both faces of every wall. One check now asks for inside-corner studs, partition
  backers and full-depth headers; the soft "thin header" check was deleted as redundant.
- Score is (hard faults, soft faults, cost), compared in that order.
- Builder goes rule by rule; rules declare `match=` and `when=`; each fires once per match; passes repeat
  until nothing changes. Each step records its trigger geometry, so the workbench steps trigger, then output.
- Proposer runs through Claude Code with the Claude subscription (Agent SDK), Opus 5.5 at medium effort.
  The Anthropic API route is kept as an option.

## 2026-11-05 First real run (`runs/first`)

Minimal grammar (plates and studs only), 3 iterations, minibatch 3, 10 training houses.

| | hard | soft | cost, 10 houses |
|---|---|---|---|
| minimal (c000) | 1025 | 47 | 10,475 |
| c001 | 0 | 0 | 21,076 |
| c003 | 0 | 0 | 19,776 |
| seed (hand-written) | 0 | 47 | 17,485 |

- Iteration 1 (3.5 min, 7 turns, 2 checks) rewrote the grammar from 309 hard faults to 0 on its three
  houses, and it held on all 10 training houses and on 10 held-out houses (0 hard, 0 soft).
- Iterations 2 and 3 (35 s and 57 s) cut cost: shallower headers, cripples at 24".
- The proposer read the verifier's header span limits off its fault messages and guessed the rest. It
  learns the verifier's rules from feedback, so the placeholder limits must be right.
- It merged jobs into big rules (top_plates 32 code lines) and replaced corner and partition backers with
  one general rule matched on backing gaps. General, but coarse for credit and reading.
- Decision: a size limit, 12 code lines per grammar function (rules and helpers), checked before
  evaluation; oversized proposals are refused and logged. Seed's largest function is 9 lines.

## 2026-11-05 Rule size, for later

- The 12-line cap is crude (line count depends on style) but simple and working; kept. Alternatives
  (one job per rule, complexity cap, size as cost) go into the planned ablations in DESIGN.md.

## 2026-11-05 Second run (`runs/atomic`): 12-line limit

Minimal grammar, 10 iterations (crashed after 4 on a parent-draw bug, fixed, resumed), minibatch 3.

| | hard | soft | cost, 10 training houses | held-out 10 houses |
|---|---|---|---|---|
| c004 (iteration 4) | 8 | 0 | 19,863 | |
| c010 (iteration 10) | 0 | 0 | 17,938 | 0 hard, 0 soft, 18,012 |
| first run's best | 0 | 0 | 19,776 | 0 hard, 0 soft |
| seed (hand-written) | 0 | 47 | 17,485 | 0 hard, 46 soft |

- All 10 proposals were kept; 20 to 80 s each after the first (3 min). No proposal hit the size limit:
  Claude wrote 17 to 23 small functions, largest 8 lines.
- Under the limit it took 5 iterations to reach zero hard faults (the first run took 1), then kept cutting
  cost: 9% below the first run's best, within 3% of the hand-written seed, with no soft faults.
- Minibatch acceptance lets a child that is better on its 3 houses be worse elsewhere: c001 had 74 hard
  faults over all 10 houses. The Pareto set and later iterations recovered. Worth measuring.
- Bug: the parent was drawn inside a generator, so a fresh random choice was compared with each
  candidate; with two grammars in the Pareto set it could match none and crash. Fixed, with a test.

## 2026-11-05 Advanced platform framing, multi-storey houses

- Houses: 2 or 3 storeys, rectangular plan, a spine partition per storey and cross partitions to it;
  floors on every storey but the top. Walls under a floor reach its top; the grammar decides joist depth.
- Floors are surfaces like walls (u, v in plan, w down), so placement and backing checks work unchanged.
  New match kinds: floor, bearer (wall under a floor), load (wall on a floor).
- Verifier toward advanced framing: a board needs support within 24" in one direction (ladder blocking,
  clips, single headers pass); exterior walls must be 2x6 (R-20 cavity); nailed blocking counts as held;
  floors carry load and joists have span limits; the single-top-plate check is gone.
- Seed rewritten as advanced platform framing (2x6/2x4 at 24" on one grid, single plates, two-stud
  corners and ladder junctions, headers only in bearing walls, 2x12 joists split over the spine):
  0 hard faults on 29 of 30 houses; the 30th has one plate bearing 5/8" on a joist.
- Lesson: a backing check that assumed a wall's face always stops at the wall it meets was wrong where the
  other wall's framing lies beyond; it now uses the same "in the way" test the grammar uses.
- Old runs (first, atomic) were scored on the earlier one-storey houses and 2x4 rules; not comparable.

## 2026-11-05 Plans: L, T, ell and U houses

- Houses are now composed of blocks (box, L, T, ell, U; weighted toward simpler ones), with wings of their own
  storey counts, junction walls where blocks meet, spines only in blocks deeper than 16 ft, and a 3 x 10 ft
  stair opening through every floor. Floors are polygons.
- Seed: rims along any outline, joists clipped to the outline and cut over walls that cross them, stair
  openings with doubled trimmers and headers. Verifier: a joist end butting into a header or rim counts as
  hung (a hanger).
- Seed results on 16 houses: boxes clean; L, T, ell and U houses keep 1 to 5 hard faults, almost all at
  inside corners (the corner details assume outside corners). Left on purpose: a systematic gap the loop
  should find and fix.
- Lesson: collinear walls (an exterior wall continuing past a junction) were treated as meeting, so a
  junction wall did not stop short. Parallel walls no longer meet.
- Tests now take about two minutes; multi-storey houses are slow to build and verify.

## 2026-11-05 Roofs: members at any angle, gable roofs on box houses

- Workbench: Regenerate frames the house from scratch and streams each step's pieces to the 3D view as the
  server places them, at the build's real speed; then shows build and verify times. Rules are numbered.
  A build of a two-storey box house takes about 0.5 s of rule firing and another 0.4 s for a last pass
  that changes nothing (gap matching); verifying takes about 0.5 s.
- Any member can now be cut by planes and notched (`solid.py`: convex pieces, exact clipping). Rules get
  put, cut, trim, notch and overlapping. The contact graph is exact at any angle; contacts keep where they
  are and which way they face. Plain boxes keep the fast path.
- Roof planes are surfaces; seams (ridges) are derived. Box houses get a gable roof, gable walls and a
  ceiling. Other houses keep flat tops until valleys come.
- Seed: rafters at 24" beside the ceiling joists that tie them, a ridge board bevelled to both planes,
  rafters trimmed plumb against it and birdsmouthed over the top plate (notch around the plate and all
  below), gable framing cut along the rafters' underside. The toy house and every box house in h000 to
  h019 frame with no hard faults, except h018's stair trimmer bearing (a floor detail from before).
- Lessons: a fixed raised heel decides rafter depth (a 2x8 at 8/12 cannot reach the plate under a 9" heel,
  so it floated); trimming by "the face the middle is furthest outside of" picked a rafter's side face for
  a stud reaching past it, so trim follows the member's centreline into the other member instead; a
  rafter's heel cut against the plate face looked like a tie, so a tie must be on the rafter's side face;
  locating contacts by bounding-box overlap put a ceiling joist's contact mid-span, so the graph now keeps
  each contact's real centre.

## 2026-11-05 Cleanup

- Deleted the extra houses (only the 20 training houses h000 to h019 remain), old job logs, generated output,
  and the first two runs (`runs/first`, `runs/atomic`): they were on the one-storey houses and no longer
  compare with anything. Their results stay in the entries above.

## 2026-11-05 Search upgrades from GEPA, optimize_anything and AlphaEvolve

Read the three papers in full and compared them with our loop. Ours already is GEPA's core (Pareto set over
instances, parents weighted by wins, minibatch of 3, minibatch acceptance, text feedback); our proposer goes
further than both in checking its own drafts and in faults that name the rule to blame. Took the cheap gains:

- Train, val and test houses. Val picks parents and the final grammar; the proposer reads only train.
- Pareto set drops candidates dominated by another on the front (GEPA Algorithm 2).
- Evaluation cached by content and run one process per core: 20 houses 14 s to 3 s; the parent's reports
  and pictures come from the cache instead of two fresh builds.
- Compile and smoke test before the minibatch. The first dry run caught a 19.2" module raising a TypeError on
  every wall, refused in under 2 s.
- The proposer sees the parent's last rejected children and up to two inspirations from the Pareto set.
- Left for later: rule-level merge (GEPA), parallel proposers and a model mix (AlphaEvolve), code excerpts
  per fault, LLM-graded readability, optimize_anything as a baseline. Workbench still draws its Pareto set
  over training houses.

## 2026-11-05 Roofs on every house

- Every house in the dataset is complete now. L, T and U wings as tall as the main block make cross gables
  with valleys; lower wings and ells get a roof that stops against the main wall. Ceilings turn so their
  joists run with the rafters above (and tie them).
- Seed: rafters follow each plane's outline (jacks run from the valleys), valley rafters grooved to both
  planes (`s.fit`), end framing set in from walls that rise past a roof or ceiling, ceiling joists notched
  around roof framing. Verifier: a jack hanging on a valley needs no tie; valley and hip thrust not checked.
- Seed on h000 to h019: box houses clean, the others 0 to 10 hard faults, 42 in all (before roofs: 1 to 5
  per non-box house). Most are floor and stair details at junctions; a few are sheathing strips at valleys.
- Lessons: a wall "rising past" a roof must be judged where it is inside the roof's outline, not against
  the plane extended; cutting a joist by a rafter's underside plane cut it far away too, so joists are now
  notched (local); the main block should own a junction wall, which also puts a plate under each valley.

## 2026-11-05: New house frames live

- New house now streams like Regenerate: the build stream opens with the house's surfaces, so the view
  shows and frames the new house at once and pieces appear about 25 ms after the click. The house list
  reloads after the build, since a concurrent reload slowed the build (one Python process, one GIL).

## 2026-11-05: Refactor for agents

The project is worked on by agents as much as by me, so it was tidied for them: one name per thing, one
path per job, files an agent can read whole, and a map (CLAUDE.md).
- One build path: `/api/build` streams every build (house surfaces, then each step's pieces, then the
  frame); the page's `build()` is the streaming one, and Regenerate and New house call it.
- `surface` end to end: steps, targets, faults and rule demos name the surface they are on as `surface`;
  "wall" now means only a wall. `State.wall` (an old alias) and `members(wall=)` are gone.
- Three bugs the survey found: a joist hanger counted an ungrounded neighbour as support (an `and`/`or`
  precedence slip); `blocking_under_plate_ends` used a loop variable after the loop; the Runs page totalled
  and ranked candidates over the training houses while the search judges by validation houses.
- Long functions split where they were several things: `verify` into one function per check family,
  `houses.roofs` into planes, gable walls and ceilings, `Run.step` into `context` and `judge`.
- Defaults live in one place each (`DEFAULT_MODEL`, `MAX_LINES`, `INSPIRATIONS`, `SEED_GRAMMAR`);
  `geometry.edges` and `Box.centre` replace copies; shims for keys the server always sends are gone.
- Tests: `conftest.py` builds the seed and minimal frames once per session; overlapping tests merged. The
  core, verifier and roof tests run in 21 s instead of 75.
- The page is split into ES modules by concern (state, 3D view, elevations, inspect, editor, runs), with
  the duplicated SVG, raycast and member-mesh code shared.

## 2026-11-05 night: a verifier for prefab panels, and the first searches on it

Overnight task: run searches, use them to find framework bugs. Along the way the goal changed: frames are to be
built as prefab panels (wall panels, floor cassettes, roof panels) that a shop cuts with an automated saw and a
crane lifts into place bottom up. The verifier grew to judge that, and became a package a person can read.

Verifier (`frameevolve/verifier/`, one module per question, `__init__.py` lists every check in order):
- physical: as before, plus span tables by measured spacing (SPF No. 2; the old floor joist table was for 16"
  and was applied at 24") and rafter ties that must reach across to the opposite slope (3" laps, or butts over
  a bearing). The seed split its ceiling joists over the spine with plain butts.
- analysis (new): a gravity load takedown through the contact graph (simply supported reactions, 99.8 to 100%
  of the load reaches the ground), bending, compression with column stability, crushing across the grain with
  the bearing area factor, deflection; ASCE 7 ASD combinations; NDS values for SPF No. 2. Written by a subagent.
- code (new): IRC prescriptive rules: stud spacing and height by size and load, studs plate to plate, header
  plies and jacks, king studs (soft), bearing walls over the floor below, notches (a birdsmouth at most d/4),
  in-line framing on a single top plate, ridge depth against rafter cut ends, lateral restraint (soft).
- prefab (new): panels flat, one piece, framed along every edge of their outline, at most 40 ft by 11'-6" and
  3,000 lb; pieces a standard automated saw cuts (6" or longer, miter 60, bevel 45, no rips, notches of three
  faces); an erection order bottom up where every unit rests on what is already up and every panel is lowered
  straight down without passing through anything; a soft fault for a surface mostly framed on site.
- cost: site pieces three times a shop piece, and a crane lift per panel.
Builder: guides (`s.guide`, `s.guides`, `s.crossings`; match kinds `house` and `guide`) and panels (`s.assign`).
The seed lays out a 24" grid over the plan first, joints wall panels on it clear of openings (a stud each side of
every joint), builds floors as 8 ft cassettes, and leaves roofs and ceilings to the site.

Bugs found by the runs and by looking: the proposer's elevation picture was 1180 x 14251 px, unreadable once
scaled to send (now the six surfaces with the most faults, two columns, panels outlined); the search's cache key
hashed only `frameevolve/*.py`, so a change in a subpackage would have reused stale scores; a committed worktree
`.venv` symlink replaced the real virtualenv on merge (git treats ignored files as expendable); the seed's panel
joints crashed where no grid line cleared the openings; false positives in rim spans, king studs under floors,
restraint at rim butts, erection cycles between doubled headers, and gable panels judged by "both ends".

Runs (validation totals, hard / soft / cost; all proposals by Opus 5.5 on the subscription):
- r1, r2 (old verifier): 26 hard -> 18 and 20. The loop works; 10 of 12 proposals kept.
- p1 (prefab verifier, 6 its): 3461 / 1085 -> 732 / 77; cost 189k -> 268k (compliance costs timber).
- p2 (with structural analysis, 10 its): 4424 / 1186 -> 626 / 90.
- p3 (from p2's best, 17 good its): 626 -> 538. Every child beats its parent on its minibatch, but
  validation gains shrink: fixes are specific to the training houses (e.g. 46 ft floor cassettes on a deeper
  validation house). The Pareto set grew to 12 grammars.
- p4 (minibatch 4, 10 its): 4424 -> 563 hard, soft up to 1584 (more joists, more restraint warnings).
- Pictures ablation (same seed and minibatches): after one iteration, 1401 -> 728 hard with pictures, 1401 ->
  1012 text only; text only reached 1305 hard on validation after 5. Cut short, see below.
What the proposer found: gable walls split into a wall panel and a gable panel, rafters raised 1/4" to keep the
birdsmouth within d/4, square ridge boards set down (no rip), rafter ties where no ceiling joist ties, double top
plates and 16" layout to satisfy in-line framing and stud tables.
Verifier bugs found from the runs and fixed: rafter ties judged by "opposite slope" failed in valley zones (now:
the tie line must span the house in plan to the far eave); a block held inside its own panel made the panel wait
for a site joist (false erection cycle); a rafter's heel against its own plate counted as lateral restraint;
the Verifier tab listed every module limit under every check.
Stopped at 1 am: the Claude subscription's 5-hour usage limit. Open: the search treats a usage limit as a failed
proposal and burns iterations (it should wait for the reset); a-images and p3 were stopped mid-run.

## 2026-11-06: the proposer at a CAD station; design objectives; panel and assembly views

- Proposer tools try_on (one house in seconds, or a variation of the draft without changing it) and look (a
  picture of the draft or a variation: 3D, or chosen surfaces square on, coloured by rule, panel or faults). In
  the first iteration with them it made 13 tries and 5 pictures before its single full check, and was kept. The
  extra tool rounds hit the 24-turn cap and lost a whole draft: now 60 turns, and running out proposes the draft.
- The proposer's 3D picture shows only the members in faults (hard red, soft amber, the rest a ghost).
- Design objectives (verifier/design.py), as soft faults ranked above cost: fewest panels a truck and a crane allow.
- Saw: an end cut to two planes meeting in an edge (a stud peaked under a valley) is not a saw cut.
- Workbench: a full-width Verifier tab; one view switch in 3D: build, panels (pick one, see it alone with its
  size, weight and faults), assembly (step through the erection order), faults; Rhino mouse; a runs list that
  says what each run is; a timeline that scales to 2,000 steps.
- Open: the search treats a usage limit as a failed proposal; no long run yet on the newest verifier.
- Run notebook (GEPA-style lessons) tried on nb1 (3 iterations from cad1's best): every iteration kept, 440 -> 417
  hard and 359 -> 237 soft on validation. The lessons are specific (wall panels to 40 ft cut most "panels" faults
  but plates then need splices over doubled studs, off the grid lines), and one exposed a verifier bug: the saw's
  bevel was measured as atan(through / along), ignoring the depth component, so every compound cheek cut (a jack
  against a valley) read about 52 degrees. Now asin of the normal's component through the thickness; on h002 54
  cut faults went to 0.
- The proposer reads the frame: the parent's overview of every surface in its prompt, and frame (members of a
  surface with places, contacts and faults), trace (a rule's firings) and raw (the house file, stored members).
- test3 (3 iterations from nb1's best, every tool in): all kept, 271 -> 250 hard on validation. Its lessons found
  three verifier errors, now fixed: a span's end reaction went only to the innermost jack under a header (the
  proposer had turned 2x6s on edge under each ply to get by; now the end reaction is shared by contact area:
  crushing on nb1's best fell from 15 to 2 over five houses); bearing was judged contact by contact, so a plate
  grazing a joist by 1/4" failed (now everything a member rests on at a place counts together, and the
  minimum is for its ends, R502.6); and an opposite rafter met head on was taken for a ridge board too shallow
  (rafters may meet with a gusset, R802.3).

## 2026-11-06: a bare-bones seed

- The seed is now what a framer does first and nothing more (~12 rules): plates, studs every 24" from the
  wall's start, kings, header and sill at openings, rim and joists, ceiling joists, rafters and a ridge, one
  panel per wall and floor. No corners, jacks, cripples, birdsmouths, ties, gables, blocking or grid. The search
  has to find all of that, which makes the loop's contribution visible. On h000-h019 it builds without a rule
  error and starts far from sound: clash 4810, backing 2945, floating 1484, header 1405, in line 1327, strength
  1150, span 790, assembly 720 hard faults.
- The old seed (advanced platform framing as panels) stays as grammars/advanced.py: the verifier tests run on
  its frames, and it is the hand-written baseline the search's grammar is compared against.

## 2026-11-09: the verifier's checks in one table

- The Verifier tab lists every check in one table, grouped under the question its module asks: kind, what it
  finds, its limit (or how many), the code it cites, and its faults on this frame with a bar to compare them.
  A filter shows all, faulted, hard or soft checks. Clicking a question opens its module's description beside
  the table; clicking a check its limits and faults, as before. The project is on GitHub (private,
  soerensenkarl/FrameEvolve) for the group.

## 2026-11-10: forces in the grammar; layout before framing

- Worry: forces are only known once the frame exists, so rules that size by force would have to iterate. They
  do not: loads come from the house and only go down. frameevolve/loads.py takes them down on the bare
  surfaces (roof strips to eave walls, floor strips along the span to bearing lines, walls to the floor they
  stand on, openings gather what is over them to their two sides). On h000-h019 every pound reaches the
  ground, in 15 to 100 ms a house.
- The build has two phases, as Karl put it: an engineer fixes the main force flows (beams, reinforcement),
  then a detailer frames with a notion of the forces. `@layout` rules lay structural guides ("beam", "span")
  and no timber; `@rule` rules frame and may not lay them. A ridge beam laid as a guide on h001 moves half
  the roof from the eave walls to two 10,000 lb points on the gable walls, which then show up as "point"
  matches on those walls, on the floor under them and on the walls below.
- Rules read forces with s.load(u0, u1) on a wall and s.pressure() on a floor or roof; the proposer sees each
  wall's load and points in the frame overview. The seed does not use them yet: finding that is the search's.
- The case that does need order: a point load a wall gathers must be seen by the floor under it. Next step
  is framing top down with each surface analysed once as it is finished, so real reactions replace the
  estimate (forces as rule outputs). Not built yet.
