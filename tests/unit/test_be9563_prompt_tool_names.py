# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9563 -- agent-facing prompts may only name tools that exist.

BE-9554 renamed nine MCP tools and swept the repo. It did not sweep the PROMPTS.
``CANONICAL_ORCHESTRATOR_TOOLS`` -- the roster rendered into the STEP 0 TOOLSEARCH
BOOTSTRAP that every staged orchestrator runs as its first action -- still listed
``close_job`` and ``resolve_reactivation`` after both were dropped from the
registry. So every orchestrator on every tenant booted by asking its harness for
two tools that do not exist. ToolSearch answers an unknown name with silence, so
nothing failed at boot; the agent discovered the gap at closeout, the most
expensive moment available.

BE-9554's own guard could not have caught it. That guard reads the REGISTERED tool
descriptions -- the strings FastMCP serves. A prompt generator's output never
passes through the registry, so the whole prompt surface was unguarded. Applying
CLAUDE.md's mechanism-vs-prose test: a lane could rename carefully, update every
description, and still ship this. Mechanism gap, and prose cannot close it.

Four layers, because the surface has four shapes and no single check sees them all:

A. ROSTERS -- the two explicit tool lists an agent is handed (the ToolSearch boot
   bundle, and get_job_mission's ``mcp_tools_available``). Allowlist: every entry
   must be a live tool. This is the layer that catches the shipped defect. Note
   the boot bundle is built from f-strings (``f"{_PREFIX}close_job"``), so a
   source scan for ``mcp__giljo_hq__close_job`` finds NOTHING -- the token never
   exists as a literal. Only reading the built tuple works.
B. QUALIFIED MENTIONS -- a fully-prefixed ``mcp__giljo_hq__<name>`` inside any
   prose literal. Allowlist against the registry.
C. BARE MENTIONS -- a retired name inside a sentence. Denylist, because a bare
   ``finalize_job`` in prose is indistinguishable from an English word without one.
D. THE MAP ITSELF -- see tests/helpers/retired_tool_names.py. Layer C is only as
   honest as its denylist, and PR #1013 proved a rename sweep will happily rewrite
   that denylist into an allowlist. D is what makes C survive the next sweep.

HOW LAYER C TELLS AGENT PROSE FROM THE ACCESSOR LAYER -- read this before adding a
suppression. BE-9554 renamed the WIRE names only. The internal accessor names
(``_call_tool(ctx, "close_job", ...)``, ``_base.py``'s dispatch map,
``tool_accessor/`` pass-throughs, ``method="close_job"`` error labels) were
deliberately left alone: a renamed door, not a new write path. Breaking them takes
the product down. Three exclusions keep them out, and each is structural rather
than a path list, so a new file is covered the day it is written:

  * DOCSTRINGS and comments -- developer prose. A docstring is exactly
    ``Expr(Constant(str))``; only literals used as VALUES are scanned.
  * LOGGER ARGUMENTS -- an operator log line never reaches an agent.
  * WHITESPACE-FREE LITERALS -- a literal whose entire value is the tool name
    (``"close_job"``) or a dotted label (``"comm_thread.pass_baton"``) is a
    dispatch key or an accessor argument. A name an agent is told to CALL always
    arrives inside a sentence. The rosters those bare literals form are covered by
    layer A instead, which is an allowlist and therefore stricter.

Measured on the fix commit: ~140 raw grep hits across src/ + api/ collapse to the
14 that are genuinely agent-facing.
"""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

from giljo_mcp.models import AgentTemplate
from tests.helpers.retired_tool_names import RETIRED_TOOL_NAMES


# Scanned roots for layers B and C. Deliberately the WHOLE backend surface rather
# than a curated list of "prompt files": the two sites BE-9563 was filed for live
# in prompts/, but the same class was also sitting in a service's next_action
# ``why``, a CLOSEOUT_BLOCKED hint, and a vision-tool ``usage`` string. A curated
# list would have found two of fourteen.
_SCAN_ROOTS = ("src", "api")

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Methods whose string arguments are operator logs, never agent-facing.
_LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "log"})

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")

# Error-context keys whose value is an internal operation label. These reach the
# agent inside str(exc) -- see test_no_error_label_is_a_bare_dead_tool_name.
_LABEL_KEYS = frozenset({"method", "operation"})


def _live_tool_names() -> set[str]:
    from api.endpoints.mcp_tools import mcp

    return {tool.name for tool in asyncio.run(mcp.list_tools())}


def _qualified_pattern() -> re.Pattern[str]:
    from giljo_mcp.branding import MCP_ALIAS

    return re.compile(rf"mcp__{re.escape(MCP_ALIAS)}__([a-z_][a-z0-9_]*)")


def _prose_literals(path: Path) -> list[tuple[int, str]]:
    """Every string literal in ``path`` that an agent could plausibly read.

    Excludes docstrings, logger arguments, and whitespace-free literals -- see the
    module docstring for why each exclusion is load-bearing.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    skip: set[int] = set()
    for node in ast.walk(tree):
        # Docstrings (and any other bare string statement) are developer prose.
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            skip.add(id(node.value))
        # Anything inside a logging call, including f-string fragments.
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
            continue  # a lone token is a dispatch key, not an instruction
        out.append((node.lineno, node.value))
    return out


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        files.extend(sorted((_REPO_ROOT / root).rglob("*.py")))
    return files


# ---------------------------------------------------------------------------
# Layer A -- the explicit rosters an agent is handed
# ---------------------------------------------------------------------------


def test_orchestrator_toolsearch_bundle_names_only_live_tools() -> None:
    """The STEP 0 bootstrap every staged orchestrator runs first.

    This is the exact assertion BE-9563 needed and nobody had: the bundle is built
    from f-strings, so no source scan for the prefixed token can see it.
    """
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
    """``mcp_tools_available``, returned to the orchestrator by get_job_mission.

    Same failure as the boot bundle one layer later: the agent is handed a roster,
    believes it, and reaches for a tool that was removed.
    """
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
    """The CE first-boots migration banner, pointed at a human instead of an agent.

    Same defect class as the two agent rosters and it drifted the same way: a list of
    tool names that nobody re-checked against the registry. Two of its eight rows were
    dead -- `get_messages` went with the message bus (BE-9012d), and
    `propose_product_context_update` had been renamed again to `apply_context_tuning`
    (BE-6225c), a double rename the banner never caught up with. A fresh CE self-hoster
    was told on their first three boots to use tools that do not exist.

    Only the RIGHT side of each pair is checked. The left side is history -- it records
    what the name used to be -- and asserting against it would be asserting that the
    past has not happened.
    """
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


# ---------------------------------------------------------------------------
# Layer B -- fully-qualified mentions in prose
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Layer C -- bare mentions in prose
# ---------------------------------------------------------------------------


def test_no_agent_facing_prose_names_a_retired_tool() -> None:
    """The regression BE-9563 exists for.

    A sentence telling an agent to call a tool that was renamed is a false
    instruction, and it reads perfectly -- the only thing wrong with it is a fact
    that lives in the registry, not in the sentence.
    """
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


# ---------------------------------------------------------------------------
# Layer D -- the denylist cannot quietly become an allowlist
# ---------------------------------------------------------------------------


def test_every_retired_key_is_actually_retired() -> None:
    """PR #1013 rewrote this map's KEYS to the new names during a rename sweep.

    Layer C skips any key that is a live tool, so the rewrite silently disabled 8 of
    9 entries and BE-9554's guard checked nothing for a release. This is the assert
    that would have failed the moment that sweep ran.
    """
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
    """The other half: a replacement pointing at a tool that does not exist sends the
    reader from one dead name to another."""
    live = _live_tool_names()
    broken = [
        f"  {name!r} -> {replacement!r} names no live tool"
        for name, replacement in RETIRED_TOOL_NAMES.items()
        if not any(token in live for token in _IDENTIFIER.findall(replacement))
    ]

    assert not broken, "RETIRED_TOOL_NAMES replacements do not resolve:\n" + "\n".join(broken)


# ---------------------------------------------------------------------------
# Layer E -- internal labels that reach the agent inside an error string
# ---------------------------------------------------------------------------


def _former_tool_names() -> set[str]:
    """Every name that was once an MCP tool and is not one now.

    Two sources, because neither alone is complete: the retired->replacement map
    (the renames), and the LEFT side of the CE boot banner's pairs (an older wave
    this project would otherwise have no record of).
    """
    from api.startup.background_tasks import TOOL_RENAME_NOTICE_PAIRS

    names = set(RETIRED_TOOL_NAMES)
    for pair in TOOL_RENAME_NOTICE_PAIRS:
        old, _, _new = pair.partition("\u2192")
        names.update(_IDENTIFIER.findall(old))
    return names - _live_tool_names()


def test_no_error_label_is_a_bare_dead_tool_name() -> None:
    """``method``/``operation`` labels reach the agent, which is not obvious.

    ``BaseGiljoError.__str__`` renders ``f"{message} (Context: {context})"``, and
    ``_base.py`` re-RAISES a sub-500 ``BaseGiljoError`` verbatim -- so the SDK puts
    ``str(e)`` on the wire. An agent calling ``resume_or_dismiss_job`` on a wrong-state
    job was shown ``'method': 'dismiss_reactivation'``, a name that is not a tool.
    Observed on prod; reproduced locally before this guard was written.

    WHAT THIS DOES NOT DO. There are ~180 of these labels and the overwhelming
    majority were NEVER tools -- ``comm_thread.post``, ``list_tasks_for_mcp``,
    ``verify_password``. That is a long-standing diagnostic convention, not drift,
    and stripping it from agent-visible errors is a separate decision with its own
    museum-rule burden. This guard is narrow on purpose: a label may not be a BARE
    name that used to be a callable tool. Qualifying it (``service.close_job``,
    ``accessor.start_chain_run``) satisfies it, matching the dotted form already in
    use at ~50 of those sites -- the label stays truthful for an operator reading
    logs, and stops reading as a tool an agent could call.
    """
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


# ---------------------------------------------------------------------------
# Layer F -- the SIX per-platform agent renderers' RETURNED value
# ---------------------------------------------------------------------------
#
# BE-9567: every layer above scans SOURCE TEXT or REGISTERED descriptions. None
# of them renders anything, which is exactly why render_gemini_agent's hardcoded
# 16-entry `tools:` block slipped all four -- the strings were Python list
# literals inside a function body, never a string an agent template ships with,
# never a registered tool description. This layer closes that gap by calling
# every per-template renderer and inspecting what it ACTUALLY RETURNS, the way
# a downloaded agent file would read. Two renderers (codex, antigravity) return
# a dict rather than a document string, so this walks structures, not just text.
#
# A hardcoded roster can go wrong two ways, and _renderer_output_problems
# checks both, over EVERY string leaf a renderer returns (a lone dict/list
# value, e.g. antigravity's ``toolNames``, AND a token embedded inside one big
# rendered document, e.g. a YAML ``tools:`` list item inside a single Markdown
# string -- render_claude_agent and render_gemini_agent return exactly one
# string covering the whole file, so a naive "only check whitespace-free
# leaves" design never even looks inside it):
#   (a) a bare retired tool name (resolve_reactivation, gone since BE-9554),
#       found with a plain \b-bounded search -- safe here because \b only
#       misclassifies a retired name when it is immediately underscore-glued to
#       something else, and this half is deliberately restricted to names that
#       stand alone;
#   (b) an MCP-qualified reference (``mcp_`` or ``mcp__`` embedding the
#       product's brand root) that does not resolve under the CURRENT
#       branding.MCP_ALIAS -- either the alias segment itself is wrong (the
#       shipped ``giljo_mcp`` vs the live ``giljo_hq``) or the trailing name is
#       not registered (a retired tool, a typo). This half deliberately does
#       NOT rely on \b to separate the alias from the tool name -- both
#       segments are underscore-joined, so \b can't tell them apart -- and
#       instead extracts the whole ``mcp_...`` run and resolves it against
#       explicit alias-prefixed forms.


def _iter_strings(value: object):
    """Yield every string leaf in a renderer's return value.

    Two renderers return a dict rather than a document string -- walk nested
    dicts/lists/tuples too, so a hardcoded tool name buried a level deep (e.g.
    inside antigravity's ``config.customAgent.toolNames``) is still seen.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _iter_strings(v)


# Every maximal ``mcp_``/``mcp__``-prefixed run inside a text -- NOT anchored
# to the whole string, so this also finds a list-item token embedded inside a
# single large rendered document (a YAML ``tools:`` entry inside render_gemini_
# agent's one returned string). Claude Code: ``mcp__<alias>__<tool>`` (double
# underscore -- see ``_qualified_pattern`` above). Gemini CLI: ``mcp_<alias>_
# <tool>`` (single underscore -- mcp-tool.ts's ``generateValidName(serverName +
# "_" + serverToolName)``, confirmed against google-gemini/gemini-cli main
# 2026-09-03).
_MCP_TOKEN_RE = re.compile(r"\bmcp_{1,2}[a-z][a-z0-9_]*")


def _renderer_output_problems(text: str, alias: str, live: set[str]) -> list[str]:
    """Every retired-tool or unresolved-MCP-reference problem found in ``text``."""
    problems: list[str] = []

    for name in RETIRED_TOOL_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", text):
            problems.append(f"names retired {name!r} directly (replacement: {RETIRED_TOOL_NAMES[name]})")

    brand_root = alias.split("_", 1)[0]
    claude_prefix = f"mcp__{alias}__"
    gemini_prefix = f"mcp_{alias}_"
    for token in _MCP_TOKEN_RE.findall(text):
        if brand_root not in token:
            # Not actually an attempt at an MCP tool reference -- e.g.
            # antigravity's `mcp_servers` systemPromptConfig section id (a
            # config identifier, not a tool call). Every alias this product
            # has used embeds the brand root ("giljo"); a config section id
            # never will.
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
    """A minimal, fully-populated AgentTemplate -- enough for all six renderers
    to run without an AttributeError on a field one of them happens to read."""
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
    """Resolve the six per-template renderers by name.

    Deliberately excludes ``render_template`` (a dispatcher over the two above)
    and ``render_plugin_manifest`` (takes name/version/description, not a
    template -- it renders no tool content at all). Rebuilt on every call
    rather than cached at module scope (no module-level mutable state, per the
    parallel-safe test-writing rule) -- it's a handful of attribute lookups.
    """
    from giljo_mcp import template_renderer as tr

    return {
        "claude": tr.render_claude_agent,
        "generic": tr.render_generic_agent,
        "gemini": tr.render_gemini_agent,
        "opencode": tr.render_opencode_agent,
        "codex": tr.render_codex_agent,
        "antigravity": tr.render_antigravity_agent,
    }


def test_no_renderer_output_names_a_retired_or_unresolved_tool() -> None:
    """The regression BE-9567 exists for, checked at the OUTPUT layer.

    render_gemini_agent's hardcoded list named ``resolve_reactivation`` (retired
    by BE-9554) and used the pre-rename ``giljo_mcp`` alias throughout (zero
    overlap with the live ``giljo_hq`` registry) -- see render_gemini_agent's
    docstring for the upstream source citations proving BOTH failure shapes are
    silently swallowed by gemini-cli (never surfaced to the model or a human).
    """
    from giljo_mcp.branding import MCP_ALIAS

    live = _live_tool_names()
    template = _make_probe_template()

    hits: list[str] = []
    for platform, renderer in _layer_f_renderers().items():
        rendered = renderer(template)
        for text in _iter_strings(rendered):
            for problem in _renderer_output_problems(text, MCP_ALIAS, live):
                hits.append(f"  render_{platform}_agent output {problem}")

    assert not hits, "A per-platform renderer's OUTPUT names a retired or unresolved tool:\n" + "\n".join(
        sorted(set(hits))
    )


def test_layer_f_scanner_fires_on_a_known_bad_render() -> None:
    """A guard that has never failed on known-bad input is not a guard.

    Two probes, because the real bug shipped in the shape the FIRST draft of
    this guard missed: a bare retired name (`_broken_dict_renderer`, proving
    the structure-walk handles a dict/list leaf) is easy to catch, but
    render_gemini_agent actually returns ONE big Markdown string with the whole
    `tools:` YAML block folded inside it -- `_broken_string_renderer` pins that
    shape directly, embedding the exact same bad tokens inside one multi-line
    document the way the real defect did. A version of this guard that only
    checked whitespace-free dict/list leaves passed clean against the
    unmodified pre-fix render_gemini_agent, which is why this second probe
    exists.

    Both probes carry: a bare retired name, a wrong-(pre-rename)-alias
    reference, a right-alias-but-retired reference, and two controls that must
    NOT fire -- a genuinely correct reference, and ``pass_baton_to`` (guards
    the exact substring trap the module docstring warns about: ``pass_baton``
    is a substring of ``pass_baton_to``).
    """
    from giljo_mcp.branding import MCP_ALIAS

    live = _live_tool_names()

    def _broken_dict_renderer(_template: object) -> dict[str, object]:
        return {
            "config": {
                "tools": [
                    "resolve_reactivation",  # bare retired name
                    "mcp_giljo_mcp_health_check",  # wrong (pre-rename) alias, correct tool
                    f"mcp_{MCP_ALIAS}_resolve_reactivation",  # right alias, retired tool
                    f"mcp_{MCP_ALIAS}_health_check",  # control: must NOT fire
                    "pass_baton_to",  # control: must NOT fire (substring trap)
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


# ---------------------------------------------------------------------------
# Checker-must-fire -- a guard that cannot fail is not a guard
# ---------------------------------------------------------------------------


def test_the_prose_scan_matches_a_known_bad_string_and_spares_the_accessor_layer(tmp_path: Path) -> None:
    """The whole guard rests on the prose/accessor split, so pin the split itself
    with one file carrying every shape at once."""
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
    """``pass_baton_to`` is a LIVE parameter on post_to_thread and ``get_vision_document``
    is a LIVE tool. A guard that flags either gets deleted by the next lane."""
    baton = re.compile(r"\bpass_baton\b")
    assert baton.search("hand off with pass_baton first"), "word-boundary match failed on a real hit"
    assert not baton.search("see the pass_baton_to parameter"), "flagged a live parameter"

    doc = re.compile(r"\bget_vision_doc\b")
    assert doc.search("call get_vision_doc first"), "word-boundary match failed on a real hit"
    assert not doc.search("call get_vision_document first"), "flagged the live tool it prefixes"
