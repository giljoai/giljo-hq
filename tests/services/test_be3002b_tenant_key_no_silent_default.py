# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.base import Base
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager, current_tenant


@pytest.fixture
async def project_service(project_service_with_session):
    return project_service_with_session


class TestTenantKeyNoSilentDefault:

    def test_project_tenant_key_has_no_callable_default(self):
        assert Project.__table__.c.tenant_key.default is None
        assert Project.__table__.c.tenant_key.server_default is None
        assert Project.__table__.c.tenant_key.nullable is False

    def test_project_id_pk_default_intact(self):
        assert Project.__table__.c.id.default is not None

    def test_no_loaded_model_auto_fills_tenant_key(self):
        offenders = [
            table.name
            for table in Base.metadata.tables.values()
            if "tenant_key" in table.c and table.c.tenant_key.default is not None
        ]
        assert offenders == [], f"models auto-fill tenant_key: {offenders}"


class TestCreateProjectTenantContext:

    @pytest.mark.asyncio
    async def test_create_without_tenant_context_raises_validation_error(self, db_manager, db_session):
        token = current_tenant.set(None)
        try:
            service = ProjectService(
                db_manager=db_manager,
                tenant_manager=TenantManager(),
                test_session=db_session,
            )
            assert service.tenant_manager.get_current_tenant() is None

            with pytest.raises(ValidationError) as exc_info:
                await service.create_project(
                    name="Orphan Project",
                    mission="Should never persist",
                )
            assert "tenant context" in str(exc_info.value).lower()

            assert not service._test_session.new
        finally:
            current_tenant.reset(token)

    @pytest.mark.asyncio
    async def test_create_with_explicit_tenant_key_persists(
        self, project_service: ProjectService, test_tenant_key: str, test_product
    ):
        project = await project_service.create_project(
            name="Legit Project",
            mission="Real mission",
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        assert project.tenant_key == test_tenant_key

        from sqlalchemy import select

        fetched = (
            await project_service._test_session.execute(select(Project).where(Project.id == project.id))
        ).scalar_one()
        assert fetched.tenant_key == test_tenant_key

    @pytest.mark.asyncio
    async def test_create_resolves_tenant_from_context(
        self, db_manager, db_session, test_tenant_key: str, test_product
    ):
        manager = TenantManager()
        manager.set_current_tenant(test_tenant_key)
        token = current_tenant.set(test_tenant_key)
        try:
            service = ProjectService(
                db_manager=db_manager,
                tenant_manager=manager,
                test_session=db_session,
            )
            project = await service.create_project(
                name="Context Project",
                mission="Resolved from context",
                product_id=test_product.id,
            )
            assert project.tenant_key == test_tenant_key
        finally:
            current_tenant.reset(token)
