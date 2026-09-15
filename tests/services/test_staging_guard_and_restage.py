# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
from tests.helpers.model_factories import make_agent_execution, make_project




@pytest.fixture
def mock_db_manager():
    db_manager = MagicMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock()
    session.info = {}
    db_manager.get_session_async = MagicMock(return_value=session)
    return db_manager, session


@pytest.fixture
def mock_tenant_manager():
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant = MagicMock(return_value="tenant-test")
    return tenant_manager


@pytest.fixture
def lifecycle_service(mock_db_manager, mock_tenant_manager):
    db_manager, _ = mock_db_manager
    return ProjectLifecycleService(db_manager=db_manager, tenant_manager=mock_tenant_manager)


def _make_project(staging_status=None, execution_mode="multi_terminal", status="active"):
    return make_project(
        name="Test Project",
        status=status,
        staging_status=staging_status,
        execution_mode=execution_mode,
        tenant_key="tenant-test",
        mission="Test mission",
        description="Test description",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        product_id=str(uuid4()),
    )


def _make_orchestrator_execution(status="waiting"):
    return make_agent_execution(
        status=status,
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        tenant_key="tenant-test",
    )




class TestStagingGuard:

    @pytest.mark.asyncio
    async def test_staging_guard_rejects_when_already_staging(self, lifecycle_service, mock_db_manager):
        project = _make_project(staging_status="staging")

        from giljo_mcp.exceptions import ProjectStateError

        with pytest.raises(ProjectStateError, match="Staging already in progress"):
            lifecycle_service.check_staging_allowed(project)

    def test_staging_guard_allows_when_not_staging(self, lifecycle_service):
        project = _make_project(staging_status=None)
        lifecycle_service.check_staging_allowed(project)

    def test_staging_guard_allows_when_staging_complete(self, lifecycle_service):
        project = _make_project(staging_status="staging_complete")
        lifecycle_service.check_staging_allowed(project)




class TestRestage:

    @pytest.mark.asyncio
    async def test_restage_success_when_staging_and_orchestrator_waiting(self, lifecycle_service, mock_db_manager):
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        orchestrator = _make_orchestrator_execution(status="waiting")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        fixture_result = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = fixture_result
            result = await lifecycle_service.restage(project.id)

        assert project.staging_status is None
        assert project.execution_mode == "multi_terminal"

        assert orchestrator.status == "decommissioned"

        session.commit.assert_called()

        mock_fixture.assert_called_once()

        assert result["message"] == "Project restaged successfully"
        assert result["project_id"] == project.id

    @pytest.mark.asyncio
    async def test_restage_rejects_when_not_staging(self, lifecycle_service, mock_db_manager):
        _, session = mock_db_manager
        project = _make_project(staging_status=None)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=project)
        session.execute = AsyncMock(return_value=mock_result)

        from giljo_mcp.exceptions import ProjectStateError

        with pytest.raises(ProjectStateError, match="not currently staged"):
            await lifecycle_service.restage(project.id)

    @pytest.mark.asyncio
    async def test_restage_recovers_from_staging_complete_before_implementation(
        self, lifecycle_service, mock_db_manager
    ):
        _, session = mock_db_manager
        project = _make_project(staging_status="staging_complete")
        project.implementation_launched_at = None
        orchestrator = _make_orchestrator_execution(status="waiting")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        fixture_result = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = fixture_result
            result = await lifecycle_service.restage(project.id)

        assert project.staging_status is None
        assert orchestrator.status == "decommissioned"
        assert result["message"] == "Project restaged successfully"

    @pytest.mark.asyncio
    async def test_restage_rejects_staging_complete_after_implementation_launched(
        self, lifecycle_service, mock_db_manager
    ):
        _, session = mock_db_manager
        project = _make_project(staging_status="staging_complete")
        project.implementation_launched_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=project)
        session.execute = AsyncMock(return_value=mock_result)

        from giljo_mcp.exceptions import ProjectStateError

        with pytest.raises(ProjectStateError, match="implementation already launched"):
            await lifecycle_service.restage(project.id)

    @pytest.mark.asyncio
    async def test_restage_rejects_when_orchestrator_active(self, lifecycle_service, mock_db_manager):
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        orchestrator = _make_orchestrator_execution(status="working")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        from giljo_mcp.exceptions import ProjectStateError

        with pytest.raises(ProjectStateError, match="orchestrator agent is already active"):
            await lifecycle_service.restage(project.id)

    @pytest.mark.asyncio
    async def test_restage_rejects_when_project_not_found(self, lifecycle_service, mock_db_manager):
        _, session = mock_db_manager

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_result)

        from giljo_mcp.exceptions import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError, match="Project not found"):
            await lifecycle_service.restage(str(uuid4()))

    @pytest.mark.asyncio
    async def test_restage_clears_implementation_launched_at_ce_0032(self, lifecycle_service, mock_db_manager):
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        project.implementation_launched_at = datetime.now(UTC)
        orchestrator = _make_orchestrator_execution(status="waiting")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
            await lifecycle_service.restage(project.id)

        assert project.implementation_launched_at is None, (
            "CE-0032: restage must clear project.implementation_launched_at to None — "
            "stale v1 timestamps would regress the CE-0027 TODOs-bypass on restage-after-completion"
        )
        assert project.staging_status is None
        assert project.execution_mode == "multi_terminal"

    @pytest.mark.asyncio
    async def test_restage_does_not_clear_ever_launched_at(self, lifecycle_service, mock_db_manager):
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        project.implementation_launched_at = datetime.now(UTC)
        project.ever_launched_at = datetime.now(UTC)
        orchestrator = _make_orchestrator_execution(status="waiting")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
            await lifecycle_service.restage(project.id)

        assert project.implementation_launched_at is None
        assert project.ever_launched_at is not None, (
            "BE-9085b: restage must NOT clear ever_launched_at -- it's the durable "
            "'was ever launched' fact the BE-9085 detector relies on"
        )

    @pytest.mark.asyncio
    async def test_restage_creates_fresh_orchestrator_fixture(self, lifecycle_service, mock_db_manager):
        _, session = mock_db_manager
        project = _make_project(staging_status="staging")
        orchestrator = _make_orchestrator_execution(status="waiting")

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none = MagicMock(return_value=project)
        mock_orch_result = MagicMock()
        mock_orch_result.scalar_one_or_none = MagicMock(return_value=orchestrator)
        session.execute = AsyncMock(side_effect=[mock_project_result, mock_orch_result])

        new_fixture = {"job_id": str(uuid4()), "agent_id": str(uuid4())}
        with patch.object(lifecycle_service, "_ensure_orchestrator_fixture", new_callable=AsyncMock) as mock_fixture:
            mock_fixture.return_value = new_fixture
            result = await lifecycle_service.restage(project.id)

        mock_fixture.assert_called_once_with(session, project)
        assert result["new_orchestrator"] == new_fixture
