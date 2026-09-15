# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.prompt_generation.serena_instructions import for_role


_ROLES = ("orchestrator", "analyzer", "implementer", "tester", "reviewer", "documenter", "anything-unknown")


@pytest.mark.parametrize("role", _ROLES)
def test_every_role_block_carries_conditional_availability_lead(role: str) -> None:
    block = for_role(role, enabled=True)
    assert "If Serena MCP tools are available in your session" in block
    assert "fall back to Read/Grep" in block


def test_orchestrator_block_drops_the_hard_mandate() -> None:
    block = for_role("orchestrator", enabled=True)
    assert "SPAWN EVERY AGENT WITH A SERENA-FIRST MISSION" not in block
    assert "LEAD with Serena" not in block
    assert "When it is available" in block
    assert "ENCOURAGE A SERENA-FIRST MISSION (WHEN AVAILABLE):" in block


def test_softening_preserves_load_bearing_markers() -> None:
    orch = for_role("orchestrator", enabled=True)
    assert "STAGING DISCOVERY" in orch
    assert "CAVEAT:" in orch
    assert "cover only the language(s) its LSP is configured for in this workspace" in orch

    impl = for_role("implementer", enabled=True)
    assert "SYMBOLIC EDITING" in impl
    assert "replace_symbol_body" in impl

    default = for_role("agent", enabled=True)
    assert "Serena MCP Available" in default


def test_disabled_returns_empty_unchanged() -> None:
    assert for_role("orchestrator", enabled=False) == ""
    assert for_role(None, enabled=False) == ""
