"""Proposers: what turns a parent grammar and its reports into a child grammar.

ClaudeCodeProposer (the default, through the Claude Agent SDK on a Claude subscription) and ClaudeProposer
(through the API) are the same agent: it sees the parent grammar, the verifier's reports and pictures with
the faults marked, and edits the grammar with a few small tools. ScriptedProposer applies a fixed function,
for testing the search without calling Claude.
"""
from __future__ import annotations

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TURNS = 60   # tool rounds per proposal: enough to try, look, edit and check; past it the draft is what is proposed

import base64
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from frameevolve.builder import MAX_LINES, too_big
from frameevolve.model import SECTIONS, STOCK
from frameevolve.verifier import CHECKS


@dataclass
class Proposal:
    source: str
    note: str = ""
    usage: dict = field(default_factory=dict)
    lessons: list[str] = field(default_factory=list)   # what the proposer learned, for later proposers in the run


class ScriptedProposer:
    """Applies edit(source, context) -> (source, note). For tests and dry runs."""

    def __init__(self, edit: Callable[[str, dict], tuple[str, str]]):
        self.edit = edit

    def propose(self, source: str, context: dict, out: Path) -> Proposal:
        src, note = self.edit(source, context)
        return Proposal(src, note)


def api_reference() -> str:
    """What a rule can call on `s`, written from the builder's own signatures and docstrings."""
    import frameevolve.builder as builder
    doc = inspect.getdoc(builder)
    lines = [doc[doc.index("A grammar is"):].strip(), "",
             "s.surface: the current surface. A wall has id, length, height, base, role ('exterior' or 'interior'), "
             "openings, start_meets, end_meets (the wall met at its start or end, or None), tees, above, below, and "
             "outline (u, v points) when its top is not level (a gable wall). A floor or ceiling has id, role "
             "('floor' or 'ceiling'), outline_uv, z, openings, bearers, loads. A roof plane has id, pitch, slope, "
             "size, outline_uv, seams, and height(x, y), its height over a point in plan. Every surface has "
             "world(u, v, w), local(point), local_dir(vector) and faces.",
             "Each opening has id, kind ('window', 'door' or 'stair'), u0, u1, v0, v1, width, height.",
             "s.house.walls, s.house.floors, s.house.roofs, s.house.surface(id). s.SECTIONS (nominal name: actual "
             "size): " + ", ".join(f"{k} ({w:g} x {d:g})" for k, (w, d) in SECTIONS.items())
             + f". s.STOCK: stock lengths {', '.join(map(str, STOCK))} (8 to 20 ft).",
             "A member has id, section, rule, surface (its surface id), role (a free label), length, width, depth, "
             "start, end, up, box (lo, hi world corners), points, cuts, notches and panel (the prefab panel it is "
             "built into, or '' for built on site).", ""]
    for name in ["place", "put", "cut", "trim", "under", "notch", "fit", "remove", "assign", "guide", "guides",
                 "crossings", "members", "local", "overlapping", "bears_on",
                 "carries", "beside", "gaps", "below", "above", "free"]:
        fn = getattr(builder.State, name)
        doc = " ".join((inspect.getdoc(fn) or "").split())
        lines.append(f"s.{name}{inspect.signature(fn)}".replace("self, ", "").replace("(self)", "()") + f": {doc}")
    lines += ["", "A gap from s.gaps() has u0, u1, v0, v1, face and kind 'edge' or 'field'.",
              "Import with `from frameevolve.builder import rule`."]
    return "\n".join(lines)


