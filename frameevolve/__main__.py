"""Command line: python -m frameevolve houses | build | serve"""
from __future__ import annotations

import argparse
from pathlib import Path

from frameevolve import houses
from frameevolve.builder import build
from frameevolve.model import House
from frameevolve.verifier import verify


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
    v.add_argument("--seed-grammar", default="grammars/seed.py")
    v.add_argument("--train", nargs="+", default=[f"data/houses/h{i:03d}.json" for i in range(10)],
                   help="houses the proposer reads reports on")
    v.add_argument("--val", nargs="*", default=[f"data/houses/h{i:03d}.json" for i in range(10, 20)],
                   help="houses that decide the Pareto set and the final grammar; none: use the training houses")
    v.add_argument("--test", nargs="*", default=[], help="houses scored only for the final grammar")
    v.add_argument("--inspirations", type=int, default=2, help="other Pareto grammars shown to the proposer")
    v.add_argument("--minibatch", type=int, default=3)
    v.add_argument("--max-lines", type=int, default=12, help="code lines allowed per grammar function")
    v.add_argument("--iterations", type=int, default=5)
    v.add_argument("--via", choices=["subscription", "api"], default="subscription",
                   help="subscription: Claude Code signed in with a Claude plan; api: an API key or ant profile")
    v.add_argument("--model", default="claude-opus-5-5")
    v.add_argument("--effort", default="medium")
    v.add_argument("--checks", type=int, default=3, help="draft checks the proposer may run per iteration")
    v.add_argument("--no-images", action="store_true", help="proposer reads text only")
    v.add_argument("--dry", action="store_true", help="scripted proposer that changes the stud spacing; no Claude")
    v.add_argument("--seed", type=int, default=0)
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
            image = None
            if a.images:
                from frameevolve import render
                Path(a.images).mkdir(parents=True, exist_ok=True)
                image = str(Path(a.images) / f"{house.id}.png")
                marks = [(f.wall, f.u, f.v, f.check) for f in report.faults if f.hard and f.wall and f.u is not None]
                render.elevations(house, frame, image, marks=marks)
            out[house.id] = {"image": image, "score": list(report.score), "hard": report.hard, "soft": report.soft,
                             "metrics": report.metrics, "text": report.text(),
                             "faults": [{"check": f.check, "hard": f.hard, "wall": f.wall, "u": f.u, "v": f.v,
                                         "message": f.message, "rules": f.rules} for f in report.faults]}
        print(json.dumps(out))
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
