# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.endpoints.agent_jobs import lifecycle
from api.endpoints.agent_jobs.models import SpawnAgentRequest
from giljo_mcp.schemas.service_responses import SpawnResult


class TestSpawnAgentJob:

    @pytest.mark.asyncio
    async def test_spawn_agent_success(self):
        mock_user = MagicMock()
        mock_user.username = "test_user"
        mock_user.role = "admin"
        mock_user.tenant_key = "test_tenant"

        mock_service = AsyncMock()
        mock_service.spawn_job.return_value = SpawnResult(
            job_id="job-123",
            agent_id="agent-456",
            agent_prompt="Test prompt",
            mission_stored=True,
            thin_client=True,
        )

        mock_ws_dep = AsyncMock()

        request = SpawnAgentRequest(agent_display_name="implementer", mission="Test mission", project_id="proj-123")

        response = await lifecycle.spawn_job(
            request=request, current_user=mock_user, orchestration_service=mock_service, ws_dep=mock_ws_dep
        )

        assert response.success is True
        assert response.job_id == "job-123"
        mock_service.spawn_job.assert_called_once()
        mock_ws_dep.broadcast_to_tenant.assert_called_once()

    @pytest.mark.asyncio
    async def test_spawn_agent_non_admin_forbidden(self):
        mock_user = MagicMock()
        mock_user.username = "test_user"
        mock_user.role = "user"
        mock_user.tenant_key = "test_tenant"

        request = SpawnAgentRequest(agent_display_name="implementer", mission="Test mission", project_id="proj-123")

        with pytest.raises(HTTPException) as exc_info:
            await lifecycle.spawn_job(
                request=request, current_user=mock_user, orchestration_service=AsyncMock(), ws_dep=AsyncMock()
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_spawn_agent_service_error(self):
        from giljo_mcp.exceptions import OrchestrationError

        mock_user = MagicMock()
        mock_user.username = "test_user"
        mock_user.role = "admin"
        mock_user.tenant_key = "test_tenant"

        mock_service = AsyncMock()
        mock_service.spawn_job.side_effect = OrchestrationError("Failed to spawn")

        request = SpawnAgentRequest(agent_display_name="implementer", mission="Test mission", project_id="proj-123")

        with pytest.raises(OrchestrationError):
            await lifecycle.spawn_job(
                request=request, current_user=mock_user, orchestration_service=mock_service, ws_dep=AsyncMock()
            )
