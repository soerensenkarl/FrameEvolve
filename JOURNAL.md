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
