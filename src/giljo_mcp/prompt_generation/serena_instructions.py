# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Serena MCP guidance — single source of truth (INF-6007).

Two entry points, both driven by the `integrations.serena_mcp.use_in_prompts`
toggle:

- `generate_serena_instructions(enabled)` — the original generic ~50-token
  notice. Retained for backward compatibility.
- `for_role(role, enabled)` — role-specific guidance. This consolidates the
  six role variants that previously lived in
  `template_manager._get_serena_guidance` (which never reached the orchestrator
  because of a broken string-anchor inject) plus a sensible default.

Both reach the runtime paths agents actually read:
- `for_role("orchestrator")` is surfaced in `get_staging_instructions`.
- `for_role(job.job_type)` is prepended to every agent mission.
"""

import logging


logger = logging.getLogger(__name__)


_GENERIC_NOTICE = """
## Serena MCP Available

Serena MCP symbolic code navigation is enabled for token-efficient codebase exploration.
Key tools: find_symbol, get_symbols_overview, search_for_pattern, replace_symbol_body.
Serena provides 80-90% token savings vs full file reads.
""".strip()


# BE-6209c: the Serena guidance blocks render whenever the
# `integrations.serena_mcp.use_in_prompts` UI toggle is on — which does NOT
# guarantee Serena is actually installed/registered in the agent's session. So the
# guidance is framed CONDITIONALLY ("prefer Serena when available, else Read/Grep")
# instead of asserting its presence and mandating its use. Shared lead-in woven into
# every role block via `for_role`, mirroring how `_PYTHON_ONLY_CAVEAT` travels.
_AVAILABILITY_LEAD = (
    "If Serena MCP tools are available in your session, prefer them for the steps below; "
    "if they are not registered, fall back to Read/Grep — the workflow is the same, only "
    "the tools differ."
)


# Caveat shared by every role: Serena's LSP only covers the language(s) it is
# configured for in a given workspace (Python-only in THIS repo). Symbol tools
# silently return nothing on files outside that coverage, which reads as a
# "no results" false negative rather than an error. Steer agents to pattern
# search for anything outside the configured language(s). BE-9260: worded
# conditionally rather than asserting "Python-only" as a universal fact — the
# customer's own product may configure Serena for a different language.
_PYTHON_ONLY_CAVEAT = (
    "Serena's symbol tools (find_symbol, find_referencing_symbols, replace_symbol_body, "
    "rename_symbol, etc.) cover only the language(s) its LSP is configured for in this "
    "workspace. For any file type outside that coverage, use search_for_pattern or "
    "standard file tools (Read/Grep/Edit) instead."
)


_ORCHESTRATOR_GUIDANCE = """
## Serena MCP — Orchestrator Guidance

{availability}

Serena MCP provides semantic, token-efficient code navigation. When it is available,
prefer it BEFORE and DURING staging, and set that expectation for the agents you spawn.

STAGING DISCOVERY (when Serena is available, do this before spawning agents):
- Use get_symbols_overview + find_symbol + search_for_pattern to scope the real
  surface area of the work — which files, which symbols, which call sites — so you
  spawn the right agents with the right file scope instead of guessing.
- Use find_referencing_symbols to size blast radius before you decide how to split work.
- If Serena is not available, do the same scoping with Read/Grep.

ENCOURAGE A SERENA-FIRST MISSION (WHEN AVAILABLE):
- When Serena is available, instruct each spawned agent to prefer it (get_symbols_overview /
  find_symbol / find_referencing_symbols) over reading whole files — the single biggest
  token saver across a multi-agent run. If Serena is not available, agents use Read/Grep.

CAVEAT:
- {caveat}

CORE TOOLS:
- get_symbols_overview: high-level file structure (classes, functions) without a full read
- find_symbol: locate a specific class/function/method
- find_referencing_symbols: find where code is used (dependency mapping)
- search_for_pattern: regex search across the codebase (use on .vue/.js/.scss)
- replace_symbol_body / insert_after_symbol / insert_before_symbol: precise edits
""".strip()


_ANALYZER_GUIDANCE = """
## Serena MCP — Analysis Guidance

{availability}

- get_symbols_overview: understand file structure without reading full code
- find_symbol: locate specific implementations
- find_referencing_symbols: map dependencies and usage patterns
- search_for_pattern: find code patterns across the codebase

