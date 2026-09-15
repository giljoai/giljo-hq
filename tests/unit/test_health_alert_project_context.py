# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from giljo_mcp.monitoring.health_config import AgentHealthStatus
from giljo_mcp.services.agent_health_ws_broadcast import broadcast_agent_auto_failed, broadcast_health_alert


class TestAgentHealthStatusProjectFields:

    def test_agent_health_status_has_project_fields(self):
        status = AgentHealthStatus(
            execution_id="exec-001",
            job_id="job-001",
            agent_id="agent-001",
            agent_display_name="implementer",
            current_status="working",
            health_state="critical",
            last_update=datetime.now(UTC),
            minutes_since_update=15.0,
            issue_description="Agent stalled",
            recommended_action="Check agent logs",
            project_id="proj-123",
            project_name="My Project",
        )

        assert status.project_id == "proj-123"
        assert status.project_name == "My Project"

    def test_agent_health_status_default_project_fields_are_empty(self):
        status = AgentHealthStatus(
            execution_id="exec-002",
            job_id="job-002",
            agent_id="agent-002",
            agent_display_name="orchestrator",
            current_status="waiting",
            health_state="warning",
            last_update=datetime.now(UTC),
            minutes_since_update=5.0,
            issue_description="Waiting too long",
            recommended_action="Check queue",
        )

        assert status.project_id == ""
        assert status.project_name == ""

    def test_agent_health_status_stores_all_required_fields(self):
        now = datetime.now(UTC)
        status = AgentHealthStatus(
            execution_id="exec-003",
            job_id="job-003",
            agent_id="agent-003",
            agent_display_name="reviewer",
            current_status="working",
            health_state="timeout",
            last_update=now,
            minutes_since_update=30.5,
            issue_description="No heartbeat for 30 minutes",
            recommended_action="Restart agent",
            project_id="proj-456",
            project_name="Backend Refactor",
        )

        assert status.execution_id == "exec-003"
        assert status.job_id == "job-003"
        assert status.agent_id == "agent-003"
        assert status.agent_display_name == "reviewer"
        assert status.current_status == "working"
        assert status.health_state == "timeout"
        assert status.last_update == now
        assert status.minutes_since_update == 30.5
        assert status.issue_description == "No heartbeat for 30 minutes"
        assert status.recommended_action == "Restart agent"
        assert status.project_id == "proj-456"
        assert status.project_name == "Backend Refactor"

    def test_agent_health_status_empty_project_for_orphaned_job(self):
        status = AgentHealthStatus(
            execution_id="exec-orphan",
            job_id="job-orphan",
            agent_id="agent-orphan",
            agent_display_name="implementer",
            current_status="working",
            health_state="critical",
            last_update=datetime.now(UTC),
            minutes_since_update=10.0,
            issue_description="Stalled execution",
            recommended_action="Manual review",
            project_id="",
            project_name="",
        )

        assert status.project_id == ""
        assert status.project_name == ""


