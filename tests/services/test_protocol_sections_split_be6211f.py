# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest




def test_orchestrator_body_importable_from_both_paths() -> None:
    from giljo_mcp.services.protocol_sections.agent_lifecycle import (
        _build_orchestrator_protocol_body as from_lifecycle,
    )
    from giljo_mcp.services.protocol_sections.orchestrator_body import (
        _build_orchestrator_protocol_body as from_body,
    )

    assert from_lifecycle is from_body


def test_anchor_constants_reexported_from_agent_lifecycle() -> None:
    from giljo_mcp.services.protocol_sections import agent_lifecycle, orchestrator_body

    for name in (
        "_WORKER_SPAWN_BLOCK_START",
        "_PROGRESS_REPORTING_ANCHOR",
        "_CONDUCTOR_COORDINATION_NOTE",
        "_PHASE3_CLOSEOUT_START",
        "_ORCHESTRATOR_CONSTRAINTS_ANCHOR",
        "_CONDUCTOR_CLOSEOUT_NOTE",
    ):
        assert getattr(agent_lifecycle, name) is getattr(orchestrator_body, name)


@pytest.mark.parametrize("mode", ["multi_terminal", "claude-code", "codex", "gemini"])
@pytest.mark.parametrize("is_conductor", [False, True])
def test_orchestrator_protocol_renders_through_moved_body(mode: str, is_conductor: bool) -> None:
    from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol

    proto = _generate_orchestrator_protocol(
        job_id="j-6211f",
        tenant_key="tk-6211f",
        executor_id="exec-6211f",
        execution_mode=mode,
        tool=mode,
        is_chain_conductor=is_conductor,
    )

    assert isinstance(proto, str) and proto
    assert "## Orchestrator Coordination Protocol (3 Phases)" in proto




def test_worker_body_importable_from_both_paths() -> None:
    from giljo_mcp.services.protocol_sections.agent_protocol import (
        _build_conditional_blocks as cond_from_proto,
    )
    from giljo_mcp.services.protocol_sections.agent_protocol import (
        _build_worker_protocol_body as body_from_proto,
    )
    from giljo_mcp.services.protocol_sections.worker_body import (
        _build_conditional_blocks as cond_from_wb,
    )
    from giljo_mcp.services.protocol_sections.worker_body import (
        _build_worker_protocol_body as body_from_wb,
    )

    assert cond_from_proto is cond_from_wb
    assert body_from_proto is body_from_wb


@pytest.mark.parametrize("mode", ["multi_terminal", "claude-code", "codex", "gemini"])
@pytest.mark.parametrize("git_enabled", [False, True])
def test_worker_protocol_renders_through_moved_body(mode: str, git_enabled: bool) -> None:
    from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol

    proto = _generate_agent_protocol(
        job_id="j-6211f",
        tenant_key="tk-6211f",
        agent_name="implementer",
        agent_id="exec-6211f",
        execution_mode=mode,
        git_integration_enabled=git_enabled,
        job_type="agent",
        tool=mode,
    )

    assert isinstance(proto, str) and proto
    assert "## Agent Lifecycle Protocol (5 Phases)" in proto
    assert ("### Git Commit (REQUIRED - Git Integration Enabled)" in proto) == git_enabled