SYSTEM = """You improve a grammar: a Python file of small rules that frames the timber walls, floors and roofs of houses
as prefab panels: wall panels, floor cassettes and roof panels built flat in a shop, cut by an automated saw,
trucked to site and lifted into place one after another, bottom up.

The builder applies the grammar to a house. A deterministic verifier then checks the frame and scores it as
(hard faults, soft faults, cost), compared in that order. It checks what an inspector, an engineer and a panel
shop would: that the frame stands, carries its loads, meets the IRC's rules, and can be built as panels small
and light enough to truck and lift, from pieces the saw can cut, in an order where every panel lands on what is
already up and can be lowered straight down. Cost counts timber, pieces (three times as much for one nailed on
site as for one built into a panel) and crane lifts. The goal is a grammar that gives every house zero hard
faults, then as few soft faults as possible, then the lowest cost. Your edit is kept only if it beats the
parent on the houses shown.

What the verifier checks:
{checks}

The rules API:
{api}

Write the grammar so a framer could read it: small rules with one job each, a docstring saying what each
does, names in framing terms. Lay out guides (a grid, panel joints) before framing to them, and assign
members to panels with s.assign. Before you finish, write down up to three lessons with record_lesson: what you
tried and what it did, or what you learned about the verifier or the builder, so the proposers after you in this
search start from it. No function may have more than {max_lines} lines of code (docstrings, blank
lines and comments do not count); a grammar that breaks this is refused unseen, so split big rules. Prefer general rules over special cases; never refer to a house or opening by
its id. Members you place record the rule that placed it, and faults name those rules.

Tools: view_grammar shows the current draft with line numbers. edit_grammar replaces one exact piece of text.
write_grammar replaces the whole file. Work like a designer at a CAD station: try_on builds and verifies the draft
on one house in seconds, or a variation of it (the draft with one replacement) without changing the draft, so you
can compare ideas before committing to one; look shows you a picture of the draft or a variation on a house, the
whole frame in 3D or chosen walls, floors and roofs square on, coloured by rule, panel or faults. Look at what
you built: a frame can score well and still be wrong to the eye. To know the frame exactly, read it: frame gives
the whole house as built, or every member of one surface with where it is, what it rests on and touches, and its
faults; trace shows what one rule did, firing by firing; raw gives the house file, or a surface's members, as they
are stored. check_grammar builds and verifies the draft on all
the houses shown and returns the full reports; it can be used a limited number of times. When you are done, reply with one or two
sentences saying what you changed and why."""


def _image_block(path: Path) -> dict:
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


