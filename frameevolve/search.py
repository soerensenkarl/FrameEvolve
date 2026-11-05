"""The search: evolve a grammar against the verifier, keeping a Pareto set over houses.

One iteration:
  1. Pick a parent from the Pareto set, weighted by the number of houses it is best on.
  2. Take a minibatch of training houses; build and verify the parent on them.
  3. The proposer reads the parent, its reports and pictures, and returns an edited grammar.
  4. Refuse the child if any function in it is longer than the run's line limit, so rules stay small.
     Otherwise build and verify it on the same minibatch, and keep it only if it beats the parent there.
  5. If kept, evaluate it on every training house and add it to the pool.

A grammar is the best on a house when no other grammar has a better score there. Scores are compared as
(hard faults, soft faults, cost). Grammars run in a separate process with a timeout, because a proposed
grammar is code that no person has read.

Everything is written to a run folder, which the workbench reads:
  runs/<name>/config.json        what was asked for
  runs/<name>/candidates.jsonl   one line per kept grammar: id, parent, scores per house, note
  runs/<name>/grammars/<id>.py   the grammars
  runs/<name>/iterations.jsonl   one line per iteration, kept or not
  runs/<name>/proposals/<n>/     what the proposer saw and did in iteration n; live.jsonl streams its actions
                                 as they happen and draft.py holds its current draft
  runs/<name>/live.json          what the search is doing right now (stage, iteration, parent, houses)
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from frameevolve import render
from frameevolve.builder import MAX_LINES, build, too_big
from frameevolve.model import House
from frameevolve.verifier import verify

ROOT = Path(__file__).resolve().parents[1]
FAILED = [10**6, 10**6, 1e12]   # the score of a grammar that crashed or timed out


@dataclass
class Candidate:
    id: str
    parent: str | None
    iteration: int
    scores: dict[str, list]              # house id: [hard, soft, cost]
    note: str = ""
    created: float = field(default_factory=time.time)

    def total(self, houses=None) -> list:
        hs = houses or list(self.scores)
        return [sum(self.scores[h][0] for h in hs), sum(self.scores[h][1] for h in hs),
                round(sum(self.scores[h][2] for h in hs), 2)]


def evaluate(grammar: Path, houses: list[Path], timeout: float = 120) -> dict:
    """Build and verify a grammar on houses in a separate process. Returns {house id: result}."""
    try:
        p = subprocess.run([sys.executable, "-m", "frameevolve", "evaluate", str(grammar), *map(str, houses)],
                           cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        if p.returncode == 0:
            return json.loads(p.stdout)
        why = (p.stderr.strip().splitlines() or ["no output"])[-1]
    except subprocess.TimeoutExpired:
        why = f"timed out after {timeout:.0f} s"
    return {House.load(h).id: {"score": FAILED, "hard": FAILED[0], "soft": 0, "text": f"Evaluation failed: {why}",
                               "faults": [], "metrics": {}} for h in houses}


def pareto(cands: list[Candidate], houses: list[str]) -> dict[str, list[str]]:
    """For every candidate in the Pareto set, the houses it is best on (ties all count)."""
    wins: dict[str, list[str]] = {}
    for h in houses:
        best = min(c.scores[h] for c in cands)
        for c in cands:
            if c.scores[h] == best:
                wins.setdefault(c.id, []).append(h)
    return wins


def better(a: list, b: list) -> bool:
    return tuple(a) < tuple(b)


class Run:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.config = json.loads((self.path / "config.json").read_text())
        self.cands: list[Candidate] = []
        f = self.path / "candidates.jsonl"
        if f.exists():
            self.cands = [Candidate(**json.loads(l)) for l in f.read_text().splitlines() if l.strip()]
        self.iteration = 0
        f = self.path / "iterations.jsonl"
        if f.exists():
            self.iteration = sum(1 for l in f.read_text().splitlines() if l.strip())

    @staticmethod
    def create(path: Path, seed_grammar: Path, train: list[Path], minibatch: int, model: str, note: str = "",
               max_lines: int = MAX_LINES) -> "Run":
        path = Path(path)
        (path / "grammars").mkdir(parents=True, exist_ok=False)
        config = {"seed_grammar": str(seed_grammar), "train": [str(h) for h in train], "minibatch": minibatch,
                  "model": model, "max_lines": max_lines, "note": note, "created": time.time()}
        (path / "config.json").write_text(json.dumps(config, indent=1))
        run = Run(path)
        src = Path(seed_grammar).read_text()
        (path / "grammars" / "c000.py").write_text(src)
        res = evaluate(path / "grammars" / "c000.py", run.train)
        run.add(Candidate("c000", None, 0, {h: r["score"] for h, r in res.items()}, f"seed: {Path(seed_grammar).name}"))
        return run

    @property
    def max_lines(self) -> int:
        return self.config.get("max_lines", MAX_LINES)

    @property
    def train(self) -> list[Path]:
        return [Path(h) for h in self.config["train"]]

    @property
    def house_ids(self) -> list[str]:
        return [House.load(h).id for h in self.train]

    def grammar(self, cid: str) -> Path:
        return self.path / "grammars" / f"{cid}.py"

    def add(self, c: Candidate) -> None:
        self.cands.append(c)
        with open(self.path / "candidates.jsonl", "a") as f:
            f.write(json.dumps(asdict(c)) + "\n")

    def log(self, entry: dict) -> None:
        with open(self.path / "iterations.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

    def stage(self, stage: str, **info) -> None:
        """Say what the search is doing now, for anyone watching (the workbench)."""
        (self.path / "live.json").write_text(json.dumps({"stage": stage, "time": time.time(), **info}))

    def pareto(self) -> dict[str, list[str]]:
        return pareto(self.cands, self.house_ids)

    def best(self) -> Candidate:
        return min(self.cands, key=lambda c: c.total())

    def step(self, proposer, rng: random.Random) -> dict:
        """One iteration. Returns the logged entry."""
        self.iteration += 1
        it = self.iteration
        t0 = time.time()
        wins = self.pareto()
        ids = list(wins)
        pick = rng.choices(ids, weights=[len(wins[i]) for i in ids])[0]
        parent = next(c for c in self.cands if c.id == pick)
        k = min(self.config["minibatch"], len(self.train))
        batch = rng.sample(self.train, k)
        batch_ids = [House.load(h).id for h in batch]
        out = self.path / "proposals" / f"{it:04d}"
        out.mkdir(parents=True, exist_ok=True)

        now = {"iteration": it, "parent": parent.id, "houses": batch_ids, "proposal": out.name, "started": t0}
        self.stage("reading the parent", **now)
        # what the proposer sees: the parent's reports and elevations on the minibatch
        parent_src = self.grammar(parent.id).read_text()
        parent_res = evaluate(self.grammar(parent.id), batch)
        images = []
        for hp in batch:
            house = House.load(hp)
            frame = build(self.grammar(parent.id), house)
            report = verify(house, frame)
            marks = [(f.wall, f.u, f.v, f.check) for f in report.faults if f.hard and f.wall and f.u is not None]
            img = out / f"{house.id}.png"
            render.elevations(house, frame, img, marks=marks)
            images.append(img)
        parent_batch = [round(sum(parent_res[h]["score"][j] for h in batch_ids), 2) for j in range(3)]
        context = {
            "iteration": it, "parent": parent.id, "houses": batch_ids, "house_paths": [str(h) for h in batch],
            "parent_batch": parent_batch, "max_lines": self.max_lines,
            "reports": {h: parent_res[h]["text"] for h in batch_ids},
            "parent_scores": parent.scores, "images": [str(p) for p in images],
            "pareto": {cid: hs for cid, hs in wins.items()},
        }
        entry = {"iteration": it, "parent": parent.id, "batch": batch_ids, "accepted": False, "child": None,
                 "parent_batch": None, "child_batch": None, "note": "", "error": None}
        entry["parent_batch"] = parent_batch
        self.stage("proposing", **now)
        try:
            proposal = proposer.propose(parent_src, context, out)
        except Exception as e:
            entry["error"] = f"proposer failed: {type(e).__name__}: {e}"
            entry["seconds"] = round(time.time() - t0, 1)
            self.log(entry)
            self.stage("between iterations", **now, accepted=False, child=None)
            return entry
        entry["note"] = proposal.note
        entry["usage"] = proposal.usage
        (out / "proposed.py").write_text(proposal.source)
        big = too_big(proposal.source, self.max_lines)
        if proposal.source.strip() == parent_src.strip():
            entry["error"] = "the proposal did not change the grammar"
        elif big:
            entry["error"] = "too big: " + " ".join(big)
        else:
            self.stage("testing the proposal", **now)
            child_res = evaluate(out / "proposed.py", batch)
            child_batch = [round(sum(child_res[h]["score"][j] for h in batch_ids), 2) for j in range(3)]
            entry["child_batch"] = child_batch
            if better(child_batch, parent_batch):
                cid = f"c{len(self.cands):03d}"
                self.stage("scoring on every house", **now, child=cid)
                self.grammar(cid).write_text(proposal.source)
                full = evaluate(self.grammar(cid), self.train)
                self.add(Candidate(cid, parent.id, it, {h: r["score"] for h, r in full.items()}, proposal.note))
                entry["accepted"], entry["child"] = True, cid
        entry["seconds"] = round(time.time() - t0, 1)
        self.log(entry)
        self.stage("between iterations", **now, accepted=entry["accepted"], child=entry["child"])
        return entry


def run_search(run: Run, proposer, iterations: int, seed: int = 0, say=None) -> None:
    """Run iterations. A file named STOP in the run folder ends the search after the current iteration."""
    say = say or (lambda *a, **k: print(*a, **{"flush": True, **k}))
    rng = random.Random(seed + run.iteration)
    stop = run.path / "STOP"
    stop.unlink(missing_ok=True)
    for _ in range(iterations):
        if stop.exists():
            stop.unlink()
            say("stopped on request")
            break
        e = run.step(proposer, rng)
        verdict = f"kept as {e['child']}" if e["accepted"] else (e["error"] or "not better")
        say(f"iteration {e['iteration']}: parent {e['parent']} on {', '.join(e['batch'])}: {verdict}"
            f"  ({e['parent_batch']} -> {e['child_batch']}, {e.get('seconds')} s)", flush=True)
    run.stage("stopped")
    b = run.best()
    say(f"best so far: {b.id} with {b.total()} (hard, soft, cost) over {len(run.house_ids)} houses; "
        f"Pareto set: {', '.join(f'{c} ({len(h)})' for c, h in run.pareto().items())}")
