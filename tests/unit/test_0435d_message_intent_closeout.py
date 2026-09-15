# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest




@asynccontextmanager
async def _async_ctx(value):
    yield value




class TestRequiresActionAutoBlock:

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
        mock_session = AsyncMock()
        mock_session.info = {}
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
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_requires_action_true_proceeds_to_check(self, routing_service):
        mock_session = AsyncMock()
        mock_session.info = {}
        mock_project = MagicMock()
        mock_project.status = "active"
        mock_project.tenant_key = "test_tenant"

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
        assert "agent-123" in result
        assert mock_execution.status == "blocked"

    @pytest.mark.asyncio
    async def test_broadcast_still_skips_auto_block(self, routing_service):
        mock_session = AsyncMock()
        mock_session.info = {}
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




class TestMessageModelColumn:

    def test_requires_action_column_exists(self):
        from giljo_mcp.models.tasks import Message

        assert hasattr(Message, "requires_action")
        col = Message.__table__.columns["requires_action"]
        assert col.default.arg is False
        assert col.nullable is False


