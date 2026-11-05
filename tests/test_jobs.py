import json
import shutil
import time
import uuid

import pytest

from frameevolve.jobs import ROOT, Jobs, command


def wait(jobs, jid, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        j = jobs.get(jid)
        if j["status"] != "running":
            return j
        time.sleep(0.3)
    raise AssertionError(f"job {jid} still running")


def test_commands_are_built_from_checked_settings():
    """Bad names and paths outside the project are refused; no shell strings are ever built."""
    argv, title = command("evolve", {"run": "abc", "iterations": 3, "dry": True})
    assert argv[-1] == "--dry" and "runs/abc" in argv and "search abc" in title
    argv, _ = command("evolve", {"run": "abc", "iterations": 3, "model": "claude-opus-5-5"})
    assert argv[argv.index("--effort") + 1] == "medium"
    for bad in [{"run": "../x"}, {"run": "a b"}, {"run": "ok", "iterations": 0},
                {"run": "ok", "model": "gpt-4"}, {"run": "ok", "effort": "huge"},
                {"run": "ok", "seed_grammar": "../../etc/passwd.py"}]:
        with pytest.raises(ValueError):
            command("evolve", bad)
    with pytest.raises(ValueError):
        command("evaluate", {"grammar": "grammars/seed.py", "houses": ["/etc/hosts"]})
    with pytest.raises(ValueError):
        command("shell", {})


def test_evaluate_job_runs_and_logs(tmp_path):
    jobs = Jobs(tmp_path / "jobs")
    j = jobs.start("evaluate", {"grammar": "grammars/seed.py", "houses": ["data/houses/h000.json"]})
    done = wait(jobs, j["id"])
    assert done["status"] == "done", done["log"]
    assert "House h000" in done["log"]
    assert jobs.list()[0]["id"] == j["id"]


def test_search_job_stops_cleanly_between_iterations(tmp_path):
    """Stop lets the current iteration finish, then the search ends with its run folder intact."""
    run = f"pytest-{uuid.uuid4().hex[:6]}"
    jobs = Jobs(tmp_path / "jobs")
    try:
        j = jobs.start("evolve", {"run": run, "iterations": 200, "dry": True,
                                  "train": [f"data/houses/h00{i}.json" for i in range(3)], "minibatch": 2})
        with pytest.raises(ValueError):    # one search per run at a time
            jobs.start("evolve", {"run": run, "iterations": 1, "dry": True})
        lines = ROOT / "runs" / run / "iterations.jsonl"
        t = time.time()
        while not (lines.exists() and lines.read_text().strip()) and time.time() - t < 60:
            time.sleep(0.2)
        jobs.stop(j["id"])
        done = wait(jobs, j["id"])
        assert done["status"] == "done", done["log"]
        assert "stopped on request" in done["log"]
        n = len(lines.read_text().splitlines())
        assert 1 <= n < 200
        assert all(json.loads(l)["iteration"] for l in lines.read_text().splitlines())
        assert not (ROOT / "runs" / run / "STOP").exists()
    finally:
        shutil.rmtree(ROOT / "runs" / run, ignore_errors=True)
