# FrameEvolve: how to work here

An LLM proposer edits a grammar of framing rules, a deterministic verifier scores the frames it builds, and a
Pareto search over houses keeps what improves. The frames are meant to be built as prefab panels: wall panels,
floor cassettes and roof panels, cut by an automated saw, trucked and lifted into place bottom up. Timber framing is the case study; the loop is the contribution.
DESIGN.md holds the design and its reasons; JOURNAL.md is the lab journal (add to it when you decide, build or
learn something). Imperial units, inches in code.

## Map

| Where | What |
|---|---|
| `frameevolve/model.py` | House, Wall, Floor, Roof (surfaces with local u, v, w axes), Member (a box, cut and notched), Frame |
| `frameevolve/geometry.py`, `solid.py` | vectors, boxes, polygons; members at any angle as convex pieces, exact overlap and contact |
| `frameevolve/graph.py` | the contact graph: bears, side, clashes, grounded |
| `frameevolve/surface.py` | backing: where a face's boards have nothing behind them; outlines of members on a surface |
| `frameevolve/loads.py` | the load takedown on the house's surfaces, before any member: what lands on each wall, floor and beam; structural guides (beam, span) change it |
| `frameevolve/builder.py` | `@rule(priority, match, when)`, `State` (what rules see and do: place, cut, notch, guide, assign to a panel, read loads), `build()`; the docstring lists match kinds |
| `frameevolve/verifier/` | `verify(house, frame) -> Report`; one module per question (physical, analysis, boards, code, prefab, cost), read in the order `__init__.py` lists |
| `frameevolve/houses.py` | procedural houses: blocks, storeys, openings, stairs, roofs; `generate(seed)`, `toy()` |
| `frameevolve/render.py` | elevations and an axonometric as PNGs, for the proposer |
| `frameevolve/search.py` | the GEPA-style search: `Run`, `evaluate` (separate processes, cached), Pareto set |
| `frameevolve/proposer.py` | the Claude proposer (Agent SDK on the subscription, or the API) and its tools |
| `frameevolve/jobs.py` | background jobs the workbench starts (a search, the tests, scoring) |
| `frameevolve/server.py` | the workbench's JSON API; builds stream as NDJSON (`/api/build`) |
| `web/` | the workbench page as ES modules: `app.js` (entry: build, stats, rules, tabs), `state.js` (shared state, units, api), `view3d.js`, `elevations.js`, `inspect.js` (inspector, verifier, timeline), `editor.js`, `runs.js`, `live.js` |
| `grammars/seed.py` | the bare-bones seed a search starts from; `advanced.py` a hand-written reference frame (tests, comparison); `minimal.py` a bad one for tests |
| `data/houses/` | the dataset, h000–h019; `runs/` search runs; `jobs/` job logs |
| `tests/` | pytest; `conftest.py` has session-scoped frames |

## Conventions

- One word per thing: a *surface* is a wall, floor, ceiling or roof plane; a *wall* is only a wall. Steps,
  targets and faults name their surface as `surface`.
- Small and tidy: delete rather than keep dead code; no compatibility shims; one way to do each thing.
- Docstrings say what and why in a sentence or two. Comments explain a choice, not the code.
- Limits at the top of each `verifier/` module and `surface.py` carry the code reference in the comment beside them; the
  workbench reads those comments.
- `references/` (codes, papers) and `reference_houses/` stay out of git.

## Run

```bash
uv run pytest -q                       # ~3 min; the search tests build real houses
uv run python -m frameevolve serve     # the workbench at http://localhost:8765 (restart it after editing Python)
uv run python -m frameevolve evolve runs/<name> --iterations 5   # a search
```

The workbench is the place to look at a frame: 3D, elevations, the build step by step, faults with evidence.
Builds use unsaved grammar edits, so a rule can be tried before it is saved.

## Commits

Author `Karl Sorensen <soerensenkarl@gmail.com>`; end the message with
`Co-Authored-By: Claude <noreply@anthropic.com>` naming the model that did the work.
