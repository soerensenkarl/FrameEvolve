import json
import re
from pathlib import Path
from types import SimpleNamespace

import random

from frameevolve import houses
from frameevolve.proposer import ClaudeProposer, ScriptedProposer
from frameevolve.search import FAILED, Candidate, Run, evaluate, pareto

ROOT = Path(__file__).resolve().parents[1]


def make_run(tmp_path, seed_src, n=3, minibatch=2):
    paths = []
    for i in range(n):
        h = houses.generate(i)
        p = tmp_path / f"{h.id}.json"
        h.save(p)
        paths.append(p)
    g = tmp_path / "seed.py"
    g.write_text(seed_src)
    return Run.create(tmp_path / "run", g, paths, minibatch, "test")


def test_pareto_keeps_every_grammar_that_is_best_somewhere():
    """A grammar that is best on one house stays, even with a poor average."""
    cs = [Candidate("A", None, 0, {"h1": [0, 0, 9], "h2": [0, 0, 6], "h3": [0, 0, 5], "h4": [0, 0, 4]}),
          Candidate("B", None, 0, {"h1": [0, 0, 7], "h2": [0, 0, 8], "h3": [0, 0, 8], "h4": [0, 0, 3]}),
          Candidate("C", None, 0, {"h1": [0, 0, 8], "h2": [0, 0, 7], "h3": [0, 0, 6], "h4": [0, 0, 5]}),
          Candidate("D", None, 0, {"h1": [1, 0, 1], "h2": [1, 0, 1], "h3": [1, 0, 1], "h4": [1, 0, 1]})]
    wins = pareto(cs, ["h1", "h2", "h3", "h4"])
    assert wins == {"A": ["h2", "h3"], "B": ["h1", "h4"]}   # D is cheap but has a hard fault everywhere


def test_evaluate_survives_a_grammar_that_hangs(tmp_path):
    """A proposed grammar that never returns gets the failed score instead of stalling the search."""
    g = tmp_path / "hang.py"
    g.write_text("from frameevolve.builder import rule\n\n@rule(1, match='wall')\ndef hang(s, w):\n    while True:\n        pass\n")
    h = tmp_path / "h.json"
    houses.generate(0).save(h)
    res = evaluate(g, [h], timeout=3)
    assert res["h000"]["score"] == FAILED


def test_search_keeps_only_improvements(tmp_path):
    """Kept children beat their parent on the minibatch; unchanged and worse proposals are logged, not kept."""
    seed = (ROOT / "grammars/seed.py").read_text().replace("SPACING = 16", "SPACING = 12")
    run = make_run(tmp_path, seed)
    choices = iter([16, 16, 8])

    def edit(src, ctx):
        return re.sub(r"SPACING = \d+", f"SPACING = {next(choices)}", src), "spacing"
    rng = random.Random(0)
    entries = [run.step(ScriptedProposer(edit), rng) for _ in range(3)]
    assert entries[0]["accepted"] and entries[0]["child"] == "c001"
    assert not entries[1]["accepted"]    # same grammar again, or a parent already at 16
    assert not entries[2]["accepted"]    # 8 in. is dearer
    lines = (run.path / "iterations.jsonl").read_text().splitlines()
    assert len(lines) == 3
    assert len(Run(run.path).cands) == len(run.cands)
    for e in entries:
        if e["accepted"]:
            assert tuple(e["child_batch"]) < tuple(e["parent_batch"])


class FakeMessage:
    def __init__(self, text, stop="end_turn"):
        self.content = [SimpleNamespace(type="text", text=text)]
        self.stop_reason = stop
        self.usage = SimpleNamespace(input_tokens=100, output_tokens=20)

    def to_dict(self):
        return {"content": [{"type": "text", "text": self.content[0].text}], "stop_reason": self.stop_reason}


def test_claude_proposer_edits_through_its_tools(tmp_path, monkeypatch):
    """The proposer's tools edit and check a draft; the run keeps the result. No network."""
    seen = {}

    def tool_runner(**kw):
        seen.update(kw)
        tools = {t.name: t for t in kw["tools"]}
        assert "SPACING = 12" in tools["view_grammar"].call({})
        assert tools["edit_grammar"].call({"old": "SPACING = 12", "new": "SPACING = 16"}) == "Changed."
        assert "occurs 0 times" in tools["edit_grammar"].call({"old": "nothing like this", "new": "x"})
        seen["check"] = tools["check_grammar"].call({})
        yield FakeMessage("", "tool_use")
        yield FakeMessage("Widened the stud module to 16 in.; fewer studs, same backing.")

    import anthropic
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(tool_runner=tool_runner)))
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: fake)
    seed = (ROOT / "grammars/seed.py").read_text().replace("SPACING = 16", "SPACING = 12")
    run = make_run(tmp_path, seed)
    e = run.step(ClaudeProposer(model="claude-opus-5-5", checks=2), random.Random(1))
    assert e["accepted"], e
    assert "SPACING = 16" in run.grammar(e["child"]).read_text()
    assert e["note"].startswith("Widened")
    assert seen["model"] == "claude-opus-5-5" and seen["output_config"] == {"effort": "medium"}
    assert seen["check"].startswith("Check 1 of 2")
    kinds = [b["type"] for b in seen["messages"][0]["content"]]
    assert kinds[0] == "text" and kinds.count("image") == 2
    out = run.path / "proposals" / "0001"
    assert (out / "prompt.md").exists() and json.loads((out / "transcript.json").read_text())
