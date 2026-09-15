# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

from giljo_mcp.models import AgentTemplate
from tests.helpers.retired_tool_names import RETIRED_TOOL_NAMES


_SCAN_ROOTS = ("src", "api")

_REPO_ROOT = Path(__file__).resolve().parents[2]

_LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "log"})

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")

_LABEL_KEYS = frozenset({"method", "operation"})


def _live_tool_names() -> set[str]:
    from api.endpoints.mcp_tools import mcp

    return {tool.name for tool in asyncio.run(mcp.list_tools())}


def _qualified_pattern() -> re.Pattern[str]:
    from giljo_mcp.branding import MCP_ALIAS

    return re.compile(rf"mcp__{re.escape(MCP_ALIAS)}__([a-z_][a-z0-9_]*)")


def _prose_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))

    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            skip.add(id(node.value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _LOG_METHODS:
            for arg in ast.walk(node):
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    skip.add(id(arg))

    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in skip:
            continue
        if not any(ch.isspace() for ch in node.value):
            continue
        out.append((node.lineno, node.value))
    return out


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        files.extend(sorted((_REPO_ROOT / root).rglob("*.py")))
    return files




def test_orchestrator_toolsearch_bundle_names_only_live_tools() -> None:
    from giljo_mcp.branding import MCP_ALIAS
    from giljo_mcp.prompts._canonical_tool_list import CANONICAL_ORCHESTRATOR_TOOLS

    live = _live_tool_names()
    prefix = f"mcp__{MCP_ALIAS}__"

    stale = []
    for entry in CANONICAL_ORCHESTRATOR_TOOLS:
        assert entry.startswith(prefix), f"{entry!r} is not a {prefix}* tool reference"
        name = entry[len(prefix) :]
        if name not in live:
            stale.append(f"  {entry} -> {RETIRED_TOOL_NAMES.get(name, 'no such tool')}")

    assert not stale, (
        "CANONICAL_ORCHESTRATOR_TOOLS names tools that are not registered:\n"
        + "\n".join(stale)
        + "\n\nThis tuple renders into the STEP 0 TOOLSEARCH BOOTSTRAP every staged orchestrator "
        "runs as its first action. ToolSearch returns silence for an unknown name, so the agent "
        "boots without the schema and only finds out when it tries to call the tool -- at closeout."
    )


def test_get_job_mission_tool_roster_names_only_live_tools() -> None:
    from giljo_mcp.services.mission_orchestration_service import ORCHESTRATOR_AVAILABLE_TOOLS

    live = _live_tool_names()
    stale = [
        f"  {name} -> {RETIRED_TOOL_NAMES.get(name, 'no such tool')}"
        for name in ORCHESTRATOR_AVAILABLE_TOOLS
        if name not in live
    ]

    assert not stale, (
        "get_job_mission advertises tools that are not registered:\n"
        + "\n".join(stale)
        + "\n\nThis roster is handed to the orchestrator as its awareness list."
    )


def test_boot_banner_rename_targets_are_live_tools() -> None:
    from api.startup.background_tasks import TOOL_RENAME_NOTICE_PAIRS

    live = _live_tool_names()
    dead: list[str] = []
    for pair in TOOL_RENAME_NOTICE_PAIRS:
        _old, _, target = pair.partition("\u2192")
        assert target.strip(), f"rename pair {pair!r} has no target side"
        if not any(token in live for token in _IDENTIFIER.findall(target)):
            dead.append(f"  {pair.strip()}  <- the target names no live tool")

    assert not dead, (
        "The CE tool-rename boot banner points self-hosters at tools that do not exist:\n"
        + "\n".join(dead)
        + "\n\nThis banner is customer-facing copy shown on a fresh install's first three "
        "boots. A row whose target is gone is worse than no row: the reader goes looking "
        "for it. Correct the TARGET (the left side is history and stays as it is)."
    )




def test_no_prose_names_an_unregistered_prefixed_tool() -> None:
    live = _live_tool_names()
    pattern = _qualified_pattern()

    hits: list[str] = []
    for path in _scanned_files():
        for lineno, text in _prose_literals(path):
            for match in pattern.finditer(text):
                if match.group(1) not in live:
                    rel = path.relative_to(_REPO_ROOT)
                    hits.append(f"  {rel}:{lineno}: names {match.group(0)}, which is not registered")

    assert not hits, "Agent-facing prose names unregistered tools:\n" + "\n".join(sorted(set(hits)))




def test_no_agent_facing_prose_names_a_retired_tool() -> None:
    live = _live_tool_names()
    patterns = {name: re.compile(rf"\b{re.escape(name)}\b") for name in RETIRED_TOOL_NAMES if name not in live}

    hits: list[str] = []
    for path in _scanned_files():
        for lineno, text in _prose_literals(path):
            for name, pattern in patterns.items():
                if pattern.search(text):
                    rel = path.relative_to(_REPO_ROOT)
                    hits.append(f"  {rel}:{lineno}: names retired {name!r} -> call {RETIRED_TOOL_NAMES[name]}")

    assert not hits, (
        "Agent-facing prose names retired tools:\n"
        + "\n".join(sorted(set(hits)))
        + "\n\nCarry the ARGUMENTS across, not just the name: await_my_turn(agent_id) became "
        "get_my_turn(agent_id, wait_seconds=45), and a sweep that renamed it without wait_seconds "
        "told agents to park on a call that returns instantly.\n"
        "If the hit is the accessor layer rather than agent prose, it should already be excluded "
        "(docstring, logger argument, or a whitespace-free literal) -- if it is not, the string is "
        "shaped like an instruction and should be read as one."
    )




def test_every_retired_key_is_actually_retired() -> None:
    live = _live_tool_names()
    resurrected = [
        f"  {name!r} is a LIVE tool but is listed as retired (replacement: {replacement})"
        for name, replacement in RETIRED_TOOL_NAMES.items()
        if name in live
    ]

    assert not resurrected, (
        "RETIRED_TOOL_NAMES contains live tool names:\n"
        + "\n".join(resurrected)
        + "\n\nEvery such entry is skipped by the prose guards, so the map reads like coverage "
        "while checking nothing. If a rename sweep touched this file, it rewrote the KEYS -- the "
        "keys are the OLD names and must stay that way. If a name genuinely came back as a tool, "
        "delete its row."
    )


def test_every_replacement_names_a_live_tool() -> None:
    live = _live_tool_names()
    broken = [
        f"  {name!r} -> {replacement!r} names no live tool"
        for name, replacement in RETIRED_TOOL_NAMES.items()
        if not any(token in live for token in _IDENTIFIER.findall(replacement))
    ]

    assert not broken, "RETIRED_TOOL_NAMES replacements do not resolve:\n" + "\n".join(broken)




def _former_tool_names() -> set[str]:
    from api.startup.background_tasks import TOOL_RENAME_NOTICE_PAIRS

    names = set(RETIRED_TOOL_NAMES)
    for pair in TOOL_RENAME_NOTICE_PAIRS:
        old, _, _new = pair.partition("\u2192")
        names.update(_IDENTIFIER.findall(old))
    return names - _live_tool_names()


def test_no_error_label_is_a_bare_dead_tool_name() -> None:
    dead = _former_tool_names()
    if not dead:  # pragma: no cover - only if every retired name came back
        return

    hits: list[str] = []
    for path in _scanned_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            found: list[str] = []
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=False):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value in _LABEL_KEYS
                        and isinstance(value, ast.Constant)
                        and value.value in dead
                    ):
                        found.append(value.value)
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _LABEL_KEYS and isinstance(kw.value, ast.Constant) and kw.value.value in dead:
                        found.append(kw.value.value)
            for name in found:
                rel = path.relative_to(_REPO_ROOT)
                hits.append(f"  {rel}:{node.lineno}: label {name!r} reads as a tool an agent could call")

    assert not hits, (
        "Error-context labels name bare dead tools, and these strings reach the agent:\n"
        + "\n".join(sorted(set(hits)))
        + "\n\nDo NOT rename the underlying method -- the accessor layer is the single "
        "writer and BE-9554 deliberately left it alone. Qualify the LABEL instead "
        "(service.<name> / accessor.<name>), which keeps it accurate for an operator "
        "reading logs while no longer reading as a callable tool."
    )




