# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Wave 2 Item 1, Part 1 — Audit informational message emitters.

Handover 0435d wired requires_action through the auto-block path so that
informational messages (default requires_action=False) do NOT reactivate
completed agents. This audit locks in the regression guard:

- The completion_report message_type (auto-generated agent completion notice)
  uses model defaults -> requires_action=False at the column level
- The Message model column default for requires_action is False
- _auto_block_completed_recipients (the KEPT auto-block primitive, BE-9012d)
  still short-circuits on requires_action=False / broadcast fan-out

If a future change accidentally flips one of these defaults to True, completed
agents will be auto-reactivated by routine status messages and burn tokens in
a loop. These tests prevent that regression.

BE-9012d: MessageRoutingService.send_message/broadcast/broadcast_to_project (the
bus send-side methods this audit originally pinned at the signature level) were
hard-removed with the bus. Their requires_action=False-by-default contract is now
moot — there is no bus emitter left to regress.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _scan_for_requires_action_true_kwarg(src_path) -> list[str]:
    """AST-based scan: returns offending Call sites that pass requires_action=True.

    Skips docstrings and comments — only matches keyword arguments in actual
    function/method calls. ``True`` and ``Constant(value=True)`` both match.
    """
    import ast

    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "requires_action":
                continue
            value = kw.value
            if isinstance(value, ast.Constant) and value.value is True:
                offenders.append(f"line {kw.lineno}: requires_action=True")
    return offenders


# ---------------------------------------------------------------------------
# 4. Message model column default
# ---------------------------------------------------------------------------


def test_message_model_requires_action_default_false():
    """Message.requires_action column must default to False (Handover 0435d)."""
    from giljo_mcp.models.tasks import Message

    col = Message.__table__.columns["requires_action"]
    assert col.default.arg is False
    assert col.nullable is False


# ---------------------------------------------------------------------------
# 5. completion_report message uses default (False) — repository inspection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completion_report_message_uses_default_requires_action():
    """
    The auto-generated completion_report message MUST not set requires_action=True.

    completion_report is the canonical "informational completion broadcast" that
    notifies upstream agents that a worker finished. If it were marked
    requires_action=True, every worker completion would auto-block its parent
    orchestrator — exactly the loop Handover 0435d closed at the messaging layer.
    """
    from pathlib import Path

    repo_src_path = Path(
        Path(__file__).parent.parent.parent / "src" / "giljo_mcp" / "repositories" / "agent_job_repository.py"
    )
    assert 'message_type="completion_report"' in repo_src_path.read_text(encoding="utf-8")

    # AST-based: ensure no Call passes requires_action=True kwarg. Defaulting
    # via the column server_default keeps the auto-completion-report at False.
    offenders = _scan_for_requires_action_true_kwarg(repo_src_path)
    assert not offenders, (
        "agent_job_repository must not pass requires_action=True on auto-generated "
        f"messages. Offending sites: {offenders}"
    )


# ---------------------------------------------------------------------------
# 6. Live: auto-block returns [] for informational messages
# ---------------------------------------------------------------------------


class TestAutoBlockBehavior:
    @pytest.fixture
    def routing_service(self):
        from giljo_mcp.services.message_routing_service import MessageRoutingService

        return MessageRoutingService(
            db_manager=MagicMock(),
            tenant_manager=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_informational_message_short_circuits_auto_block(self, routing_service):
        """requires_action=False -> auto-block returns [] without DB calls."""
        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_project = MagicMock()
        mock_project.status = "active"

        result = await routing_service._auto_block_completed_recipients(
            session=mock_session,
            resolved_to_agents=["agent-123"],
            project=mock_project,
            sender_display_name="orchestrator",
            is_broadcast_fanout=False,
            requires_action=False,
        )
        assert result == []
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_fanout_short_circuits_auto_block(self, routing_service):
        """Broadcasts skip auto-block regardless of requires_action."""
        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_project = MagicMock()
        mock_project.status = "active"

        result = await routing_service._auto_block_completed_recipients(
            session=mock_session,
            resolved_to_agents=["agent-123"],
            project=mock_project,
            sender_display_name="orchestrator",
            is_broadcast_fanout=True,
            requires_action=True,
        )
        assert result == []
