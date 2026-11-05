"""Proposers: what turns a parent grammar and its reports into a child grammar.

ClaudeProposer is the real one: a Claude agent that sees the parent grammar, the verifier's reports and
elevations with the faults marked, and edits the grammar with a few small tools. ScriptedProposer applies
a fixed function, for testing the search without calling Claude.
"""
from __future__ import annotations

import base64
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from frameevolve import surface
from frameevolve.builder import State
from frameevolve.model import SECTIONS, STOCK, Opening, Wall
from frameevolve.verifier import CHECKS


@dataclass
class Proposal:
    source: str
    note: str = ""
    usage: dict = field(default_factory=dict)


class ScriptedProposer:
    """Applies edit(source, context) -> (source, note). For tests and dry runs."""

    def __init__(self, edit: Callable[[str, dict], tuple[str, str]]):
        self.edit = edit

    def propose(self, source: str, context: dict, out: Path) -> Proposal:
        src, note = self.edit(source, context)
        return Proposal(src, note)


def api_reference() -> str:
    """What a rule can call on `s`, written from the builder's own signatures and docstrings."""
    lines = ["Rules receive `s`, the design state for one wall. Units are inches. Coordinates on a wall: u along it "
             "from its start, v up from its base, w inward from its outer face.",
             "",
             "s.wall: the current wall, with id, length, height, base, role, openings, start_meets, end_meets "
             "(the id of the wall meeting this one at its start or end, or None).",
             "Each opening has id, kind ('window' or 'door'), u0, u1, v0, v1, width, height.",
             "s.house.walls: every wall. s.SECTIONS (nominal name: actual size): "
             + ", ".join(f"{k} ({w:g} x {d:g})" for k, (w, d) in SECTIONS.items())
             + f". s.STOCK: stock lengths {', '.join(map(str, STOCK))} (8 to 20 ft).",
             "A member has id, section, rule, surface (its wall id), role (a free label), length, box (lo, hi world corners).",
             ""]
    for name in ["place", "remove", "once", "members", "local", "bears_on", "carries", "beside", "gaps", "below",
                 "above", "free"]:
        fn = getattr(State, name)
        doc = " ".join((inspect.getdoc(fn) or "").split())
        lines.append(f"s.{name}{inspect.signature(fn)}".replace("self, ", "").replace("(self)", "()") + f": {doc}")
    lines += ["", "A gap from s.gaps() has u0, u1, v0, v1 and kind 'edge' or 'field'.",
              "Mark a rule with @rule(priority) from frameevolve.builder. Lower priority runs first in every pass. "
              "Each pass calls every rule on every wall; building stops when a pass changes nothing."]
    return "\n".join(lines)


SYSTEM = """You improve a grammar: a Python file of small rules that frames the timber walls of houses.

The builder applies the grammar to a house. A deterministic verifier then checks the frame and scores it as
(hard faults, soft faults, cost), compared in that order. The goal is a grammar that gives every house zero
hard faults, then as few soft faults as possible, then the lowest cost. Your edit is kept only if it beats the
parent on the houses shown.

What the verifier checks:
{checks}

The rules API:
{api}

Write the grammar so a framer could read it: small rules with one job each, a docstring saying what each
does, names in framing terms. Prefer general rules over special cases; never refer to a house or opening by
its id. Members you place record the rule that placed it, and faults name those rules.

Tools: view_grammar shows the current draft with line numbers. edit_grammar replaces one exact piece of text.
write_grammar replaces the whole file. check_grammar builds and verifies your draft on the houses shown and
returns the reports; it can be used a limited number of times. When you are done, reply with one or two
sentences saying what you changed and why."""


def _image_block(path: Path) -> dict:
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


