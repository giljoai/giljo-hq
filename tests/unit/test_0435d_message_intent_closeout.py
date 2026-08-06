# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for Handover 0435d: Message Intent Flag & Closeout Validation.

Tests cover:
1. requires_action=False to a complete agent does NOT trigger auto-block
2. requires_action=True to a complete agent DOES trigger auto-block
3. requires_action column exists on Message model
4. Soft 360 memory check logic
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _async_ctx(value):
    yield value


# ---------------------------------------------------------------------------
# 1. requires_action controls auto-block behavior
# ---------------------------------------------------------------------------


class TestRequiresActionAutoBlock:
    """Verify that _auto_block_completed_recipients respects requires_action flag."""

    @pytest.fixture
    def routing_service(self):
        from giljo_mcp.services.message_routing_service import MessageRoutingService

        mock_db = MagicMock()
        mock_tenant = MagicMock()
        mock_tenant.get_current_tenant.return_value = "test_tenant"

        return MessageRoutingService(
            db_manager=mock_db,
            tenant_manager=mock_tenant,
        )

    @pytest.mark.asyncio
    async def test_informational_message_does_not_auto_block(self, routing_service):
        """requires_action=False should return empty list (no auto-blocking)."""
        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_project = MagicMock()
        mock_project.status = "active"

        result = await routing_service._auto_block_completed_recipients(
            session=mock_session,
            resolved_to_agents=["agent-123"],
            project=mock_project,
            sender_display_name="tester",
            is_broadcast_fanout=False,
            requires_action=False,
        )
        assert result == []
        # Session should never have been queried since we return early
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_requires_action_true_proceeds_to_check(self, routing_service):
        """requires_action=True should proceed past the guard and check agent status."""
        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_project = MagicMock()
        mock_project.status = "active"
        mock_project.tenant_key = "test_tenant"

        # Mock execution query returning a complete agent
        mock_execution = MagicMock()
        mock_execution.status = "complete"
        mock_execution.agent_display_name = "reviewer"
        mock_execution.agent_name = "reviewer"
        mock_execution.agent_id = "agent-123"
        mock_execution.job_id = "job-456"

        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_execution
        mock_session.execute = AsyncMock(return_value=mock_exec_result)
        mock_session.flush = AsyncMock()

        result = await routing_service._auto_block_completed_recipients(
            session=mock_session,
            resolved_to_agents=["agent-123"],
            project=mock_project,
            sender_display_name="tester",
            is_broadcast_fanout=False,
            requires_action=True,
        )
        # Should have auto-blocked the agent
        assert "agent-123" in result
        assert mock_execution.status == "blocked"

    @pytest.mark.asyncio
    async def test_broadcast_still_skips_auto_block(self, routing_service):
        """Broadcasts should still skip auto-block regardless of requires_action."""
        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_project = MagicMock()
        mock_project.status = "active"

        result = await routing_service._auto_block_completed_recipients(
            session=mock_session,
            resolved_to_agents=["agent-123"],
            project=mock_project,
            sender_display_name="tester",
            is_broadcast_fanout=True,
            requires_action=True,
        )
        assert result == []


# ---------------------------------------------------------------------------
# 2. Message model has requires_action column
# ---------------------------------------------------------------------------


class TestMessageModelColumn:
    """Verify the requires_action column exists on the Message model."""

    def test_requires_action_column_exists(self):
        from giljo_mcp.models.tasks import Message

        assert hasattr(Message, "requires_action")
        col = Message.__table__.columns["requires_action"]
        assert col.default.arg is False
        assert col.nullable is False


# BE-9012d: TestMCPSendMessageParam (the send_message MCP tool signature) and
# TestDefaultBehavior (MessageRoutingService.send_message's default) were removed
# with the bus hard-removal — send_message no longer exists at either layer. The
# requires_action=False-by-default contract they pinned is still covered by
# TestRequiresActionAutoBlock above (_auto_block_completed_recipients, KEPT) and
# tests/services/test_message_routing_requires_action_audit.py's
# test_message_model_requires_action_default_false (the Message column default).
