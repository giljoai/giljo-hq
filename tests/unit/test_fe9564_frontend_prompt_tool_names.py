# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.endpoints.mcp_tools._base import TOOL_SCOPES
from tests.helpers.retired_tool_names import RETIRED_TOOL_NAMES


REPO_ROOT = Path(__file__).resolve().parents[2]

FRONTEND_ROOTS = (REPO_ROOT / "frontend" / "src", REPO_ROOT / "frontend" / "tests")

_SOURCE_SUFFIXES = (".vue", ".js", ".ts")

_NAME = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+"

_QUALIFIED = r"(?<![\w.])"

_MARKUP = re.compile(r"</?code>|`")

_CLAIM_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mcp-prefix", re.compile(r"mcp__giljo_(?:hq|mcp)__(" + _NAME + r")")),
    ("kwarg-call", re.compile(_QUALIFIED + r"(" + _NAME + r")\(\s*[a-z_]+\s*=")),
    (
        "call-verb",
        re.compile(r"\b(?:call|calling|invoke|invoking)\s+(?:the\s+)?" + _QUALIFIED + r"(" + _NAME + r")\b", re.I),
    ),
    ("mcp-tool-phrase", re.compile(_QUALIFIED + r"(" + _NAME + r")\s+MCP tool\b")),
)


def _frontend_sources() -> list[Path]:
    return sorted(
        p
        for root in FRONTEND_ROOTS
        for p in root.rglob("*")
        if p.suffix in _SOURCE_SUFFIXES and "node_modules" not in p.parts and p.is_file()
    )


def _scan(pattern: re.Pattern[str]) -> list[tuple[str, int, str, str]]:
    found: list[tuple[str, int, str, str]] = []
    for path in _frontend_sources():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for match in pattern.finditer(_MARKUP.sub("", raw)):
                found.append((rel, lineno, match.group(1), raw.strip()))
    return found


def test_frontend_source_tree_is_where_this_test_thinks_it_is() -> None:
    for root in FRONTEND_ROOTS:
        assert root.is_dir(), f"frontend source tree missing at {root}"
    sources = _frontend_sources()
    assert len(sources) > 100, f"only {len(sources)} frontend sources found -- the scan root is wrong"


def test_no_frontend_source_names_a_retired_tool() -> None:
    retired = re.compile(_QUALIFIED + r"(" + "|".join(re.escape(n) for n in sorted(RETIRED_TOOL_NAMES)) + r")\b")
    hits = _scan(retired)
    assert not hits, "frontend sources naming a retired MCP tool:\n" + "\n".join(
        f"  {rel}:{lineno}  {name} -> {RETIRED_TOOL_NAMES[name]}\n      {line[:120]}"
        for rel, lineno, name, line in hits
    )


def test_every_claimed_tool_reference_is_registered() -> None:
    unknown: list[str] = []
    for label, pattern in _CLAIM_SHAPES:
        for rel, lineno, name, line in _scan(pattern):
            if name not in TOOL_SCOPES:
                replacement = RETIRED_TOOL_NAMES.get(name, "not a registered tool")
                unknown.append(f"  {rel}:{lineno}  [{label}] {name} -> {replacement}\n      {line[:120]}")
    assert not unknown, "frontend text names tools that are not in the shipped registry:\n" + "\n".join(
        sorted(set(unknown))
    )


def test_the_shipped_names_carry_the_arguments_the_rename_moved() -> None:
    required_arguments = {
        "get_my_turn": "wait_seconds",
        "list_threads": "query",
    }
    offenders: list[str] = []
    call = re.compile(_QUALIFIED + r"(" + _NAME + r")\((?P<args>[^)]*)\)")
    for path in _frontend_sources():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = _MARKUP.sub("", raw)
            for match in call.finditer(line):
                argument = required_arguments.get(match.group(1))
                if argument and "=" in match.group("args") and argument not in match.group("args"):
                    offenders.append(
                        f"  {rel}:{lineno}  {match.group(1)}(...) is missing {argument}=\n      {raw.strip()[:120]}"
                    )
    assert not offenders, "prompt text carries a renamed tool but dropped the argument the rename moved:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize(
    ("shape", "sample"),
    [
        ("mcp-prefix", "  // see mcp__giljo_hq__update_roadmap_metadata for the write path"),
        ("kwarg-call", '  `1. Call get_vision_doc(product_id="${id}") and follow it`,'),
        ("call-verb", "  '5. Save by calling update_roadmap_metadata with',"),
        ("mcp-tool-phrase", "  (it writes the roadmap via the <code>update_roadmap_metadata</code> MCP tool)"),
    ],
)
def test_each_claim_shape_actually_fires(shape: str, sample: str) -> None:
    pattern = dict(_CLAIM_SHAPES)[shape]
    match = pattern.search(_MARKUP.sub("", sample))
    assert match, f"shape {shape!r} no longer fires on the text it was written for: {sample!r}"
    assert match.group(1) not in TOOL_SCOPES


def test_claim_shapes_ignore_ordinary_javascript() -> None:
    benign = [
        "  const ok = await copy(promptText.value)",
        "  function buildRoadmapPrompt(mode) {",
        "  emit_websocket_event(payload)",
        "  const { product_id, project_id } = route.params",
        "  await api.prompts.implementation(projectId)",
    ]
    for line in benign:
        for shape, pattern in _CLAIM_SHAPES:
            assert not pattern.search(_MARKUP.sub("", line)), f"shape {shape!r} false-fired on ordinary JS: {line!r}"


def test_module_qualification_exempts_a_symbol_but_a_bare_name_still_fires() -> None:
    retired = re.compile(_QUALIFIED + r"(" + "|".join(re.escape(n) for n in sorted(RETIRED_TOOL_NAMES)) + r")\b")
    exempt = "  // the backend /threads/search endpoint (comm_threads.search_threads)"
    caught = "  * finds it the SAME way every sub-orchestrator does: search_threads(run_id)."
    assert not retired.search(exempt), "module-qualified live symbol must not be flagged"
    assert retired.search(caught), "a bare retired tool name must still be flagged"
