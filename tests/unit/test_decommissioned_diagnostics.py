# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for decommissioned execution diagnostic errors (Handover 0824, Fixes 2 & 3).

Tests cover:
1. complete_job returns descriptive error when execution was decommissioned
2. report_progress returns descriptive error when execution was decommissioned

These tests validate that agents receive actionable error messages explaining
WHY their execution is no longer active (decommissioned by force-close) instead
of a generic "No active execution found" message.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager
from tests.helpers.model_factories import make_agent_execution


def _make_mock_execution(
    status: str = "decommissioned",
    job_id: str | None = None,
    tenant_key: str = "test-tenant",
) -> Mock:
    """Create a mock AgentExecution with the given status."""
    return make_agent_execution(
        status=status,
        job_id=job_id or str(uuid4()),
        tenant_key=tenant_key,
        agent_id=str(uuid4()),
        agent_display_name="test-agent",
        started_at=datetime.now(UTC),
    )


class TestDecommissionedDiagnostics:
    """Tests for descriptive errors when an execution has been decommissioned."""

    @pytest.mark.asyncio
    async def test_complete_job_decommissioned_specific_error(self):
        """When complete_job finds no active execution but a decommissioned one, return descriptive error."""
        job_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_db_manager = MagicMock()
        mock_tenant_manager = MagicMock(spec=TenantManager)
        mock_tenant_manager.get_current_tenant.return_value = tenant_key

        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target

        decommissioned_exec = _make_mock_execution(status="decommissioned", job_id=job_id, tenant_key=tenant_key)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                # Active execution lookup -- none found
                result.scalar_one_or_none.return_value = None
            elif call_count["n"] == 2:
                # Decommissioned check -- found one
                result.scalar_one_or_none.return_value = decommissioned_exec
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        service = OrchestrationService(
            db_manager=mock_db_manager,
            tenant_manager=mock_tenant_manager,
            test_session=mock_session,
        )

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.complete_job(
                job_id=job_id,
                result={"summary": "done"},
                tenant_key=tenant_key,
            )

        assert "decommissioned" in str(exc_info.value).lower()
        assert exc_info.value.context["execution_status"] == "decommissioned"

    @pytest.mark.asyncio
    async def test_report_progress_decommissioned_specific_error(self):
        """When report_progress finds no active execution but a decommissioned one, return descriptive error."""
        job_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_db_manager = MagicMock()
        mock_tenant_manager = MagicMock(spec=TenantManager)
        mock_tenant_manager.get_current_tenant.return_value = tenant_key

        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target

        decommissioned_exec = _make_mock_execution(status="decommissioned", job_id=job_id, tenant_key=tenant_key)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                # Active execution lookup -- none found
                result.scalar_one_or_none.return_value = None
            elif call_count["n"] == 2:
                # Decommissioned check -- found one
                result.scalar_one_or_none.return_value = decommissioned_exec
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        service = OrchestrationService(
            db_manager=mock_db_manager,
            tenant_manager=mock_tenant_manager,
            test_session=mock_session,
        )

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.report_progress(
                job_id=job_id,
                progress={"percent": 50},
                tenant_key=tenant_key,
            )

        assert "decommissioned" in str(exc_info.value).lower()
        assert exc_info.value.context["execution_status"] == "decommissioned"
