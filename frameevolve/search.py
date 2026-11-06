"""The search: evolve a grammar against the verifier, keeping a Pareto set over houses.

The houses come in three sets, as in GEPA:
  train  the proposer reads reports on these; minibatches are drawn from them
  val    decides the Pareto set, the parents and the final grammar; the proposer never reads their reports
  test   reported for the final grammar only, never used by the search
A run without a validation set uses the training houses for both, as the first runs did.

One iteration:
  1. Pick a parent from the Pareto set over validation houses, weighted by the number of houses it is best on.
  2. Take a minibatch of training houses; the parent's reports and elevations on them (from the cache).
  3. The proposer reads the parent, its reports and pictures, the children of this parent that were not kept,
     and a few other grammars from the Pareto set that beat the parent where it is weak, and returns a child.
  4. Refuse the child if the file does not compile or any function is longer than the run's line limit.
     Smoke test it on the smallest house of the minibatch: refuse it if it crashes or raises more rule errors
     than the parent there. Then verify it on the rest of the minibatch and keep it only if it beats the parent.
  5. If kept, evaluate it on every training and validation house and add it to the pool.

A grammar is the best on a house when no other grammar has a better score there. Scores are compared as
(hard faults, soft faults, cost). Grammars run in separate processes with a timeout, because a proposed
grammar is code that no person has read; houses are split over processes to use every core. Results are
cached by the content of the grammar, the house and the framework code, so nothing is built twice.

Everything is written to a run folder, which the workbench reads:
  runs/<name>/config.json        what was asked for
  runs/<name>/candidates.jsonl   one line per kept grammar: id, parent, scores per house, note
  runs/<name>/grammars/<id>.py   the grammars
  runs/<name>/iterations.jsonl   one line per iteration, kept or not
  runs/<name>/proposals/<n>/     what the proposer saw and did in iteration n; live.jsonl streams its actions
                                 as they happen and draft.py holds its current draft
  runs/<name>/cache/             evaluation results and elevations, by content hash
  runs/<name>/test.json          the final grammar's scores on the test houses
  runs/<name>/live.json          what the search is doing right now (stage, iteration, parent, houses)
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from frameevolve.builder import MAX_LINES, too_big
from frameevolve.model import House

ROOT = Path(__file__).resolve().parents[1]
SEED_GRAMMAR = "grammars/seed.py"   # where a run starts unless told otherwise
FAILED = [10**6, 10**6, 1e12]   # the score of a grammar that crashed or timed out
INSPIRATIONS = 2                # other Pareto grammars shown to the proposer
REJECTED = 3                    # earlier children of the parent that were not kept, shown to the proposer
NOTEBOOK = 24                   # lessons from earlier iterations of the run, newest, shown to the proposer
PICTURES = {"image": ".png", "image3d": ".3d.png"}   # elevations, and the whole frame in 3D from two sides


@dataclass
class Candidate:
    id: str
    parent: str | None
    iteration: int
    scores: dict[str, list]              # house id: [hard, soft, cost]
    note: str = ""
    created: float = field(default_factory=time.time)

    def total(self, houses=None) -> list:
        return total(self.scores, houses or list(self.scores))


def total(scores: dict, houses) -> list:
    """Scores summed over houses: [hard, soft, cost]."""
    return [sum(scores[h][0] for h in houses), sum(scores[h][1] for h in houses),
            round(sum(scores[h][2] for h in houses), 2)]


@lru_cache(maxsize=None)
def house_id(path: Path) -> str:
    return House.load(path).id


NOT_EVALUATION = {"server.py", "jobs.py", "proposer.py", "search.py", "describe.py"}   # code that does not change a result


@lru_cache(maxsize=1)
def code_hash() -> str:
    """The code that builds, verifies and draws a frame: a change to it must not reuse old results."""
    h = hashlib.sha256()
    for f in sorted((ROOT / "frameevolve").rglob("*.py")):
        if f.name not in NOT_EVALUATION:
            h.update(str(f.relative_to(ROOT)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def cache_key(grammar_src: str, house: Path) -> str:
    h = hashlib.sha256(code_hash().encode())
    h.update(grammar_src.encode())
    h.update(Path(house).read_bytes())
    return h.hexdigest()[:24]


def failed(hid: str, why: str) -> dict:
    return {"score": FAILED, "hard": FAILED[0], "soft": 0, "text": f"House {hid}: evaluation failed: {why}",
            "faults": [], "metrics": {}, "image": None, "image3d": None}


def _run_group(grammar: Path, houses: list[Path], timeout: float, images: Path | None) -> dict:
    """One process builds and verifies the grammar on a group of houses."""
    cmd = [sys.executable, "-m", "frameevolve", "evaluate", str(grammar), *map(str, houses)]
    if images:
        cmd += ["--images", str(images)]
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        if p.returncode == 0:
            return json.loads(p.stdout)
        why = (p.stderr.strip().splitlines() or ["no output"])[-1]
    except subprocess.TimeoutExpired:
        why = f"timed out after {timeout:.0f} s"
    return {house_id(h): failed(house_id(h), why) for h in houses}


def evaluate(grammar: Path, houses: list[Path], timeout: float = 120, cache: Path | None = None,
             images: Path | None = None) -> dict:
    """Build and verify a grammar on houses, in separate processes, one group of houses per core.
    Returns {house id: result}. With `cache`, results (and elevations) are reused by content. With `images`,
    each house's pictures, hard faults marked, are written there and named in the result: elevations as
    <house id>.png ("image") and the whole frame from two sides as <house id>.3d.png ("image3d")."""
    grammar, houses = Path(grammar), [Path(h) for h in houses]
    src = grammar.read_text()
    out, todo = {}, []
    for h in houses:
        hid = house_id(h)
        if cache:
            key = cache_key(src, h)
            f = cache / f"{key}.json"
            if f.exists() and (not images or all((cache / f"{key}{x}").exists() for x in PICTURES.values())):
                out[hid] = json.loads(f.read_text())
                if images:
                    images.mkdir(parents=True, exist_ok=True)
                    for name, x in PICTURES.items():
                        shutil.copy(cache / f"{key}{x}", images / f"{hid}{x}")
                        out[hid][name] = str(images / f"{hid}{x}")
                continue
        todo.append(h)
    if todo:
        n = min(len(todo), os.cpu_count() or 4)
        groups = [todo[i::n] for i in range(n)]
        with ThreadPoolExecutor(n) as pool:
            for res in pool.map(lambda g: _run_group(grammar, g, timeout, images), groups):
                out.update(res)
        if cache:
            cache.mkdir(parents=True, exist_ok=True)
            for h in todo:
                r = out[house_id(h)]
                if r["score"] == FAILED:
                    continue                 # a timeout may be the machine, not the grammar
                key = cache_key(src, h)
                if images:
                    for name, x in PICTURES.items():
                        if r.get(name):
                            shutil.copy(r[name], cache / f"{key}{x}")
                (cache / f"{key}.json").write_text(json.dumps({**r, **{name: None for name in PICTURES}}))
    return {house_id(h): out[house_id(h)] for h in houses}


def dominates(a: Candidate, b: Candidate, houses: list[str]) -> bool:
    """a is at least as good as b on every house and better on one."""
    pairs = [(tuple(a.scores[h]), tuple(b.scores[h])) for h in houses]
    return all(x <= y for x, y in pairs) and any(x < y for x, y in pairs)


def pareto(cands: list[Candidate], houses: list[str]) -> dict[str, list[str]]:
    """For every candidate in the Pareto set, the houses it is best on (ties all count). Candidates that are best
    somewhere but dominated by another such candidate are dropped first (GEPA, Algorithm 2), so near-copies do
    not crowd the draw."""
    best = {h: min(tuple(c.scores[h]) for c in cands) for h in houses}
    front = [c for c in cands if any(tuple(c.scores[h]) == best[h] for h in houses)]
    front = [c for c in front if not any(dominates(o, c, houses) for o in front if o is not c)]
    wins: dict[str, list[str]] = {}
    for h in houses:
        for c in front:
            if tuple(c.scores[h]) == best[h]:
                wins.setdefault(c.id, []).append(h)
    return wins


def better(a: list, b: list) -> bool:
    return tuple(a) < tuple(b)


def batch_total(res: dict, ids: list[str]) -> list:
    return [round(sum(res[h]["score"][j] for h in ids), 2) for j in range(3)]


def overview(grammar: Path, house: Path) -> str:
    """The frame a grammar builds on a house, surface by surface, in words (describe.overview), built in its own
    process like every evaluation; empty if it fails."""
    try:
        p = subprocess.run([sys.executable, "-m", "frameevolve", "describe", str(grammar), str(house)], cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
        return p.stdout.strip() if p.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        return ""


def compiles(src: str) -> str | None:
    """Why the source is not valid Python, or None."""
    try:
        compile(src, "proposed.py", "exec")
    except SyntaxError as e:
        return f"does not compile: {e.msg} at line {e.lineno}"
    return None


def rule_errors(r: dict) -> int:
    return sum(1 for f in r["faults"] if f["check"] == "rule error")


class Run:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.config = json.loads((self.path / "config.json").read_text())
        self.cands: list[Candidate] = []
        f = self.path / "candidates.jsonl"
        if f.exists():
            self.cands = [Candidate(**json.loads(l)) for l in f.read_text().splitlines() if l.strip()]
        self.iteration = len(self.iterations())

    @staticmethod
    def create(path: Path, seed_grammar: Path, train: list[Path], minibatch: int, model: str, note: str = "",
               max_lines: int = MAX_LINES, val: list[Path] = (), test: list[Path] = (),
               inspirations: int = INSPIRATIONS) -> "Run":
        path = Path(path)
        missing = [str(h) for h in [*train, *val, *test] if not Path(h).exists()]
        if missing:
            raise FileNotFoundError("no such house: " + ", ".join(missing))
        (path / "grammars").mkdir(parents=True, exist_ok=False)
        config = {"seed_grammar": str(seed_grammar), "train": [str(h) for h in train], "val": [str(h) for h in val],
                  "test": [str(h) for h in test], "minibatch": minibatch, "model": model, "max_lines": max_lines,
                  "inspirations": inspirations, "note": note, "created": time.time(), "code": code_hash()}
        (path / "config.json").write_text(json.dumps(config, indent=1))
        run = Run(path)
        src = Path(seed_grammar).read_text()
        (path / "grammars" / "c000.py").write_text(src)
        res = evaluate(path / "grammars" / "c000.py", run.scored, cache=run.cache)
        run.add(Candidate("c000", None, 0, {h: r["score"] for h, r in res.items()}, f"seed: {Path(seed_grammar).name}"))
        return run

    @property
    def max_lines(self) -> int:
        return self.config.get("max_lines", MAX_LINES)

    @property
    def cache(self) -> Path:
        return self.path / "cache"

    @property
    def train(self) -> list[Path]:
        return [Path(h) for h in self.config["train"]]

    @property
    def val(self) -> list[Path]:
        """The houses that decide the Pareto set and the final grammar; the training houses if none were given."""
        return [Path(h) for h in self.config.get("val") or self.config["train"]]

    @property
    def test(self) -> list[Path]:
        return [Path(h) for h in self.config.get("test") or []]

    @property
    def scored(self) -> list[Path]:
        """Every house a kept grammar is scored on: training and validation."""
        return list(dict.fromkeys(self.train + self.val))

    @property
    def house_ids(self) -> list[str]:
        return [house_id(h) for h in self.train]

    @property
    def val_ids(self) -> list[str]:
        return [house_id(h) for h in self.val]

    def grammar(self, cid: str) -> Path:
        return self.path / "grammars" / f"{cid}.py"

    def cand(self, cid: str) -> Candidate:
        return next(c for c in self.cands if c.id == cid)

    def add(self, c: Candidate) -> None:
        self.cands.append(c)
        with open(self.path / "candidates.jsonl", "a") as f:
            f.write(json.dumps(asdict(c)) + "\n")

    def log(self, entry: dict) -> None:
        with open(self.path / "iterations.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

    def iterations(self) -> list[dict]:
        f = self.path / "iterations.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []

    def stage(self, stage: str, **info) -> None:
        """Say what the search is doing now, for anyone watching (the workbench)."""
        (self.path / "live.json").write_text(json.dumps({"stage": stage, "time": time.time(), **info}))

    def pareto(self) -> dict[str, list[str]]:
        return pareto(self.cands, self.val_ids)

    def best(self) -> Candidate:
        """The grammar with the best total over the validation houses."""
        return min(self.cands, key=lambda c: c.total(self.val_ids))

    def rejected(self, parent: str, n: int = REJECTED) -> list[dict]:
        """The latest children of this parent that were not kept, and why: so the proposer does not repeat them."""
        out = [{"iteration": e["iteration"], "error": e.get("error"), "parent_batch": e.get("parent_batch"),
                "child_batch": e.get("child_batch"), "note": (e.get("note") or "")[:600]}
               for e in self.iterations() if e.get("parent") == parent and not e.get("accepted")]
        return out[-n:]

    def notebook(self, n: int = NOTEBOOK) -> list[dict]:
        """The run's notebook (GEPA's reflective memory, kept short): the lessons proposers wrote down, the newest n,
        each with how its iteration came out."""
        out = [{"iteration": e["iteration"], "accepted": e["accepted"], "error": e.get("error"),
                "parent_batch": e.get("parent_batch"), "child_batch": e.get("child_batch"), "lesson": lesson}
               for e in self.iterations() for lesson in e.get("lessons") or []]
        return out[-n:]

    def inspirations(self, parent: Candidate, wins: dict[str, list[str]], n: int) -> list[dict]:
        """Other grammars in the Pareto set, those better than the parent on the most validation houses first.
        The proposer sees their code and their training scores, never validation reports."""
        rivals = []
        for cid in wins:
            if cid == parent.id:
                continue
            c = self.cand(cid)
            beats = sum(better(c.scores[h], parent.scores[h]) for h in self.val_ids)
            if beats:
                rivals.append((beats, len(wins[cid]), c))
        rivals.sort(key=lambda r: (-r[0], -r[1], r[2].id))
        out = []
        for _, _, c in rivals[:n]:
            better_on = [h for h in self.house_ids if better(c.scores[h], parent.scores[h])]
            out.append({"id": c.id, "total": c.total(self.house_ids), "better_on": better_on, "note": c.note[:600],
                        "source": self.grammar(c.id).read_text()})
        return out

    def smoke(self, src_path: Path, batch: list[Path], parent_res: dict) -> str | None:
        """Why the child fails a cheap test, or None: builds it on the smallest minibatch house. That result is
        cached, so a child that passes costs nothing extra."""
        small = min(batch, key=lambda h: h.stat().st_size)
        hid = house_id(small)
        r = evaluate(src_path, [small], timeout=60, cache=self.cache)[hid]
        if r["score"] == FAILED:
            return f"smoke test on {hid}: {r['text']}"
        if rule_errors(r) > rule_errors(parent_res[hid]):
            first = next(f["message"] for f in r["faults"] if f["check"] == "rule error")
            return f"smoke test on {hid}: {rule_errors(r)} rule errors (parent {rule_errors(parent_res[hid])}): {first}"
        return None

    def context(self, it: int, parent: Candidate, batch: list[Path], out: Path) -> tuple[dict, dict]:
        """What the proposer sees for one iteration, and the parent's results on the minibatch: its reports and
        pictures there, its scores on every training house, the Pareto set, rejected siblings, inspirations."""
        batch_ids = [house_id(h) for h in batch]
        parent_res = evaluate(self.grammar(parent.id), batch, cache=self.cache, images=out)
        wins = self.pareto()
        context = {
            "iteration": it, "parent": parent.id, "houses": batch_ids, "house_paths": [str(h) for h in batch],
            "parent_batch": batch_total(parent_res, batch_ids), "max_lines": self.max_lines, "cache": str(self.cache),
            "reports": {h: parent_res[h]["text"] for h in batch_ids},
            "parent_scores": {h: parent.scores[h] for h in self.house_ids},
            "images": [parent_res[h][name] for h in batch_ids for name in ("image3d", "image")
                       if parent_res[h].get(name)],
            "pareto": dict(wins),
            "rejected": self.rejected(parent.id),
            "notebook": self.notebook(),
            "overviews": {h: overview(self.grammar(parent.id), p) for h, p in zip(batch_ids, batch)},
            "inspirations": self.inspirations(parent, wins, self.config.get("inspirations", INSPIRATIONS)),
        }
        return context, parent_res

    def judge(self, source: str, parent_src: str, parent_res: dict, batch: list[Path], proposed: Path,
              now: dict) -> tuple[str | None, list | None]:
        """Why a proposal is refused, or None; and its minibatch total when it got that far. Cheap tests first:
        unchanged, does not compile, too big, smoke test; then the whole minibatch."""
        if source.strip() == parent_src.strip():
            return "the proposal did not change the grammar", None
        if bad := compiles(source):
            return bad, None
        if big := too_big(source, self.max_lines):
            return "too big: " + " ".join(big), None
        self.stage("smoke test", **now)
        if bad := self.smoke(proposed, batch, parent_res):
            return bad, None
        self.stage("testing the proposal", **now)
        return None, batch_total(evaluate(proposed, batch, cache=self.cache), [house_id(h) for h in batch])

    def step(self, proposer, rng: random.Random) -> dict:
        """One iteration. Returns the logged entry."""
        self.iteration += 1
        it = self.iteration
        t0 = time.time()
        wins = self.pareto()
        parent = self.cand(rng.choices(list(wins), weights=[len(h) for h in wins.values()])[0])
        batch = rng.sample(self.train, min(self.config["minibatch"], len(self.train)))
        batch_ids = [house_id(h) for h in batch]
        out = self.path / "proposals" / f"{it:04d}"
        out.mkdir(parents=True, exist_ok=True)
        now = {"iteration": it, "parent": parent.id, "houses": batch_ids, "proposal": out.name, "started": t0}
        self.stage("reading the parent", **now)
        parent_src = self.grammar(parent.id).read_text()
        context, parent_res = self.context(it, parent, batch, out)
        entry = {"iteration": it, "parent": parent.id, "batch": batch_ids, "accepted": False, "child": None,
                 "parent_batch": context["parent_batch"], "child_batch": None, "note": "", "error": None,
                 "inspirations": [i["id"] for i in context["inspirations"]]}

        def done() -> dict:
            entry["seconds"] = round(time.time() - t0, 1)
            self.log(entry)
            self.stage("between iterations", **now, accepted=entry["accepted"], child=entry["child"])
            return entry

        self.stage("proposing", **now)
        try:
            proposal = proposer.propose(parent_src, context, out)
        except Exception as e:
            entry["error"] = f"proposer failed: {type(e).__name__}: {e}"
            return done()
        entry["note"], entry["usage"], entry["lessons"] = proposal.note, proposal.usage, proposal.lessons
        proposed = out / "proposed.py"
        proposed.write_text(proposal.source)
        entry["error"], entry["child_batch"] = self.judge(proposal.source, parent_src, parent_res, batch, proposed, now)
        if not entry["error"] and better(entry["child_batch"], entry["parent_batch"]):
            cid = f"c{len(self.cands):03d}"
            self.stage("scoring on every house", **now, child=cid)
            self.grammar(cid).write_text(proposal.source)
            full = evaluate(self.grammar(cid), self.scored, cache=self.cache)
            self.add(Candidate(cid, parent.id, it, {h: r["score"] for h, r in full.items()}, proposal.note))
            entry["accepted"], entry["child"] = True, cid
        return done()

    def report_test(self) -> dict | None:
        """Score the best grammar on the test houses and write test.json. None when the run has no test set."""
        if not self.test:
            return None
        b = self.best()
        res = evaluate(self.grammar(b.id), self.test, cache=self.cache)
        scores = {h: r["score"] for h, r in res.items()}
        out = {"candidate": b.id, "val_total": b.total(self.val_ids), "scores": scores,
               "total": total(scores, list(scores)), "time": time.time()}
        (self.path / "test.json").write_text(json.dumps(out, indent=1))
        return out


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
            f"  ({e['parent_batch']} -> {e['child_batch']}, {e.get('seconds')} s)")
    run.stage("stopped")
    b = run.best()
    say(f"best on validation: {b.id} with {b.total(run.val_ids)} (hard, soft, cost) over {len(run.val_ids)} houses; "
        f"Pareto set: {', '.join(f'{c} ({len(h)})' for c, h in run.pareto().items())}")
    t = run.report_test()
    if t:
        say(f"test: {t['candidate']} scores {t['total']} over {len(t['scores'])} held-out houses")
