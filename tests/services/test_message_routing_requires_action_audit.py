# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _scan_for_requires_action_true_kwarg(src_path) -> list[str]:
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




def test_message_model_requires_action_default_false():
    from giljo_mcp.models.tasks import Message

    col = Message.__table__.columns["requires_action"]
    assert col.default.arg is False
    assert col.nullable is False




@pytest.mark.asyncio
async def test_completion_report_message_uses_default_requires_action():
    from pathlib import Path

    repo_src_path = Path(
        Path(__file__).parent.parent.parent / "src" / "giljo_mcp" / "repositories" / "agent_job_repository.py"
    )
    assert 'message_type="completion_report"' in repo_src_path.read_text(encoding="utf-8")

    offenders = _scan_for_requires_action_true_kwarg(repo_src_path)
    assert not offenders, (
        "agent_job_repository must not pass requires_action=True on auto-generated "
        f"messages. Offending sites: {offenders}"
    )




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
        mock_session = AsyncMock()
        mock_session.info = {}
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
        mock_session = AsyncMock()
        mock_session.info = {}
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
