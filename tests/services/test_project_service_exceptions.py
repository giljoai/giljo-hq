# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from uuid import uuid4

import pytest

from giljo_mcp.exceptions import (
    BaseGiljoError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.products import Product
from giljo_mcp.schemas.service_responses import (
    OperationResult,
    ProjectData,
    ProjectDetail,
    ProjectMissionUpdateResult,
    SoftDeleteResult,
)
from giljo_mcp.services.project_service import ProjectService


class TestProjectServiceExceptions:

    @pytest.mark.asyncio
    async def test_get_project_raises_not_found(self, project_service: ProjectService, test_tenant_key: str):
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await project_service.get_project("nonexistent-id", test_tenant_key)

        assert "not found" in exc_info.value.message.lower()
        assert exc_info.value.context.get("project_id") == "nonexistent-id"
        assert exc_info.value.context.get("tenant_key") == test_tenant_key

    @pytest.mark.asyncio
    async def test_get_project_requires_tenant_key(self, project_service: ProjectService):
        with pytest.raises(ValidationError) as exc_info:
            await project_service.get_project("some-id", "")

        assert "tenant_key" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_project_mission_raises_not_found(self, project_service: ProjectService, test_tenant_key: str):
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await project_service.update_project_mission("nonexistent-id", "New mission", test_tenant_key)

        assert "not found" in exc_info.value.message.lower()



    @pytest.mark.asyncio
    async def test_activate_project_raises_not_found(self, project_service: ProjectService, test_tenant_key: str):
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await project_service.activate_project("nonexistent-id", test_tenant_key)

        assert "not found" in exc_info.value.message.lower()


    @pytest.mark.asyncio
    async def test_deactivate_project_raises_not_found(self, project_service: ProjectService, test_tenant_key: str):
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await project_service.deactivate_project("nonexistent-id", test_tenant_key)

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_deactivate_project_raises_state_error(
        self, project_service: ProjectService, test_tenant_key: str, inactive_project
    ):
        with pytest.raises(ProjectStateError) as exc_info:
            await project_service.deactivate_project(inactive_project.id, test_tenant_key)

        assert "cannot deactivate" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_complete_project_raises_not_found(self, project_service: ProjectService, test_tenant_key: str):
        with pytest.raises(BaseGiljoError) as exc_info:
            await project_service.complete_project(
                "nonexistent-id", "Summary", key_outcomes=[], decisions_made=[], tenant_key=test_tenant_key
            )

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_complete_project_raises_validation_error_no_summary(
        self, project_service: ProjectService, test_tenant_key: str, active_project
    ):
        with pytest.raises(ValidationError) as exc_info:
            await project_service.complete_project(
                active_project.id, "", key_outcomes=[], decisions_made=[], tenant_key=test_tenant_key
            )

        assert "summary" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_cancel_project_raises_not_found(self, project_service: ProjectService, test_tenant_key: str):
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await project_service.lifecycle.cancel_project("nonexistent-id", test_tenant_key)

        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_restore_project_raises_not_found(self, project_service: ProjectService, test_tenant_key: str):
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await project_service.deletion.restore_project("nonexistent-id", tenant_key=test_tenant_key)

        assert "not found" in exc_info.value.message.lower()


    @pytest.mark.asyncio
    async def test_cancel_staging_raises_not_found(self, project_service: ProjectService, test_tenant_key: str):
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await project_service.lifecycle.cancel_staging("nonexistent-id", test_tenant_key)

        assert "not found" in exc_info.value.message.lower()



class TestProjectServiceTypedReturns:

    @pytest.mark.asyncio
    async def test_get_project_returns_project_detail(
        self, project_service: ProjectService, test_tenant_key: str, active_project
    ):
        result = await project_service.get_project(active_project.id, test_tenant_key)
        assert isinstance(result, ProjectDetail)
        assert result.id == str(active_project.id)
        assert result.name == "Active Test Project"
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_update_project_mission_returns_typed(
        self, project_service: ProjectService, test_tenant_key: str, active_project
    ):
        result = await project_service.update_project_mission(
            active_project.id, "Updated mission text", test_tenant_key
        )
        assert isinstance(result, ProjectMissionUpdateResult)
        assert result.project_id == active_project.id
        assert result.message == "Mission updated successfully"

    @pytest.mark.asyncio
    async def test_cancel_staging_returns_project_data(
        self, project_service: ProjectService, test_tenant_key: str, db_session
    ):
        from giljo_mcp.models.projects import Project as ProjectModel

        staging_product = Product(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            name=f"Staging Product {uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(staging_product)
        await db_session.flush()

        project = ProjectModel(
            id=str(uuid4()),
            product_id=staging_product.id,
            name="Staging Project",
            mission="Test mission",
            description="Test description",
            tenant_key=test_tenant_key,
            status="inactive",
            staging_status="staging",
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)
        await db_session.commit()
        await db_session.refresh(project)

        result = await project_service.lifecycle.cancel_staging(project.id)
        assert isinstance(result, ProjectData)
        assert result.status == "cancelled"
        assert result.name == "Staging Project"

    @pytest.mark.asyncio
    async def test_update_project_returns_project_data(
        self, project_service: ProjectService, test_tenant_key: str, active_project
    ):
        result = await project_service.update_project(active_project.id, {"name": "Updated Name"})
        assert isinstance(result, ProjectData)
        assert result.name == "Updated Name"
        assert result.id == active_project.id

    @pytest.mark.asyncio
    async def test_restore_project_returns_operation_result(
        self, project_service: ProjectService, test_tenant_key: str, db_session
    ):
        from giljo_mcp.models.products import Product
        from giljo_mcp.models.projects import Project

        _owning_product_project = Product(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            name=f"Owning Product {uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_project)
        project = Project(
            id=str(uuid4()),
            name="Completed Project",
            mission="Test mission",
            description="Test description",
            tenant_key=test_tenant_key,
            product_id=_owning_product_project.id,
            status="completed",
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)
        await db_session.commit()
        await db_session.refresh(project)

        result = await project_service.deletion.restore_project(project.id, tenant_key=test_tenant_key)
        assert isinstance(result, OperationResult)
        assert "restored" in result.message.lower()

    @pytest.mark.asyncio
    async def test_delete_project_returns_soft_delete_result(
        self, project_service: ProjectService, test_tenant_key: str, active_project
    ):
        result = await project_service.deletion.delete_project(active_project.id)
        assert isinstance(result, SoftDeleteResult)
        assert result.message == "Project deleted successfully"
        assert result.deleted_at is not None


@pytest.fixture
async def project_service(project_service_with_session):
    return project_service_with_session


@pytest.fixture
async def active_project(db_session, test_tenant_key):
    from giljo_mcp.models.projects import Project

    _owning_product_project = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid4()),
        name="Active Test Project",
        mission="Test mission",
        description="Test description",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def inactive_project(db_session, test_tenant_key):
    from giljo_mcp.models.projects import Project

    _owning_product_project = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid4()),
        name="Inactive Test Project",
        mission="Test mission",
        description="Test description",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        status="inactive",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def staged_project(db_session, test_tenant_key):
    from giljo_mcp.models.projects import Project

    _owning_product_project = Product(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"Owning Product {uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid4()),
        name="Staged Test Project",
        mission="Staged mission",
        description="Test description",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        status="inactive",
        staging_status="staged",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project