class Draft:
    """The grammar the proposer is editing, and the four things it can do to it. Shared by both proposers."""
    TOOLS = {
        "view_grammar": ("Show the current draft grammar with line numbers. start: first line, from 1; "
                         "end: last line, 0 for the end of the file.",
                         {"start": (int, 1), "end": (int, 0)}),
        "edit_grammar": ("Replace one exact piece of the draft grammar. old: text that occurs exactly once, "
                         "including indentation; new: what to put in its place.",
                         {"old": (str, None), "new": (str, None)}),
        "write_grammar": ("Replace the whole draft grammar. source: the complete Python file.",
                          {"source": (str, None)}),
        "check_grammar": ("Build and verify the current draft on all of this round's houses and return the full "
                          "reports. Limited uses: try ideas with try_on and look first.", {}),
        "try_on": ("Build and verify the draft on one house of this round in a few seconds, and say its score against "
                   "the parent's there and its faults by check. With old and new, try a variation instead: the draft with "
                   "that one replacement, without changing the draft, to compare ideas quickly.",
                   {"house": (str, None), "old": (str, ""), "new": (str, "")}),
        "look": ("A picture of the draft (or, with old and new, a variation) built on one house, hard faults as red "
                 "crosses. view '3d': the whole frame from two opposite corners. view 'surface': up to four walls, "
                 "floors or roofs square on (surface: their ids, comma separated; empty: those with the most faults), "
                 "prefab panels outlined. colour 'rule', 'panel' (members built on site grey) or 'faults' (members in "
                 "hard faults red, soft amber, the rest a faint ghost: where the problems are).",
                 {"house": (str, None), "view": (str, "3d"), "surface": (str, ""), "colour": (str, "rule"),
                  "old": (str, ""), "new": (str, "")}),
        "frame": ("The frame the draft builds on one house, in exact words. With no surface: every wall, floor, ceiling "
                  "and roof (kind, size, what it rests on and carries, its panels, members by rule, faults by check). With a "
                  "surface id: every member on it, one per line along it: id, role, section, rule, panel, where it is "
                  "(inches in the surface's u, v, w), what it rests on, carries and touches, and the faults it is in "
                  "(capitals: hard); rule: only that rule's members. With old and new, of a variation.",
                  {"house": (str, None), "surface": (str, ""), "rule": (str, ""), "old": (str, ""), "new": (str, "")}),
        "trace": ("What one rule of the draft did on one house, firing by firing: what it matched, and what it placed "
                  "(and where), cut, notched or removed. With old and new, of a variation.",
                  {"house": (str, None), "rule": (str, None), "old": (str, ""), "new": (str, "")}),
        "raw": ("The files as they are, untranslated. part 'house': the house file (the input the builder hands your "
                "rules: walls, floors, roofs, openings, junctions). part 'frame' with a surface id: the members the draft "
                "builds on it as the frame stores them, one JSON per line (world coordinates in inches, cuts and notches "
                "as planes, panel). With old and new, of a variation.",
                {"house": (str, None), "part": (str, "house"), "surface": (str, ""), "old": (str, ""), "new": (str, "")}),
        "record_lesson": ("Write down one short lesson for the proposers after you in this search: something you "
                          "tried and what it did, or something you learned about the verifier or the builder. One "
                          "sentence or two under 300 characters, specific enough to act on. Up to three per proposal.", {"lesson": (str, None)}),
    }
    TRIES = 16   # try_on per proposal: one house, seconds each
    LOOKS = 8    # pictures per proposal
    LESSONS = 3  # lessons per proposal
    READS = 30   # frame and trace answers per proposal

    def __init__(self, source: str, context: dict, out: Path, checks: int):
        self.src, self.context, self.out, self.limit, self.checks = source, context, out, checks, 0
        self.tries = self.looks = 0
        self.lessons: list[str] = []
        self.reads, self.answers = 0, {}
        (out / "draft.py").write_text(source)

    def event(self, kind: str, **data) -> None:
        """One line in live.jsonl: what the proposer just did, for anyone watching."""
        import time
        with open(self.out / "live.jsonl", "a") as f:
            f.write(json.dumps({"time": time.time(), "kind": kind, **data}) + "\n")

    def call(self, name: str, **kwargs) -> tuple[str, list[Path]]:
        """Run a tool, logging the call, its result and, after an edit, the new draft. Returns its text and the
        pictures it made (look makes one)."""
        brief = {k: (v if len(str(v)) <= 300 else str(v)[:300] + "...") for k, v in kwargs.items()}
        self.event("tool", tool=name, input=brief)
        result = getattr(self, name)(**kwargs)
        text, images = result if isinstance(result, tuple) else (result, [])
        self.event("result", tool=name, text=text if len(text) <= 1500 else text[:1500] + "...",
                   images=[p.name for p in images])
        if name in ("edit_grammar", "write_grammar") and not text.startswith("Not changed"):
            (self.out / "draft.py").write_text(self.src)
            self.event("draft", lines=len(self.src.splitlines()))
        return text, images

    def house_path(self, house: str) -> Path | None:
        return next((Path(p) for p, h in zip(self.context["house_paths"], self.context["houses"]) if h == house), None)

    def variant(self, old: str, new: str) -> str | None:
        """The draft, or the draft with one replacement (old must occur exactly once): None if it does not."""
        if not old:
            return self.src
        return self.src.replace(old, new) if self.src.count(old) == 1 else None

    def prepared(self, house: str, old: str, new: str, kind: str) -> tuple[Path, Path] | str:
        """The house's file and the grammar to build, written to a file; or why not, in words."""
        path = self.house_path(house)
        if path is None:
            return f"Not {kind}: {house} is not one of this round's houses ({', '.join(self.context['houses'])})."
        src = self.variant(old, new)
        if src is None:
            return f"Not {kind}: old must occur exactly once in the draft."
        big = too_big(src, self.context.get("max_lines", MAX_LINES))
        if big:
            return f"Not {kind}: " + " ".join(big)
        f = self.out / f"{kind}{self.tries + self.looks + 1}.py"
        f.write_text(src)
        return path, f

    def describe(self, house: str, old: str, new: str, args: list[str]) -> str:
        """Run `frameevolve describe` on the draft (or a variation) in its own process; answers are kept, so asking
        again about the same draft costs nothing."""
        import hashlib
        import subprocess
        import sys
        from frameevolve.search import ROOT
        src = self.variant(old, new)
        if src is None:
            return "Not read: old must occur exactly once in the draft."
        key = (hashlib.sha256(src.encode()).hexdigest(), house, *args)
        if key in self.answers:
            return self.answers[key]
        if self.reads >= self.READS:
            return f"No reads left ({self.READS} used)."
        path = self.house_path(house)
        if path is None:
            return f"Not read: {house} is not one of this round's houses ({', '.join(self.context['houses'])})."
        self.reads += 1
        f = self.out / f"read{self.reads}.py"
        f.write_text(src)
        try:
            p = subprocess.run([sys.executable, "-m", "frameevolve", "describe", str(f), str(path), *args], cwd=ROOT,
                               capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return "Not read: building it took over 3 minutes."
        text = p.stdout.strip() if p.returncode == 0 else "Not read: " + ((p.stderr.strip().splitlines() or ["no output"])[-1])
        self.answers[key] = text
        return text

    def frame(self, house: str, surface: str = "", rule: str = "", old: str = "", new: str = "") -> str:
        args = (["--surface", surface] if surface else []) + (["--rule", rule] if rule else [])
        return self.describe(house, old, new, args)

    def trace(self, house: str, rule: str, old: str = "", new: str = "") -> str:
        return self.describe(house, old, new, ["--trace", "--rule", rule])

    def raw(self, house: str, part: str = "house", surface: str = "", old: str = "", new: str = "") -> str:
        path = self.house_path(house)
        if path is None:
            return f"Not read: {house} is not one of this round's houses ({', '.join(self.context['houses'])})."
        if part == "house":
            return path.read_text()
        if part != "frame" or not surface:
            return "Not read: part is 'house', or 'frame' with a surface id."
        return self.describe(house, old, new, ["--raw", "--surface", surface])

    def record_lesson(self, lesson: str) -> str:
        lesson = " ".join(lesson.split())[:500]
        if len(self.lessons) >= self.LESSONS:
            return f"Not recorded: {self.LESSONS} lessons already."
        if not lesson:
            return "Not recorded: the lesson is empty."
        self.lessons.append(lesson)
        return f"Recorded ({len(self.lessons)} of {self.LESSONS})."

    def try_on(self, house: str, old: str = "", new: str = "") -> str:
        from collections import Counter
        from frameevolve.search import evaluate
        if self.tries >= self.TRIES:
            return f"No tries left ({self.TRIES} used). Use check_grammar, or finish."
        ready = self.prepared(house, old, new, "tried")
        if isinstance(ready, str):
            return ready
        self.tries += 1
        path, f = ready
        cache = self.context.get("cache")
        r = evaluate(f, [path], timeout=120, cache=Path(cache) if cache else None)[house]
        parent = self.context.get("parent_scores", {}).get(house)
        counts = Counter((x["check"], x["hard"]) for x in r["faults"])
        first = {}                     # one example of each kind of fault, the commonest first
        for x in r["faults"]:
            first.setdefault((x["check"], x["hard"]), x)
        worst = [first[k] for k, _ in counts.most_common()][:8]
        return "\n".join([
            f"Try {self.tries} of {self.TRIES} on {house}" + (" (a variation; the draft is unchanged)" if old else "")
            + f": {_score(r['score'])}" + (f"; the parent there: {_score(parent)}" if parent else "") + ".",
            "Faults: " + (", ".join(f"{c} {n}{'' if h else ' (soft)'}" for (c, h), n in counts.most_common()) or "none") + ".",
            *[f"  - {x['message']}" for x in worst]])

    def look(self, house: str, view: str = "3d", surface: str = "", colour: str = "rule", old: str = "",
             new: str = "") -> tuple[str, list[Path]] | str:
        import subprocess
        import sys
        from frameevolve.search import ROOT
        if self.looks >= self.LOOKS:
            return f"No pictures left ({self.LOOKS} used)."
        if view not in ("3d", "surface") or colour not in ("rule", "panel", "faults"):
            return "Not drawn: view is '3d' or 'surface', colour 'rule', 'panel' or 'faults'."
        ready = self.prepared(house, old, new, "drawn")
        if isinstance(ready, str):
            return ready
        self.looks += 1
        path, f = ready
        png = self.out / f"look{self.looks}.png"
        cmd = [sys.executable, "-m", "frameevolve", "look", str(f), str(path), "--out", str(png), "--view", view,
               "--colour", colour]
        if surface.strip():
            cmd += ["--surface", *[x.strip() for x in surface.split(",") if x.strip()][:4]]
        try:
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return "Not drawn: building it took over 3 minutes."
        if p.returncode != 0 or not png.exists():
            return "Not drawn: " + ((p.stderr.strip().splitlines() or ["no output"])[-1])
        info = json.loads(p.stdout)
        return (f"Picture {self.looks} of {self.LOOKS}: {house}, {view}, coloured by {colour}"
                + (" (a variation; the draft is unchanged)" if old else "") + f"; it scores {_score(info['score'])}"
                + (f"; rule errors: {info['errors']}" if info["errors"] else "") + "."), [png]

    def view_grammar(self, start: int = 1, end: int = 0) -> str:
        lines = self.src.splitlines()
        end = end or len(lines)
        return "\n".join(f"{i:4d}  {lines[i - 1]}" for i in range(max(1, start), min(end, len(lines)) + 1))

    def edit_grammar(self, old: str, new: str) -> str:
        n = self.src.count(old)
        if n != 1:
            return f"Not changed: that text occurs {n} times in the draft; it must occur exactly once."
        self.src = self.src.replace(old, new)
        return "Changed."

    def write_grammar(self, source: str) -> str:
        self.src = source
        return f"Draft replaced, {len(source.splitlines())} lines."

    def check_grammar(self) -> str:
        from frameevolve.search import evaluate
        if self.checks >= self.limit:
            return f"No checks left ({self.limit} used). Finish with what you have."
        self.checks += 1
        big = too_big(self.src, self.context.get("max_lines", MAX_LINES))
        if big:
            return (f"Check {self.checks} of {self.limit}: refused before building, because "
                    + " ".join(big))
        path = self.out / "check.py"
        path.write_text(self.src)
        cache = self.context.get("cache")
        res = evaluate(path, [Path(h) for h in self.context["house_paths"]], cache=Path(cache) if cache else None)
        total = [sum(r["score"][j] for r in res.values()) for j in range(3)]
        return (f"Check {self.checks} of {self.limit}. Total over these houses: {total[0]} hard, {total[1]} soft, "
                f"cost {total[2]:.1f} (parent: {self.context['parent_batch']}).\n\n"
                + "\n\n".join(r["text"] for r in res.values()))


def _score(s) -> str:
    return f"{s[0]} hard, {s[1]} soft, cost {s[2]:.1f}"


def overviews_text(overviews: dict[str, str]) -> str:
    """The parent's frame on each of this round's houses, surface by surface: the whole house in view. Each
    surface's members in full, and what each rule did, come from the frame and trace tools."""
    if not any(overviews.values()):
        return ""
    return ("The parent's frame on each of these houses, surface by surface (capital faults are hard; read any "
            "surface member by member with the frame tool):\n\n" + "\n\n".join(t for t in overviews.values() if t) + "\n\n")


def notebook_text(notebook: list[dict]) -> str:
    """The run's notebook: what earlier proposers in this search learned, newest last, with how each came out."""
    if not notebook:
        return ""
    lines = ["Lessons the proposers before you in this search wrote down, newest last, with how their iteration came "
             "out (a lesson from an edit that was not kept can still be true):"]
    for n in notebook:
        if n["accepted"]:
            how = f"kept, {n['parent_batch'][0]} -> {n['child_batch'][0]} hard"
        elif n.get("error"):
            how = f"refused: {n['error'][:80]}"
        else:
            how = "not kept: not better" + (f", {n['parent_batch'][0]} -> {n['child_batch'][0]} hard"
                                             if n.get("child_batch") else "")
        lines.append(f"- iteration {n['iteration']} ({how}): {n['lesson']}")
    return "\n".join(lines) + "\n\n"


def rejected_text(rejected: list[dict]) -> str:
    """Earlier children of this parent that were not kept, so the proposer tries something else."""
    if not rejected:
        return ""
    lines = ["Earlier edits to this parent that were not kept (try something different, or fix what went wrong):"]
    for r in rejected:
        why = r["error"] or (f"not better on its houses: {_score(r['child_batch'])} against the parent's "
                             f"{_score(r['parent_batch'])}" if r.get("child_batch") else "not better")
        note = " ".join((r.get("note") or "").split())
        lines.append(f"- iteration {r['iteration']}: {why}." + (f" Its note: {note}" if note else ""))
    return "\n".join(lines) + "\n\n"


def inspirations_text(insp: list[dict]) -> str:
    """Other grammars from the Pareto set that do better than the parent somewhere: ideas to borrow."""
    if not insp:
        return ""
    parts = ["Other grammars from the search do better than the parent on some houses. Their code is below for "
             "ideas; borrow what fits into the parent's rules, do not paste a whole grammar."]
    for i in insp:
        where = (f"better than the parent on training houses {', '.join(i['better_on'])}" if i["better_on"]
                 else "better than the parent on houses you do not see")
        note = " ".join((i.get("note") or "").split())
        parts.append(f"## {i['id']}: {where}; total on training houses {_score(i['total'])}."
                     + (f"\nIts author's note: {note}" if note else "")
                     + f"\n```python\n{i['source'].rstrip()}\n```")
    return "\n\n".join(parts) + "\n\n"


def prompt(context: dict, images: bool, out: Path) -> tuple[str, list[dict]]:
    """The system prompt and the first message's content (text, then the pictures). Saved to prompt.md."""
    reports = "\n\n".join(context["reports"].values())
    scores = "\n".join(f"  {h}: {s[0]} hard, {s[1]} soft, cost {s[2]:.1f}" for h, s in context["parent_scores"].items())
    pb = context["parent_batch"]
    text = (f"The parent grammar is {context['parent']}. Its scores on every training house:\n{scores}\n\n"
            f"These houses are this round's test: {', '.join(context['houses'])}. The parent's total on them is "
            f"{pb[0]} hard, {pb[1]} soft, cost {pb[2]:.1f}. Their reports:\n\n{reports}\n\n"
            + ("For each house, in the order above, two pictures with red crosses marking hard faults: first the whole "
               "frame in 3D from two opposite corners, showing only the members in faults (hard red, soft amber; the "
               "rest a faint ghost), then the surfaces with the most faults square on, members coloured by rule and "
               "prefab panels outlined, where red hatching marks boards with nothing behind them.\n\n" if images else "")
            + overviews_text(context.get("overviews", {}))
            + notebook_text(context.get("notebook", []))
            + rejected_text(context.get("rejected", []))
            + inspirations_text(context.get("inspirations", []))
            + "Read the grammar with view_grammar, then improve it.")
    content = [{"type": "text", "text": text}]
    if images:
        content += [_image_block(Path(p)) for p in context["images"]]
    system = SYSTEM.format(checks="\n".join(f"- {k}: {v}" for k, v in CHECKS.items()), api=api_reference(),
                           max_lines=context.get("max_lines", MAX_LINES))
    (out / "prompt.md").write_text(f"# System\n\n{system}\n\n# User\n\n{text}\n")
    return system, content


class ClaudeProposer:
    """Claude through the Anthropic API (an API key or an `ant auth login` profile)."""

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "medium", checks: int = 3,
                 max_turns: int = MAX_TURNS, images: bool = True, fallbacks: bool = True):
        self.model, self.effort, self.checks = model, effort, checks
        self.max_turns, self.images, self.fallbacks = max_turns, images, fallbacks

    def propose(self, source: str, context: dict, out: Path) -> Proposal:
        import anthropic
        from anthropic.lib.tools import BetaFunctionTool

        draft = Draft(source, context, out, self.checks)
        def bound(name):
            def run(**kwargs):
                text, images = draft.call(name, **kwargs)
                return [{"type": "text", "text": text}, *[_image_block(p) for p in images]] if images else text
            return run
        tools = [BetaFunctionTool(bound(name), name=name, description=desc,
                                  input_schema=_schema(params)) for name, (desc, params) in Draft.TOOLS.items()]
        system, content = prompt(context, self.images, out)
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if self.fallbacks else {}
        runner = anthropic.Anthropic().beta.messages.tool_runner(
            model=self.model, max_tokens=16000, system=system, messages=[{"role": "user", "content": content}],
            tools=tools, max_iterations=self.max_turns, output_config={"effort": self.effort}, **extra)
        transcript, usage, last = [], {"input_tokens": 0, "output_tokens": 0, "turns": 0}, None
        draft.event("start", model=self.model, effort=self.effort, via="api")
        for message in runner:
            last = message
            transcript.append(message.to_dict())
            for b in message.content:
                if b.type == "text" and b.text.strip():
                    draft.event("say", text=b.text.strip())
            usage["turns"] += 1
            usage["input_tokens"] += message.usage.input_tokens
            usage["output_tokens"] += message.usage.output_tokens
        (out / "transcript.json").write_text(json.dumps(transcript, indent=1, default=str))
        if last is None:
            raise RuntimeError("Claude returned nothing")
        if last.stop_reason == "refusal":
            raise RuntimeError("Claude declined the request")
        note = " ".join(b.text for b in last.content if b.type == "text").strip()
        usage.update(checks=draft.checks, tries=draft.tries, looks=draft.looks)
        return Proposal(draft.src, note[:2000], usage, draft.lessons)


