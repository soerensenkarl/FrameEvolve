"""Command line: python -m frameevolve houses | build | evaluate | evolve | serve

houses makes the dataset, build frames houses with a grammar and draws them, evaluate prints a grammar's
reports as JSON (the search runs it in its own process), evolve runs the search, serve opens the workbench.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from frameevolve import houses
from frameevolve.builder import MAX_LINES, build
from frameevolve.model import House
from frameevolve.proposer import DEFAULT_MODEL
from frameevolve.search import INSPIRATIONS, PICTURES, SEED_GRAMMAR
from frameevolve.verifier import verify


def in_faults(report) -> dict:
    """Member id -> True if it is in a hard fault, False if only in soft ones."""
    out = {}
    for f in report.faults:
        for mid in f.members:
            out[mid] = out.get(mid, False) or f.hard
    return out


def pictures(house, frame, report, folder: Path) -> dict:
    """The proposer's pictures of one house, hard faults marked, by name as in search.PICTURES: "image" is the
    elevations, "image3d" the whole frame from two opposite corners. A picture that fails is None; it must
    never fail the evaluation."""
    import sys
    from frameevolve import render
    folder.mkdir(parents=True, exist_ok=True)
    marks = [(f.surface, f.u, f.v, f.check) for f in report.faults if f.hard and f.surface and f.u is not None]
    points = [(*f.at, f.check) for f in report.faults if f.hard and f.at is not None]
    draw = {"image": lambda p: render.elevations(house, frame, p, marks=marks),
            "image3d": lambda p: render.axonometric(house, frame, p, marks=points, views=[(28, -58), (28, 122)],
                                                    by="faults", faults=in_faults(report))}
    out = {}
    for name, suffix in PICTURES.items():
        path = folder / f"{house.id}{suffix}"
        try:
            draw[name](str(path))
            out[name] = str(path)
        except Exception as e:
            print(f"{house.id}: no picture {path.name}: {type(e).__name__}: {e}", file=sys.stderr)
            out[name] = None
    return out


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="frameevolve")
    sub = p.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("houses", help="generate procedural houses")
    h.add_argument("--n", type=int, default=10)
    h.add_argument("--seed", type=int, default=0)
    h.add_argument("--out", default="data/houses")
    b = sub.add_parser("build", help="apply a grammar to houses, save the frames and draw them")
    b.add_argument("grammar")
    b.add_argument("houses", nargs="+")
    b.add_argument("--out", default="out")
    e = sub.add_parser("evaluate", help="build and verify, print JSON (used by the search, one process per grammar)")
    e.add_argument("grammar")
    e.add_argument("houses", nargs="+")
    e.add_argument("--images", help="folder for each house's elevations, hard faults marked")
    v = sub.add_parser("evolve", help="run the search; creates the run folder on first use")
    v.add_argument("run", help="run folder, e.g. runs/gable")
    v.add_argument("--seed-grammar", default=SEED_GRAMMAR)
    v.add_argument("--train", nargs="+", default=[f"data/houses/h{i:03d}.json" for i in range(10)],
                   help="houses the proposer reads reports on")
    v.add_argument("--val", nargs="*", default=[f"data/houses/h{i:03d}.json" for i in range(10, 20)],
                   help="houses that decide the Pareto set and the final grammar; none: use the training houses")
    v.add_argument("--test", nargs="*", default=[], help="houses scored only for the final grammar")
    v.add_argument("--inspirations", type=int, default=INSPIRATIONS, help="other Pareto grammars shown to the proposer")
    v.add_argument("--minibatch", type=int, default=3)
    v.add_argument("--max-lines", type=int, default=MAX_LINES, help="code lines allowed per grammar function")
    v.add_argument("--iterations", type=int, default=5)
    v.add_argument("--via", choices=["subscription", "api"], default="subscription",
                   help="subscription: Claude Code signed in with a Claude plan; api: an API key or ant profile")
    v.add_argument("--model", default=DEFAULT_MODEL)
    v.add_argument("--effort", default="medium")
    v.add_argument("--checks", type=int, default=3, help="draft checks the proposer may run per iteration")
    v.add_argument("--no-images", action="store_true", help="proposer reads text only")
    v.add_argument("--dry", action="store_true", help="scripted proposer that changes the stud spacing; no Claude")
    v.add_argument("--seed", type=int, default=0)
    k = sub.add_parser("look", help="a picture of a grammar's frame on one house, as JSON with the picture's path "
                                    "(the proposer's look tool)")
    k.add_argument("grammar")
    k.add_argument("house")
    k.add_argument("--out", required=True)
    k.add_argument("--view", choices=["3d", "surface"], default="3d")
    k.add_argument("--surface", nargs="*", default=[], help="surfaces to show square on; default: most faults")
    k.add_argument("--colour", choices=["rule", "panel", "faults"], default="rule")
    w = sub.add_parser("serve", help="open the workbench in a browser")
    w.add_argument("--port", type=int, default=8765)
    a = p.parse_args(argv)

    if a.cmd == "evolve":
        import random
        import re
        from frameevolve.proposer import ClaudeCodeProposer, ClaudeProposer, ScriptedProposer
        from frameevolve.search import Run, run_search
        if Path(a.run, "config.json").exists():
            run = Run(Path(a.run))
            print(f"continuing {a.run} at iteration {run.iteration}")
        else:
            run = Run.create(Path(a.run), Path(a.seed_grammar), [Path(h) for h in a.train], a.minibatch,
                             "scripted" if a.dry else a.model, max_lines=a.max_lines, val=[Path(h) for h in a.val],
                             test=[Path(h) for h in a.test], inspirations=a.inspirations)
            print(f"created {a.run}: seed {a.seed_grammar} scores {run.cands[0].total(run.val_ids)} over "
                  f"{len(run.val_ids)} validation houses ({len(a.train)} train, {len(a.test)} test)")
        if a.dry:
            rng = random.Random(a.seed)

            def edit(src, ctx):
                new = rng.choice([12, 16, 19.2, 24])
                out, n = re.subn(r"\b(SPACING = |u \+= )[\d.]+", lambda m: f"{m.group(1)}{new}", src, count=1)
                return out, f"set the stud module to {new} in." if n else "no spacing found"
            proposer = ScriptedProposer(edit)
        else:
            kind = ClaudeCodeProposer if a.via == "subscription" else ClaudeProposer
            proposer = kind(a.model, a.effort, a.checks, images=not a.no_images)
        run_search(run, proposer, a.iterations, a.seed)
    elif a.cmd == "evaluate":
        import json
        out = {}
        for hp in a.houses:
            house = House.load(hp)
            frame = build(a.grammar, house)
            report = verify(house, frame)
            pics = pictures(house, frame, report, Path(a.images)) if a.images else {k: None for k in PICTURES}
            out[house.id] = {"score": list(report.score), "hard": report.hard, "soft": report.soft, **pics,
                             "metrics": report.metrics, "text": report.text(),
                             "faults": [asdict(f) for f in report.faults]}
        print(json.dumps(out))
    elif a.cmd == "look":
        import json
        from frameevolve import render
        house = House.load(a.house)
        frame = build(a.grammar, house)
        report = verify(house, frame)
        hard = [f for f in report.faults if f.hard]
        faults = in_faults(report)
        if a.view == "3d":
            render.axonometric(house, frame, a.out, marks=[(*f.at, f.check) for f in hard if f.at is not None],
                               views=[(28, -58), (28, 122)], by=a.colour, faults=faults)
        else:
            render.elevations(house, frame, a.out, marks=[(f.surface, f.u, f.v, f.check) for f in hard
                                                          if f.surface and f.u is not None], only=a.surface,
                              by=a.colour, faults=faults)
        print(json.dumps({"image": a.out, "score": list(report.score), "errors": frame.errors[:3],
                          "surfaces": [x.id for x in house.surfaces]}))
    elif a.cmd == "serve":
        from frameevolve.server import serve
        serve(a.port)

    elif a.cmd == "houses":
        Path(a.out).mkdir(parents=True, exist_ok=True)
        for i in range(a.seed, a.seed + a.n):
            house = houses.generate(i)
            house.save(Path(a.out) / f"{house.id}.json")
            print(house.id, " ".join(f"{w.id}:{w.length:.0f}/{len(w.openings)}" for w in house.walls))
    elif a.cmd == "build":
        from frameevolve import render
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for hp in a.houses:
            house = House.load(hp)
            frame = build(a.grammar, house)
            frame.save(out / f"{house.id}.frame.json")
            render.elevations(house, frame, out / f"{house.id}.elevations.png")
            render.axonometric(house, frame, out / f"{house.id}.3d.png")
            report = verify(house, frame)
            print(report.text(examples=1), "\n")


if __name__ == "__main__":
    main()