def _iter_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _iter_strings(v)


_MCP_TOKEN_RE = re.compile(r"\bmcp_{1,2}[a-z][a-z0-9_]*")


def _renderer_output_problems(text: str, alias: str, live: set[str]) -> list[str]:
    problems: list[str] = []

    for name in RETIRED_TOOL_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", text):
            problems.append(f"names retired {name!r} directly (replacement: {RETIRED_TOOL_NAMES[name]})")

    brand_root = alias.split("_", 1)[0]
    claude_prefix = f"mcp__{alias}__"
    gemini_prefix = f"mcp_{alias}_"
    for token in _MCP_TOKEN_RE.findall(text):
        if brand_root not in token:
            continue
        if token.startswith(claude_prefix):
            name = token[len(claude_prefix) :]
        elif token.startswith(gemini_prefix):
            name = token[len(gemini_prefix) :]
        else:
            problems.append(f"names {token!r}, which does not carry the live alias {alias!r}")
            continue
        if name not in live:
            replacement = RETIRED_TOOL_NAMES.get(name, "no such tool")
            problems.append(f"names {token!r} -> {name!r}, which is not registered (replacement: {replacement})")

    return problems


def _make_probe_template() -> AgentTemplate:
    return AgentTemplate(
        name="probe-implementer",
        role="implementer",
        cli_tool="claude",
        description="Probe template for the BE-9567 renderer-output guard.",
        system_instructions="You are a probe agent.",
        user_instructions="Do the probe thing.",
        model="sonnet",
        background_color="#3498DB",
        behavioral_rules=["Follow patterns"],
        success_criteria=["Tests pass"],
    )