class ClaudeProposer:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium", checks: int = 3,
                 max_turns: int = 24, images: bool = True, fallbacks: bool = True):
        self.model = model
        self.effort = effort
        self.checks = checks
        self.max_turns = max_turns
        self.images = images
        self.fallbacks = fallbacks

    def propose(self, source: str, context: dict, out: Path) -> Proposal:
        import anthropic
        from anthropic import beta_tool

        from frameevolve.search import evaluate

        draft = {"src": source, "checks": 0}
        draft_path = out / "draft.py"
        houses = [Path(p) for p in context.get("house_paths", [])]

        @beta_tool
        def view_grammar(start: int = 1, end: int = 0) -> str:
            """Show the current draft grammar with line numbers.

            Args:
                start: first line to show, from 1.
                end: last line to show; 0 means the end of the file.
            """
            lines = draft["src"].splitlines()
            end = end or len(lines)
            return "\n".join(f"{i:4d}  {lines[i - 1]}" for i in range(max(1, start), min(end, len(lines)) + 1))

        @beta_tool
        def edit_grammar(old: str, new: str) -> str:
            """Replace one exact piece of the draft grammar with new text.

            Args:
                old: text that occurs exactly once in the draft, including indentation.
                new: the text to put in its place.
            """
            n = draft["src"].count(old)
            if n != 1:
                return f"Not changed: that text occurs {n} times in the draft; it must occur exactly once."
            draft["src"] = draft["src"].replace(old, new)
            return "Changed."

        @beta_tool
        def write_grammar(source: str) -> str:
            """Replace the whole draft grammar.

            Args:
                source: the complete Python file.
            """
            draft["src"] = source
            return f"Draft replaced, {len(source.splitlines())} lines."

        @beta_tool
        def check_grammar() -> str:
            """Build and verify the current draft on the houses shown, and return the reports."""
            if draft["checks"] >= self.checks:
                return f"No checks left ({self.checks} used). Finish with what you have."
            draft["checks"] += 1
            draft_path.write_text(draft["src"])
            res = evaluate(draft_path, houses)
            total = [sum(r["score"][j] for r in res.values()) for j in range(3)]
            return (f"Check {draft['checks']} of {self.checks}. Total over these houses: {total[0]} hard, "
                    f"{total[1]} soft, cost {total[2]:.1f} (parent: {context['parent_batch']}).\n\n"
                    + "\n\n".join(r["text"] for r in res.values()))

        reports = "\n\n".join(context["reports"].values())
        scores = "\n".join(f"  {h}: {s[0]} hard, {s[1]} soft, cost {s[2]:.1f}"
                           for h, s in context["parent_scores"].items())
        text = (f"The parent grammar is {context['parent']}. Its scores on every training house:\n{scores}\n\n"
                f"These houses are this round's test: {', '.join(context['houses'])}. The parent's total on them is "
                f"{context['parent_batch'][0]} hard, {context['parent_batch'][1]} soft, cost "
                f"{context['parent_batch'][2]:.1f}. Their reports:\n\n{reports}\n\n"
                + ("The pictures show each wall from outside, coloured by rule; red crosses mark hard faults and "
                   "red hatching marks sheathing with nothing behind it.\n\n" if self.images else "")
                + "Read the grammar with view_grammar, then improve it.")
        content = [{"type": "text", "text": text}]
        if self.images:
            content += [_image_block(Path(p)) for p in context["images"]]
        system = SYSTEM.format(checks="\n".join(f"- {k}: {v}" for k, v in CHECKS.items()), api=api_reference())
        (out / "prompt.md").write_text(f"# System\n\n{system}\n\n# User\n\n{text}\n")

        client = anthropic.Anthropic()
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if self.fallbacks else {}
        runner = client.beta.messages.tool_runner(
            model=self.model, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": content}],
            tools=[view_grammar, edit_grammar, write_grammar, check_grammar],
            max_iterations=self.max_turns, output_config={"effort": self.effort}, **extra,
        )
        transcript, usage, last = [], {"input_tokens": 0, "output_tokens": 0, "turns": 0}, None
        for message in runner:
            last = message
            transcript.append(message.to_dict())
            usage["turns"] += 1
            usage["input_tokens"] += message.usage.input_tokens
            usage["output_tokens"] += message.usage.output_tokens
        (out / "transcript.json").write_text(json.dumps(transcript, indent=1, default=str))
        if last is None:
            raise RuntimeError("Claude returned nothing")
        if last.stop_reason == "refusal":
            raise RuntimeError("Claude declined the request")
        note = " ".join(b.text for b in last.content if b.type == "text").strip()
        usage["checks"] = draft["checks"]
        return Proposal(draft["src"], note[:2000], usage)
