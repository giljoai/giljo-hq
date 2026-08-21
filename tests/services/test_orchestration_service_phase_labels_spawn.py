# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TDD Tests for Handover 0411a: Phase Labels on AgentJob - Spawn Tests.

Change A: spawn_job accepts and stores `phase` parameter on AgentJob,
and WebSocket broadcast includes `phase` in data dict.

Split from test_orchestration_service_phase_labels.py during test reorganization.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from giljo_mcp.models import AgentJob
from tests.helpers.model_factories import make_project


# ============================================================================
# Change A: spawn_job accepts and stores phase parameter
# ============================================================================


@pytest.mark.asyncio
class TestSpawnAgentJobPhaseParameter:
    """Tests that spawn_job correctly handles the `phase` parameter."""

    async def test_spawn_stores_phase_on_agent_job(self, db_session, db_manager, test_project, test_tenant_key):
        """Verify spawn_job stores phase value on AgentJob record."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Analyze the codebase",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        # Verify phase stored on AgentJob
        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase == 1

    async def test_spawn_stores_none_phase_when_omitted(self, db_session, db_manager, test_project, test_tenant_key):
        """Verify spawn_job defaults phase to None when not provided."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Analyze the codebase",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
        )

        # Verify phase is None when not specified
        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase is None

    async def test_spawn_stores_higher_phase_numbers(self, db_session, db_manager, test_project, test_tenant_key):
        """Verify spawn_job correctly stores phase values > 1."""
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        # CE-0033 Task 11: phase > 1 requires a non-empty predecessor_job_id.
        predecessor = await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Predecessor analysis",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=1,
        )

        result = await service.spawn_job(
            agent_display_name="tester",
            agent_name="tester-1",
            mission="Write integration tests",
            project_id=test_project.id,
            tenant_key=test_tenant_key,
            phase=3,
            predecessor_job_id=predecessor.job_id,
        )

        job_stmt = select(AgentJob).where(AgentJob.job_id == result.job_id)
        job_result = await db_session.execute(job_stmt)
        job = job_result.scalar_one()
        assert job.phase == 3


# ============================================================================
# Change A (continued): WebSocket broadcast includes phase
# ============================================================================


