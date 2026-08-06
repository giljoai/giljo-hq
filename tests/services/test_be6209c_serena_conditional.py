# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6209c (Q3) — Serena guidance is conditional, not an assertion/mandate.

The Serena blocks render whenever the `integrations.serena_mcp.use_in_prompts` UI
toggle is on, which does NOT guarantee Serena is actually installed/registered in
the agent's session. The orchestrator block hard-asserted presence ("you use it
BEFORE and DURING staging") and mandated use ("SPAWN EVERY AGENT WITH A SERENA-FIRST
MISSION", "LEAD with Serena"). This softens every role block to conditional phrasing
("prefer Serena when available, else Read/Grep").

Pure-string assertions (no DB, no module-level mutable state) — parallel-safe.
Edition Scope: CE.
"""

from __future__ import annotations

import pytest

from giljo_mcp.prompt_generation.serena_instructions import for_role


_ROLES = ("orchestrator", "analyzer", "implementer", "tester", "reviewer", "documenter", "anything-unknown")


@pytest.mark.parametrize("role", _ROLES)
def test_every_role_block_carries_conditional_availability_lead(role: str) -> None:
    """Each role block (incl. the unknown→default fallback) leads with the conditional
    availability framing instead of asserting Serena is present."""
    block = for_role(role, enabled=True)
    assert "If Serena MCP tools are available in your session" in block
    assert "fall back to Read/Grep" in block


def test_orchestrator_block_drops_the_hard_mandate() -> None:
    """The imperative presence-assertion + serena-first mandate are gone."""
    block = for_role("orchestrator", enabled=True)
    assert "SPAWN EVERY AGENT WITH A SERENA-FIRST MISSION" not in block
    assert "LEAD with Serena" not in block
    # Conditional replacements are present instead.
    assert "When it is available" in block
    assert "ENCOURAGE A SERENA-FIRST MISSION (WHEN AVAILABLE):" in block


def test_softening_preserves_load_bearing_markers() -> None:
    """Markers other tests pin must survive the reword.

    BE-9260: the CAVEAT text no longer asserts "Python-only" as a universal fact
    (that was THIS repo's LSP config leaking into every customer's guidance) — it
    now derives the claim from "the language(s) its LSP is configured for in this
    workspace". Pin the CAVEAT section's survival on that reworded language instead.
    """
    orch = for_role("orchestrator", enabled=True)
    assert "STAGING DISCOVERY" in orch
    assert "CAVEAT:" in orch
    assert "cover only the language(s) its LSP is configured for in this workspace" in orch

    impl = for_role("implementer", enabled=True)
    assert "SYMBOLIC EDITING" in impl
    assert "replace_symbol_body" in impl

    default = for_role("agent", enabled=True)  # unknown role → default block
    assert "Serena MCP Available" in default


def test_disabled_returns_empty_unchanged() -> None:
    """The toggle-off contract is untouched: disabled → empty string."""
    assert for_role("orchestrator", enabled=False) == ""
    assert for_role(None, enabled=False) == ""