def find_claude() -> str | None:
    """The Claude Code program: CLAUDE_CLI, `claude` on the path, or the one inside the Claude desktop app."""
    import glob
    import os
    import shutil
    if os.environ.get("CLAUDE_CLI"):
        return os.environ["CLAUDE_CLI"]
    home = os.path.expanduser("~")
    return shutil.which("claude") or (sorted(glob.glob(f"{home}/.claude/local/claude"))
                                      + sorted(glob.glob(f"{home}/Library/Application Support/Claude/claude-code/*/*/"
                                                         "claude.app/Contents/MacOS/claude")) or [None])[-1]


class ClaudeCodeProposer:
    """Claude through Claude Code (the Claude Agent SDK), signed in with a Claude subscription."""

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "medium", checks: int = 3,
                 max_turns: int = MAX_TURNS, images: bool = True):
        self.model, self.effort, self.checks = model, effort, checks
        self.max_turns, self.images = max_turns, images

    def propose(self, source: str, context: dict, out: Path) -> Proposal:
        import asyncio
        return asyncio.run(self._propose(source, context, out))

    async def _propose(self, source: str, context: dict, out: Path) -> Proposal:
        import asyncio
        from dataclasses import asdict, is_dataclass

        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolUseBlock,
                                      create_sdk_mcp_server, query, tool)

        cli = find_claude()
        if not cli:
            raise RuntimeError("Claude Code not found: install it, or set CLAUDE_CLI to its path")
        draft = Draft(source, context, out, self.checks)

        def wrap(name, desc, params):
            async def run(args):
                kwargs = {k: args[k] for k in params if k in args}
                text, images = await asyncio.to_thread(draft.call, name, **kwargs)
                pics = [{"type": "image", "data": base64.standard_b64encode(p.read_bytes()).decode(),
                         "mimeType": "image/png"} for p in images]
                return {"content": [{"type": "text", "text": text}, *pics]}
            return tool(name, desc, _schema(params))(run)

        server = create_sdk_mcp_server("grammar", tools=[wrap(n, d, p) for n, (d, p) in Draft.TOOLS.items()])
        system, content = prompt(context, self.images, out)
        options = ClaudeAgentOptions(
            system_prompt=system, mcp_servers={"grammar": server}, strict_mcp_config=True, tools=[],
            allowed_tools=[f"mcp__grammar__{n}" for n in Draft.TOOLS], setting_sources=[],
            env={"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}, cwd=str(out), cli_path=cli,
            model=self.model, effort=self.effort, max_turns=self.max_turns)

        async def message():
            yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}

        transcript, pending, result, out_of_turns = [], [], None, False
        draft.event("start", model=self.model, effort=self.effort, via="subscription")
        try:
            async for m in query(prompt=message(), options=options):
                transcript.append(asdict(m) if is_dataclass(m) else str(m))
                if isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, ToolUseBlock):
                            pending = []            # text before a tool call is thinking aloud
                        elif isinstance(b, TextBlock) and b.text.strip():
                            pending.append(b.text.strip())
                            draft.event("say", text=b.text.strip())
                elif isinstance(m, ResultMessage):
                    result = m
        except Exception as e:      # out of turns: propose the draft as it stands rather than lose it
            if "maximum number of turns" not in str(e):
                raise
            out_of_turns = True
        (out / "transcript.json").write_text(json.dumps(transcript, indent=1, default=str))
        if out_of_turns or (result is not None and result.is_error and "max_turns" in str(result.subtype)):
            pending = [f"(Ran out of turns; this is the draft as it stood.) {' '.join(pending)}"]
            draft.event("say", text="ran out of turns: the draft as it stands is the proposal")
            if result is None or result.is_error:
                return Proposal(draft.src, " ".join(pending)[:2000], {"turns": self.max_turns, "checks": draft.checks,
                                                                      "tries": draft.tries, "looks": draft.looks},
                                draft.lessons)
        if result is None:
            raise RuntimeError("Claude Code returned nothing")
        if result.is_error:
            err = result.result or result.subtype
            raise RuntimeError(("Claude Code is not signed in: run it once and use /login. " if "login" in str(err).lower()
                                else "") + f"Claude Code error: {err}")
        u = result.usage or {}
        usage = {"input_tokens": sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                                   "cache_creation_input_tokens")),
                 "output_tokens": int(u.get("output_tokens") or 0), "turns": result.num_turns,
                 "seconds": round((result.duration_ms or 0) / 1000, 1), "checks": draft.checks,
                 "tries": draft.tries, "looks": draft.looks}
        return Proposal(draft.src, " ".join(pending)[:2000], usage, draft.lessons)


def _schema(params: dict) -> dict:
    kinds = {int: "integer", str: "string"}
    return {"type": "object", "additionalProperties": False,
            "properties": {k: {"type": kinds[t]} for k, (t, _) in params.items()},
            "required": [k for k, (_, default) in params.items() if default is None]}