@pytest.mark.asyncio
class TestSpawnWebSocketBroadcastPhase:
    """Tests that WebSocket broadcast data includes phase field."""

    async def test_websocket_broadcast_includes_phase(self):
        """Verify agent:created WebSocket broadcast includes phase in data dict."""
        from giljo_mcp.services.orchestration_service import OrchestrationService

        db_manager = MagicMock()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.add = MagicMock()
        session.info = {}  # tenant_session_context save/restore target
        db_manager.get_session_async = MagicMock(return_value=session)

        mock_ws = AsyncMock()
        tenant_manager = MagicMock()

        service = OrchestrationService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=mock_ws,
        )

        # Mock project lookup
        # INF-9399: a real transient Project, not a mock. The mock_execute below
        # dispatches by CALL ORDER, so a project that is not shaped like a real row
        # is unusually expensive here: spawn resolves the project's product to scope
        # the agent allowlist, and a bare mock answered that with a truthy child
        # mock, running a lookup that shifted every subsequent call index by one.
        # BE-9437: a project with no product is NO LONGER a real state (product_id
        # is NOT NULL), so the factory supplies one and that product-scoping lookup
        # DOES run. It is answered explicitly below rather than dodged -- the
        # dispatch has to model the real call sequence, not a shorter one.
        project = make_project(
            id=str(uuid.uuid4()),
            name="Test Project",
            execution_mode="multi_terminal",
        )

        # Mock template lookup (active templates for validation)
        mock_template_row = MagicMock()
        mock_template_row.__getitem__ = lambda self, idx: "analyzer-1"

        # Query 1: Project lookup
        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)

        # Query 2: Template name validation
        template_validation_result = MagicMock()
        template_validation_result.fetchall = MagicMock(return_value=[mock_template_row])

        # Query 3: Duplicate agent_display_name check (returns no duplicates)
        duplicate_check_result = MagicMock()
        duplicate_check_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        # Query 4: Template lookup for multi-terminal injection
        mock_template = MagicMock()
        mock_template.id = str(uuid.uuid4())
        mock_template.system_instructions = "Test instructions"
        mock_template.user_instructions = None
        template_lookup_result = MagicMock()
        template_lookup_result.scalar_one_or_none = MagicMock(return_value=mock_template)

        # BE-9437: product_agent_selection.template_ids_for_product runs an
        # existence probe whenever the project HAS a product. .first() is None ->
        # the junction has "no opinion" and the tenant-wide allowlist is used (the
        # documented tolerance rule), which is the behaviour these phase-label
        # tests want and the one the product-less project used to reach by
        # skipping the query entirely.
        assignment_probe_result = MagicMock()
        assignment_probe_result.first = MagicMock(return_value=None)

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return project_result
            if call_count == 2:
                return assignment_probe_result
            if call_count == 3:
                return template_validation_result
            if call_count == 4:
                return duplicate_check_result
            return template_lookup_result

        session.execute = AsyncMock(side_effect=mock_execute)

        # CE-0033 Task 11: phase > 1 requires a non-empty predecessor_job_id,
        # which triggers a DB query that's awkward to mock here. The broadcast-
        # shape contract is the same for any phase value, so use phase=2 with a
        # predecessor-only test surface is overkill — phase=1 exercises the
        # phase-in-broadcast wiring just as well.
        await service.spawn_job(
            agent_display_name="analyzer",
            agent_name="analyzer-1",
            mission="Analyze codebase",
            project_id=project.id,
            tenant_key="tk_test",
            phase=1,
        )

        # Verify broadcast was called with phase in data
        mock_ws.broadcast_to_tenant.assert_called_once()
        call_kwargs = mock_ws.broadcast_to_tenant.call_args
        broadcast_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert "phase" in broadcast_data
        assert broadcast_data["phase"] == 1

    async def test_websocket_broadcast_includes_none_phase_when_omitted(self):
        """Verify agent:created WebSocket broadcast includes phase=None when not specified."""
        from giljo_mcp.services.orchestration_service import OrchestrationService

        db_manager = MagicMock()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.add = MagicMock()
        session.info = {}  # tenant_session_context save/restore target
        db_manager.get_session_async = MagicMock(return_value=session)

        mock_ws = AsyncMock()
        tenant_manager = MagicMock()

        service = OrchestrationService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            websocket_manager=mock_ws,
        )

        # INF-9399: a real transient Project, not a mock. The mock_execute below
        # dispatches by CALL ORDER, so a project that is not shaped like a real row
        # is unusually expensive here: spawn resolves the project's product to scope
        # the agent allowlist, and a bare mock answered that with a truthy child
        # mock, running a lookup that shifted every subsequent call index by one.
        # BE-9437: a project with no product is NO LONGER a real state (product_id
        # is NOT NULL), so the factory supplies one and that product-scoping lookup
        # DOES run. It is answered explicitly below rather than dodged -- the
        # dispatch has to model the real call sequence, not a shorter one.
        project = make_project(
            id=str(uuid.uuid4()),
            name="Test Project",
            execution_mode="multi_terminal",
        )

        mock_template_row = MagicMock()
        mock_template_row.__getitem__ = lambda self, idx: "impl-1"

        # Query 1: Project lookup
        project_result = MagicMock()
        project_result.scalar_one_or_none = MagicMock(return_value=project)

        # Query 2: Template name validation
        template_validation_result = MagicMock()
        template_validation_result.fetchall = MagicMock(return_value=[mock_template_row])

        # Query 3: Duplicate agent_display_name check (returns no duplicates)
        duplicate_check_result = MagicMock()
        duplicate_check_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        # Query 4: Template lookup for multi-terminal injection
        mock_template = MagicMock()
        mock_template.id = str(uuid.uuid4())
        mock_template.system_instructions = "Test instructions"
        mock_template.user_instructions = None
        template_lookup_result = MagicMock()
        template_lookup_result.scalar_one_or_none = MagicMock(return_value=mock_template)

        # BE-9437: product_agent_selection.template_ids_for_product runs an
        # existence probe whenever the project HAS a product. .first() is None ->
        # the junction has "no opinion" and the tenant-wide allowlist is used (the
        # documented tolerance rule), which is the behaviour these phase-label
        # tests want and the one the product-less project used to reach by
        # skipping the query entirely.
        assignment_probe_result = MagicMock()
        assignment_probe_result.first = MagicMock(return_value=None)

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return project_result
            if call_count == 2:
                return assignment_probe_result
            if call_count == 3:
                return template_validation_result
            if call_count == 4:
                return duplicate_check_result
            return template_lookup_result

        session.execute = AsyncMock(side_effect=mock_execute)

        await service.spawn_job(
            agent_display_name="implementer",
            agent_name="impl-1",
            mission="Implement feature",
            project_id=project.id,
            tenant_key="tk_test",
            # No phase parameter
        )

        mock_ws.broadcast_to_tenant.assert_called_once()
        call_kwargs = mock_ws.broadcast_to_tenant.call_args
        broadcast_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert "phase" in broadcast_data
        assert broadcast_data["phase"] is None
