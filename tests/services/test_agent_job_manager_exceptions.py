# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import BaseGiljoError, ResourceNotFoundError
from giljo_mcp.services.agent_job_manager import AgentJobManager
from giljo_mcp.tenant import TenantManager


@pytest.fixture
def mock_db_manager():
    return AsyncMock(spec=DatabaseManager)


@pytest.fixture
def mock_tenant_manager():
    manager = AsyncMock(spec=TenantManager)
    manager.get_current_tenant.return_value = "test-tenant"
    return manager


@pytest.fixture
def agent_job_manager(mock_db_manager, mock_tenant_manager):
    return AgentJobManager(db_manager=mock_db_manager, tenant_manager=mock_tenant_manager)


class TestSpawnExecutionExceptions:

    @pytest.mark.asyncio
    async def test_spawn_execution_raises_exception_on_database_error(self, agent_job_manager, mock_db_manager):
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.side_effect = Exception("Database connection lost")
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None

        mock_db_manager.get_session_async.return_value = mock_session

        with pytest.raises(BaseGiljoError) as exc_info:
            await agent_job_manager.spawn_execution(
                job_id="test-job",
                agent_display_name="Test Agent",
                tenant_key="test-tenant",
            )

        assert "Database connection lost" in str(exc_info.value)
        assert exc_info.value.context.get("operation") == "spawn_execution"


class TestCompleteJobExceptions:

    @pytest.mark.asyncio
    async def test_complete_job_raises_not_found_error(self, agent_job_manager, mock_db_manager):
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None

        mock_db_manager.get_session_async.return_value = mock_session

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await agent_job_manager.complete_job(job_id="nonexistent-job", tenant_key="test-tenant")

        assert "Job" in str(exc_info.value)
        assert "not found" in str(exc_info.value)
        assert exc_info.value.context.get("job_id") == "nonexistent-job"

    @pytest.mark.asyncio
    async def test_complete_job_raises_exception_on_database_error(self, agent_job_manager, mock_db_manager):
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.side_effect = Exception("Database error during job completion")
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None

        mock_db_manager.get_session_async.return_value = mock_session

        with pytest.raises(BaseGiljoError) as exc_info:
            await agent_job_manager.complete_job(job_id="test-job", tenant_key="test-tenant")

        assert "Database error during job completion" in str(exc_info.value)
        assert exc_info.value.context.get("operation") == "complete_job"
