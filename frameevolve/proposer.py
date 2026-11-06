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
from frameevolve.builder import MAX_LINES, State, too_big
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
    import frameevolve.builder as builder
    doc = inspect.getdoc(builder)
    lines += [doc[doc.index("A grammar is"):doc.index("Coordinates in rules")].strip(), ""]
    for name in ["place", "remove", "members", "local", "bears_on", "carries", "beside", "gaps", "below",
                 "above", "free"]:
        fn = getattr(State, name)
        doc = " ".join((inspect.getdoc(fn) or "").split())
        lines.append(f"s.{name}{inspect.signature(fn)}".replace("self, ", "").replace("(self)", "()") + f": {doc}")
    lines += ["", "A gap from s.gaps() has u0, u1, v0, v1, face and kind 'edge' or 'field'.",
              "Import with `from frameevolve.builder import rule`."]
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
does, names in framing terms. No function may have more than {max_lines} lines of code (docstrings, blank
lines and comments do not count); a grammar that breaks this is refused unseen, so split big rules. Prefer general rules over special cases; never refer to a house or opening by
its id. Members you place record the rule that placed it, and faults name those rules.

Tools: view_grammar shows the current draft with line numbers. edit_grammar replaces one exact piece of text.
write_grammar replaces the whole file. check_grammar builds and verifies your draft on the houses shown and
returns the reports; it can be used a limited number of times. When you are done, reply with one or two
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
        "check_grammar": ("Build and verify the current draft on this round's houses and return the reports. "
                          "Limited uses.", {}),
    }

    def __init__(self, source: str, context: dict, out: Path, checks: int):
        self.src, self.context, self.out, self.limit, self.checks = source, context, out, checks, 0
        (out / "draft.py").write_text(source)

    def event(self, kind: str, **data) -> None:
        """One line in live.jsonl: what the proposer just did, for anyone watching."""
        import time
        with open(self.out / "live.jsonl", "a") as f:
            f.write(json.dumps({"time": time.time(), "kind": kind, **data}) + "\n")

    def call(self, name: str, **kwargs) -> str:
        """Run a tool, logging the call, its result and, after an edit, the new draft."""
        brief = {k: (v if len(str(v)) <= 300 else str(v)[:300] + "...") for k, v in kwargs.items()}
        self.event("tool", tool=name, input=brief)
        result = getattr(self, name)(**kwargs)
        self.event("result", tool=name, text=result if len(result) <= 1500 else result[:1500] + "...")
        if name in ("edit_grammar", "write_grammar") and not result.startswith("Not changed"):
            (self.out / "draft.py").write_text(self.src)
            self.event("draft", lines=len(self.src.splitlines()))
        return result

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
            + ("The pictures show each wall from outside, coloured by rule; red crosses mark hard faults and red "
               "hatching marks sheathing with nothing behind it.\n\n" if images else "")
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

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium", checks: int = 3,
                 max_turns: int = 24, images: bool = True, fallbacks: bool = True):
        self.model, self.effort, self.checks = model, effort, checks
        self.max_turns, self.images, self.fallbacks = max_turns, images, fallbacks

    def propose(self, source: str, context: dict, out: Path) -> Proposal:
        import anthropic
        from anthropic.lib.tools import BetaFunctionTool

        draft = Draft(source, context, out, self.checks)
        def bound(name):
            def run(**kwargs):
                return draft.call(name, **kwargs)
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
        usage["checks"] = draft.checks
        return Proposal(draft.src, note[:2000], usage)


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

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium", checks: int = 3,
                 max_turns: int = 24, images: bool = True):
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
                text = await asyncio.to_thread(draft.call, name, **kwargs)
                return {"content": [{"type": "text", "text": text}]}
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

        transcript, pending, result = [], [], None
        draft.event("start", model=self.model, effort=self.effort, via="subscription")
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
        (out / "transcript.json").write_text(json.dumps(transcript, indent=1, default=str))
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
                 "seconds": round((result.duration_ms or 0) / 1000, 1), "checks": draft.checks}
        return Proposal(draft.src, " ".join(pending)[:2000], usage)


def _schema(params: dict) -> dict:
    kinds = {int: "integer", str: "string"}
    return {"type": "object", "additionalProperties": False,
            "properties": {k: {"type": kinds[t]} for k, (t, _) in params.items()},
            "required": [k for k, (_, default) in params.items() if default is None]}