class TestBroadcastHealthAlertProjectContext:

    @pytest.mark.asyncio
    async def test_broadcast_health_alert_includes_project_context(self):
        from api.websocket import WebSocketManager

        ws_manager = WebSocketManager()

        ws_manager.broadcast_event_to_tenant = AsyncMock()

        health_status = AgentHealthStatus(
            execution_id="exec-100",
            job_id="job-100",
            agent_id="agent-100",
            agent_display_name="implementer",
            current_status="working",
            health_state="critical",
            last_update=datetime.now(UTC),
            minutes_since_update=20.0,
            issue_description="No progress for 20 minutes",
            recommended_action="Check agent",
            project_id="proj-abc",
            project_name="Feature Sprint",
            product_id="product-abc",
        )

        await broadcast_health_alert(
            ws_manager,
            tenant_key="test-tenant",
            job_id="job-100",
            agent_display_name="implementer",
            health_status=health_status,
        )

        ws_manager.broadcast_event_to_tenant.assert_called_once()
        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = (
            call_kwargs.kwargs.get("event") or call_kwargs[1].get("event") or call_kwargs[0][1]
            if len(call_kwargs[0]) > 1
            else call_kwargs.kwargs["event"]
        )

        data = event["data"]
        assert data["project_id"] == "proj-abc"
        assert data["project_name"] == "Feature Sprint"
        assert data["execution_id"] == "exec-100"
        assert data["tenant_key"] == "test-tenant"
        assert data["job_id"] == "job-100"
        assert data["agent_display_name"] == "implementer"
        assert data["health_state"] == "critical"
        assert data["product_id"] == "product-abc"

    @pytest.mark.asyncio
    async def test_broadcast_health_alert_includes_empty_project_for_orphaned_jobs(self):
        from api.websocket import WebSocketManager

        ws_manager = WebSocketManager()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        health_status = AgentHealthStatus(
            execution_id="exec-orphan-200",
            job_id="job-orphan-200",
            agent_id="agent-orphan-200",
            agent_display_name="orchestrator",
            current_status="waiting",
            health_state="timeout",
            last_update=datetime.now(UTC),
            minutes_since_update=45.0,
            issue_description="Job never acknowledged",
            recommended_action="Manual intervention required",
        )

        await broadcast_health_alert(
            ws_manager,
            tenant_key="test-tenant",
            job_id="job-orphan-200",
            agent_display_name="orchestrator",
            health_status=health_status,
        )

        ws_manager.broadcast_event_to_tenant.assert_called_once()
        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = (
            call_kwargs.kwargs.get("event") or call_kwargs[1].get("event") or call_kwargs[0][1]
            if len(call_kwargs[0]) > 1
            else call_kwargs.kwargs["event"]
        )

        data = event["data"]
        assert data["project_id"] == ""
        assert data["project_name"] == ""
        assert data["execution_id"] == "exec-orphan-200"

    @pytest.mark.asyncio
    async def test_broadcast_health_alert_event_type_is_correct(self):
        from api.websocket import WebSocketManager

        ws_manager = WebSocketManager()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        health_status = AgentHealthStatus(
            execution_id="exec-300",
            job_id="job-300",
            agent_id="agent-300",
            agent_display_name="implementer",
            current_status="working",
            health_state="warning",
            last_update=datetime.now(UTC),
            minutes_since_update=10.0,
            issue_description="Slow progress",
            recommended_action="Monitor",
            project_id="proj-xyz",
            project_name="Test Project",
        )

        await broadcast_health_alert(
            ws_manager,
            tenant_key="test-tenant",
            job_id="job-300",
            agent_display_name="implementer",
            health_status=health_status,
        )

        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = (
            call_kwargs.kwargs.get("event") or call_kwargs[1].get("event") or call_kwargs[0][1]
            if len(call_kwargs[0]) > 1
            else call_kwargs.kwargs["event"]
        )

        assert event["type"] == "agent:health_alert"
        assert event["schema_version"] == "1.0"


class TestBroadcastAgentAutoFailedProductId:

    @pytest.mark.asyncio
    async def test_broadcast_agent_auto_failed_includes_product_id(self):
        from api.websocket import WebSocketManager

        ws_manager = WebSocketManager()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await broadcast_agent_auto_failed(
            ws_manager,
            tenant_key="test-tenant",
            job_id="job-400",
            agent_display_name="implementer",
            reason="Abandoned",
            product_id="product-xyz",
        )

        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs["event"]
        assert event["type"] == "agent:auto_failed"
        assert event["data"]["product_id"] == "product-xyz"

    @pytest.mark.asyncio
    async def test_broadcast_agent_auto_failed_omits_product_id_when_none(self):
        from api.websocket import WebSocketManager

        ws_manager = WebSocketManager()
        ws_manager.broadcast_event_to_tenant = AsyncMock()

        await broadcast_agent_auto_failed(
            ws_manager,
            tenant_key="test-tenant",
            job_id="job-401",
            agent_display_name="implementer",
            reason="Abandoned",
        )

        call_kwargs = ws_manager.broadcast_event_to_tenant.call_args
        event = call_kwargs.kwargs["event"]
        assert "product_id" not in event["data"]