def _layer_f_renderers() -> dict[str, object]:
    from giljo_mcp import template_renderer as tr
    from giljo_mcp.services.mission_assembly import compose_agent_profile

    return {"profile": lambda template: tr.render_profile_markdown(compose_agent_profile(template))}


def test_no_renderer_output_names_a_retired_or_unresolved_tool() -> None:
    from giljo_mcp.branding import MCP_ALIAS

    live = _live_tool_names()
    template = _make_probe_template()

    hits: list[str] = []
    for platform, renderer in _layer_f_renderers().items():
        rendered = renderer(template)
        for text in _iter_strings(rendered):
            for problem in _renderer_output_problems(text, MCP_ALIAS, live):
                hits.append(f"  render_{platform} output {problem}")

    assert not hits, "A renderer's OUTPUT names a retired or unresolved tool:\n" + "\n".join(sorted(set(hits)))


def test_layer_f_scanner_fires_on_a_known_bad_render() -> None:
    from giljo_mcp.branding import MCP_ALIAS

    live = _live_tool_names()

    def _broken_dict_renderer(_template: object) -> dict[str, object]:
        return {
            "config": {
                "tools": [
                    "resolve_reactivation",
                    "mcp_giljo_mcp_health_check",
                    f"mcp_{MCP_ALIAS}_resolve_reactivation",
                    f"mcp_{MCP_ALIAS}_health_check",
                    "pass_baton_to",
                ]
            }
        }

    def _broken_string_renderer(_template: object) -> str:
        return (
            "---\nname: probe\ntools:\n"
            "- resolve_reactivation\n"
            "- mcp_giljo_mcp_health_check\n"
            f"- mcp_{MCP_ALIAS}_resolve_reactivation\n"
            f"- mcp_{MCP_ALIAS}_health_check\n"
            "- pass_baton_to\n"
            "---\n\nBody text.\n"
        )

    for rendered in (_broken_dict_renderer(None), _broken_string_renderer(None)):
        all_problems = [p for text in _iter_strings(rendered) for p in _renderer_output_problems(text, MCP_ALIAS, live)]
        joined = "\n".join(all_problems)

        assert "resolve_reactivation" in joined and "directly" in joined, f"bare retired name did not fire: {joined!r}"
        assert "mcp_giljo_mcp_health_check" in joined, f"wrong-alias reference did not fire: {joined!r}"
        assert f"mcp_{MCP_ALIAS}_resolve_reactivation" in joined, (
            f"right-alias retired-tool ref did not fire: {joined!r}"
        )
        assert f"mcp_{MCP_ALIAS}_health_check" not in joined, f"a genuinely correct reference was flagged: {joined!r}"
        assert "pass_baton_to" not in joined, f"the pass_baton/pass_baton_to substring trap misfired: {joined!r}"




def test_the_prose_scan_matches_a_known_bad_string_and_spares_the_accessor_layer(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""Module docstring mentioning close_job, which is developer prose."""\n'
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        'HINT = "Verify the deliverable, then close_job each accepted agent."\n'
        'DISPATCH = "close_job"\n'
        'LABEL = "comm_thread.pass_baton"\n'
        'logger.warning("MCP pass_baton WS broadcast failed (non-fatal)")\n'
        "def f():\n"
        '    """Docstring naming implement_project."""\n'
        '    return "call get_implementation_prompt again"\n',
        encoding="utf-8",
    )

    found = {text for _lineno, text in _prose_literals(sample)}

    assert any("close_job each accepted agent" in t for t in found), "missed a real agent-facing instruction"
    assert "call get_implementation_prompt again" in found, "missed a prose literal inside a function"
    assert not any("developer prose" in t for t in found), "scanned a module docstring"
    assert not any("Docstring naming" in t for t in found), "scanned a function docstring"
    assert "close_job" not in found, "scanned a bare dispatch key"
    assert "comm_thread.pass_baton" not in found, "scanned a dotted accessor label"
    assert not any("WS broadcast failed" in t for t in found), "scanned a logger argument"


def test_the_retired_name_matching_respects_word_boundaries() -> None:
    baton = re.compile(r"\bpass_baton\b")
    assert baton.search("hand off with pass_baton first"), "word-boundary match failed on a real hit"
    assert not baton.search("see the pass_baton_to parameter"), "flagged a live parameter"

    doc = re.compile(r"\bget_vision_doc\b")
    assert doc.search("call get_vision_doc first"), "word-boundary match failed on a real hit"
    assert not doc.search("call get_vision_document first"), "flagged the live tool it prefixes"
