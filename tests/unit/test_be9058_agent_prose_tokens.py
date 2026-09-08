# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9058 — grep-test: agent-facing prose never teaches retired/legacy tokens.

Live agent instructions contradicted the server (chapters_startup taught the
retired ``acknowledge_closeout_todo=True`` as REQUIRED; the guide and the
the chain tool's description taught pre-BE-9035c legacy execution-mode tokens;
BE-9554 retired start_chain_run into link_projects, so the scan anchors on that),
so agents got no-op advice or kept writing deprecated vocabulary into the DB.
This test is the structural fix that outlives the prose sweep: any prose
regression becomes CI-visible.

Two surfaces are scanned for every entry in ``BANNED_AGENT_PROSE_TOKENS``
(tests/helpers/banned_prose_tokens.py — extend the ban there, not here):

1. The prose-module SOURCES — the protocol chapter renderers, the seeded
   template instructions, the giljo guide, and the prompt templates. These
   modules exist to hold agent-facing strings, so a banned token anywhere in
   them (including comments) is a regression.
2. The LIVE FastMCP tool registry — every registered tool's description and
   parameter schema (the exact text an MCP client renders to its agent).

Pure source/registry scan; no DB. Parallel-safe. Edition Scope: Both.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers.banned_prose_tokens import BANNED_AGENT_PROSE_TOKENS, TOOL_PROSE_SURVIVORS


REPO_ROOT = Path(__file__).resolve().parents[2]

# The agent-facing prose modules: files whose PURPOSE is rendered agent
# instructions. Directories are scanned recursively (*.py).
PROSE_SURFACES: tuple[str, ...] = (
    "src/giljo_mcp/services/protocol_sections",
    "src/giljo_mcp/tools/giljo_guide.py",
    "src/giljo_mcp/template_seeder.py",
    "src/giljo_mcp/prompts",
)


def _iter_prose_files() -> list[Path]:
    files: list[Path] = []
    for surface in PROSE_SURFACES:
        base = REPO_ROOT / surface
        if base.is_file():
            files.append(base)
        elif base.is_dir():
            files.extend(p for p in base.rglob("*.py") if p.is_file())
    return files


def test_prose_surfaces_exist():
    """Guard against drift: if a surface moves, update PROSE_SURFACES."""
    for surface in PROSE_SURFACES:
        assert (REPO_ROOT / surface).exists(), f"Prose surface {surface} no longer exists — update PROSE_SURFACES."


@pytest.mark.parametrize("token,reason", BANNED_AGENT_PROSE_TOKENS, ids=[t for t, _ in BANNED_AGENT_PROSE_TOKENS])
def test_prose_modules_never_mention_banned_token(token: str, reason: str):
    offenders: list[str] = []
    for path in _iter_prose_files():
        text = path.read_text(encoding="utf-8")
        if token in text:
            offenders.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    assert not offenders, (
        f"Banned agent-prose token {token!r} found in {offenders}. Reason banned: {reason}. "
        f"Rendered protocol/template/guide prose must not mention it — reword (see "
        f"tests/helpers/banned_prose_tokens.py)."
    )


def _live_tool_texts() -> dict[str, str]:
    """name -> description + serialized parameter schema for every registered tool.

    Importing ``mcp_sdk_server`` registers every @mcp.tool wrapper against the
    shared FastMCP instance; the registry is the exact surface an MCP client
    renders to its agent (tools/list).
    """
    from api.endpoints import mcp_sdk_server  # noqa: F401 — import registers the wrappers
    from api.endpoints.mcp_tools._base import mcp

    texts: dict[str, str] = {}
    for tool in mcp._tool_manager.list_tools():
        params = json.dumps(tool.parameters) if isinstance(tool.parameters, dict) else ""
        texts[tool.name] = f"{tool.description or ''}\n{params}"
    return texts


@pytest.mark.parametrize("token,reason", BANNED_AGENT_PROSE_TOKENS, ids=[t for t, _ in BANNED_AGENT_PROSE_TOKENS])
def test_tool_descriptions_never_mention_banned_token(token: str, reason: str):
    offenders = [
        name for name, text in _live_tool_texts().items() if token in text and (name, token) not in TOOL_PROSE_SURVIVORS
    ]
    assert not offenders, (
        f"Banned agent-prose token {token!r} found in the registered tool description/schema of "
        f"{offenders}. Reason banned: {reason}. Fix the @mcp.tool wrapper prose (see "
        f"tests/helpers/banned_prose_tokens.py)."
    )


def test_registry_scan_actually_sees_tools():
    """The registry scan must never silently pass on an empty tool list."""
    texts = _live_tool_texts()
    assert len(texts) > 20, f"Expected the full MCP tool surface, got only {sorted(texts)}"
    assert "link_projects" in texts, "link_projects missing from the registry scan"
