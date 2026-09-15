# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers.banned_prose_tokens import BANNED_AGENT_PROSE_TOKENS, TOOL_PROSE_SURVIVORS


REPO_ROOT = Path(__file__).resolve().parents[2]

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
    texts = _live_tool_texts()
    assert len(texts) > 20, f"Expected the full MCP tool surface, got only {sorted(texts)}"
    assert "link_projects" in texts, "link_projects missing from the registry scan"
