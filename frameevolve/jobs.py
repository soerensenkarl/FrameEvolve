"""Background jobs the workbench starts: a search, the test suite, scoring a grammar on houses.

Each job is a separate process built from a fixed command (never a shell string), with its output in a
log file. jobs/<id>/job.json records what was asked and how it ended, so the list survives a restart of
the workbench. A search stops cleanly: `stop` asks it to finish the current iteration first; `kill`
ends it at once.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "jobs"
NAME = re.compile(r"^[A-Za-z0-9_\-]+$")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def credentials() -> dict:
    """Whether the proposer can reach Claude, and how."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"ok": True, "how": "ANTHROPIC_API_KEY is set"}
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return {"ok": True, "how": "ANTHROPIC_AUTH_TOKEN is set"}
    if (Path.home() / ".config" / "anthropic").exists():
        return {"ok": True, "how": "an `ant auth login` profile exists"}
    return {"ok": False, "how": "No Claude credentials. Set ANTHROPIC_API_KEY before starting the workbench, "
                                "or run `ant auth login` once. Dry runs work without them."}


def _house(path: str) -> str:
    p = (ROOT / path).resolve()
    if ROOT not in p.parents or p.suffix != ".json" or not p.is_file():
        raise ValueError(f"not a house file: {path}")
    return str(p.relative_to(ROOT))


def _grammar(path: str) -> str:
    p = (ROOT / path).resolve()
    if ROOT not in p.parents or p.suffix != ".py" or not p.is_file():
        raise ValueError(f"not a grammar file: {path}")
    return str(p.relative_to(ROOT))


def command(kind: str, a: dict) -> tuple[list[str], str]:
    """The argv for a job, from validated settings, and a one-line title."""
    py = [sys.executable, "-u", "-m"]
    if kind == "evolve":
        run = a.get("run", "")
        if not NAME.match(run):
            raise ValueError("a run name uses letters, digits, - and _ only")
        n = int(a.get("iterations", 5))
        if not 1 <= n <= 500:
            raise ValueError("iterations must be 1 to 500")
        argv = py + ["frameevolve", "evolve", f"runs/{run}", "--iterations", str(n), "--seed", str(int(a.get("seed", 0)))]
        if not (ROOT / "runs" / run / "config.json").exists():   # settings that only matter for a new run
            argv += ["--seed-grammar", _grammar(a.get("seed_grammar", "grammars/seed.py")),
                     "--minibatch", str(int(a.get("minibatch", 3)))]
            if a.get("train"):
                argv += ["--train", *[_house(h) for h in a["train"]]]
        if a.get("dry"):
            argv.append("--dry")
        else:
            model = a.get("model", "claude-opus-5-5")
            if not re.match(r"^claude-[a-z0-9\-]+$", model):
                raise ValueError(f"not a Claude model id: {model}")
            effort = a.get("effort", "medium")
            if effort not in EFFORTS:
                raise ValueError(f"effort is one of {', '.join(EFFORTS)}")
            argv += ["--model", model, "--effort", effort, "--checks", str(int(a.get("checks", 3)))]
            if a.get("no_images"):
                argv.append("--no-images")
        return argv, f"search {run}: {n} iterations" + (" (dry)" if a.get("dry") else "")
    if kind == "tests":
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], "test suite"
    if kind == "evaluate":
        g = _grammar(a.get("grammar", "grammars/seed.py"))
        houses = [_house(h) for h in a.get("houses", [])]
        if not houses:
            raise ValueError("choose at least one house")
        return py + ["frameevolve", "build", g, *houses, "--out", f"out/{Path(g).stem}"], f"score {g} on {len(houses)} houses"
    raise ValueError(f"unknown job kind: {kind}")


class Jobs:
    def __init__(self, root: Path = JOBS):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.procs: dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()

    def _meta(self, jid: str) -> dict:
        return json.loads((self.root / jid / "job.json").read_text())

    def _save(self, jid: str, meta: dict) -> None:
        (self.root / jid / "job.json").write_text(json.dumps(meta, indent=1))

    def start(self, kind: str, settings: dict) -> dict:
        argv, title = command(kind, settings)
        with self.lock:
            if kind == "evolve" and any(m["kind"] == "evolve" and m["settings"].get("run") == settings.get("run")
                                        and m["status"] == "running" for m in self.list()):
                raise ValueError(f"run {settings.get('run')} already has a running search")
            jid = time.strftime("%Y%m%d-%H%M%S") + f"-{kind}"
            n = 1
            while (self.root / jid).exists():
                n += 1
                jid = time.strftime("%Y%m%d-%H%M%S") + f"-{kind}{n}"
            (self.root / jid).mkdir()
            log = open(self.root / jid / "log.txt", "w")
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            p = subprocess.Popen(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env,
                                 start_new_session=True)
            self.procs[jid] = p
            meta = {"id": jid, "kind": kind, "title": title, "settings": settings,
                    "argv": [Path(argv[0]).name, *argv[1:]], "status": "running", "pid": p.pid,
                    "started": time.time(), "ended": None, "returncode": None}
            self._save(jid, meta)
        threading.Thread(target=self._wait, args=(jid, p, log), daemon=True).start()
        return meta

    def _wait(self, jid: str, p: subprocess.Popen, log) -> None:
        rc = p.wait()
        log.close()
        with self.lock:
            meta = self._meta(jid)
            if meta["status"] == "running":
                meta["status"] = "done" if rc == 0 else "failed"
            meta["returncode"], meta["ended"] = rc, time.time()
            self._save(jid, meta)
            self.procs.pop(jid, None)

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.root.iterdir(), reverse=True):
            if (d / "job.json").exists():
                meta = json.loads((d / "job.json").read_text())
                if meta["status"] == "running" and d.name not in self.procs:
                    meta["status"] = "lost"     # the workbench restarted while it ran
                out.append(meta)
        return out

    def get(self, jid: str, tail: int = 400) -> dict:
        if not NAME.match(jid) or not (self.root / jid / "job.json").exists():
            raise ValueError("no such job")
        meta = next(m for m in self.list() if m["id"] == jid)
        lines = (self.root / jid / "log.txt").read_text(errors="replace").splitlines()
        return {**meta, "log": "\n".join(lines[-tail:])}

    def stop(self, jid: str) -> dict:
        """A search finishes its current iteration and stops; anything else ends now."""
        meta = self.get(jid)
        if meta["status"] != "running":
            return meta
        if meta["kind"] == "evolve":
            (ROOT / "runs" / meta["settings"]["run"] / "STOP").write_text("stop requested from the workbench\n")
            return {**meta, "stopping": True}
        return self.kill(jid)

    def kill(self, jid: str) -> dict:
        p = self.procs.get(jid)
        if p and p.poll() is None:
            with self.lock:
                meta = self._meta(jid)
                meta["status"] = "stopped"
                self._save(jid, meta)
            os.killpg(p.pid, signal.SIGTERM)
        return self.get(jid)