WORKFLOW:
1. Start with get_symbols_overview for new files (avoids reading entire files).
2. Use find_symbol to locate implementation details.
3. Use find_referencing_symbols to map dependencies.
4. Focus on architecture, not editing (you analyze, the implementer edits).

CAVEAT:
- {caveat}
""".strip()


_IMPLEMENTER_GUIDANCE = """
## Serena MCP — Implementation Guidance

{availability}

- get_symbols_overview: understand file structure before editing
- find_symbol: locate the exact symbols to modify
- find_referencing_symbols: check dependencies before changing a symbol
- SYMBOLIC EDITING (prefer these for precision):
  - replace_symbol_body: update a function/class implementation
  - insert_after_symbol / insert_before_symbol: add code around an existing symbol

WORKFLOW:
1. Use get_symbols_overview first (don't read entire files blindly).
2. Locate exact symbols with find_symbol.
3. Check callers with find_referencing_symbols before you change a signature.
4. Use symbolic editing for precise, maintainable changes.

CAVEAT:
- {caveat}
""".strip()


_TESTER_GUIDANCE = """
## Serena MCP — Testing Guidance

{availability}

- get_symbols_overview: identify testable units
- find_symbol: locate functions/classes to test
- find_referencing_symbols: find existing test coverage / call sites

WORKFLOW:
1. Use get_symbols_overview to discover testable units.
2. Use find_symbol to understand implementation details.
3. Use find_referencing_symbols to check whether tests already exist.

CAVEAT:
- {caveat}
""".strip()


_REVIEWER_GUIDANCE = """
## Serena MCP — Code Review Guidance

{availability}

- get_symbols_overview: understand code structure
- find_symbol: examine specific implementations
- find_referencing_symbols: check usage patterns and blast radius

WORKFLOW:
1. Use get_symbols_overview to understand file organization.
2. Use find_symbol to examine implementations.
3. Use find_referencing_symbols to verify correct usage.

CAVEAT:
- {caveat}
""".strip()


_DOCUMENTER_GUIDANCE = """
## Serena MCP — Documentation Guidance

{availability}

- get_symbols_overview: discover the public API surface
- find_symbol: examine implementations to document
- search_for_pattern: find similar patterns across the codebase

WORKFLOW:
1. Use get_symbols_overview to identify public APIs.
2. Use find_symbol to understand implementation details.
3. Document based on the actual code structure.

CAVEAT:
- {caveat}
""".strip()


_DEFAULT_GUIDANCE = """
## Serena MCP Available

{availability}

Use Serena MCP tools for semantic, token-efficient code analysis:
- get_symbols_overview: understand file structure
- find_symbol: locate specific code
- find_referencing_symbols: map dependencies
- search_for_pattern: regex search across the codebase

CAVEAT:
- {caveat}
""".strip()


_ROLE_GUIDANCE: dict[str, str] = {
    "orchestrator": _ORCHESTRATOR_GUIDANCE,
    "analyzer": _ANALYZER_GUIDANCE,
    "implementer": _IMPLEMENTER_GUIDANCE,
    "tester": _TESTER_GUIDANCE,
    "reviewer": _REVIEWER_GUIDANCE,
    "documenter": _DOCUMENTER_GUIDANCE,
}


def generate_serena_instructions(enabled: bool = True) -> str:
    """
    Generate the simplified, role-agnostic Serena MCP notice (~50 tokens).

    Args:
        enabled: Whether Serena MCP is enabled.

    Returns:
        Generic notice if enabled, empty string if disabled.
    """
    if not enabled:
        return ""
    return _GENERIC_NOTICE


def for_role(role: str | None, enabled: bool = True) -> str:
    """
    Generate role-specific Serena MCP guidance.

    This is the single source of truth for Serena guidance text. The
    orchestrator instructions builder and the agent-mission builder both call
    it so every surface gets the same, role-appropriate guidance.

    Args:
        role: Agent role (orchestrator, analyzer, implementer, tester,
            reviewer, documenter). Unknown/None falls back to a generic block.
        enabled: Whether Serena MCP is enabled.

    Returns:
        Role-specific guidance if enabled, empty string if disabled.
    """
    if not enabled:
        return ""

    key = role.lower() if role else ""
    template = _ROLE_GUIDANCE.get(key, _DEFAULT_GUIDANCE)
    return template.format(caveat=_PYTHON_ONLY_CAVEAT, availability=_AVAILABILITY_LEAD)
