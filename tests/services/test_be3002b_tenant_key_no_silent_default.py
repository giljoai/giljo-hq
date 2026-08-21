# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-3002b regression: projects.tenant_key has NO silent default.

Edition Scope: Both (projects is a CE-core table).

The bug class: ``projects.tenant_key`` carried a callable model default
(``default=generate_uuid``) AND ``ProjectService.create_project`` auto-minted a
``tk_<uuid>`` key when none was supplied. Either path silently fabricated a
phantom tenant for any INSERT that forgot to set ``tenant_key`` — and INSERTs
are the one statement class the tenant guard does not inspect, so the row became
invisible orphaned data under a freshly-minted tenant nobody owns.

These tests pin BOTH sides of the fix:
  * Model: no callable default on ``tenant_key`` (PK ``id`` default untouched).
  * Service: create with no resolvable tenant context raises ``ValidationError``
    (a clean 422 at the boundary), NOT a DB IntegrityError/500 and NOT a
    silently-minted phantom tenant.
  * Load-bearing happy path: create WITH a tenant_key (or via the auth-set
    tenant context) still succeeds and persists with that exact key.
"""

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.base import Base
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager, current_tenant


@pytest.fixture
async def project_service(project_service_with_session):
    """Alias for the shared-session ProjectService (tenant context preset)."""
    return project_service_with_session


class TestTenantKeyNoSilentDefault:
    """The model column must not auto-fill tenant_key."""

    def test_project_tenant_key_has_no_callable_default(self):
        """projects.tenant_key carries NO model default (the phantom-tenant source)."""
        assert Project.__table__.c.tenant_key.default is None
        assert Project.__table__.c.tenant_key.server_default is None
        # tenant_key stays NOT NULL — a forgotten key must fail loudly, not be filled.
        assert Project.__table__.c.tenant_key.nullable is False

    def test_project_id_pk_default_intact(self):
        """The PK id keeps its auto-generate default — only tenant_key changed."""
        assert Project.__table__.c.id.default is not None

    def test_no_loaded_model_auto_fills_tenant_key(self):
        """Defensive sweep: no mapped table has a callable default on tenant_key."""
        offenders = [
            table.name
            for table in Base.metadata.tables.values()
            if "tenant_key" in table.c and table.c.tenant_key.default is not None
        ]
        assert offenders == [], f"models auto-fill tenant_key: {offenders}"


class TestCreateProjectTenantContext:
    """Service-layer create_project tenant-context discipline (the failing layer)."""

    @pytest.mark.asyncio
    async def test_create_without_tenant_context_raises_validation_error(self, db_manager, db_session):
        """No explicit tenant_key AND no tenant context -> ValidationError, no phantom row."""
        # Fresh TenantManager with NO current tenant; force the process-global
        # contextvar to None so a value leaked by a prior test cannot resolve.
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
                    # tenant_key intentionally omitted
                )
            assert "tenant context" in str(exc_info.value).lower()

            # No phantom-tenant orphan row: the raise fires BEFORE the session is
            # opened, so the session never received the Project — nothing pending
            # to flush, nothing INSERTed.
            assert not service._test_session.new
        finally:
            current_tenant.reset(token)

    @pytest.mark.asyncio
    async def test_create_with_explicit_tenant_key_persists(
        self, project_service: ProjectService, test_tenant_key: str, test_product
    ):
        """LOAD-BEARING: explicit tenant_key -> succeeds and persists with that exact key."""
        # BE-9437: a project must name a product. Orthogonal to the tenant
        # discipline under test -- the product only has to exist for the row to
        # be writable at all.
        project = await project_service.create_project(
            name="Legit Project",
            mission="Real mission",
            tenant_key=test_tenant_key,
            product_id=test_product.id,
        )
        assert project.tenant_key == test_tenant_key

        # Round-trip: the row is readable under that tenant key.
        from sqlalchemy import select

        fetched = (
            await project_service._test_session.execute(select(Project).where(Project.id == project.id))
        ).scalar_one()
        assert fetched.tenant_key == test_tenant_key

    @pytest.mark.asyncio
    async def test_create_resolves_tenant_from_context(
        self, db_manager, db_session, test_tenant_key: str, test_product
    ):
        """LOAD-BEARING: no explicit tenant_key but context set -> uses the context tenant."""
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
                product_id=test_product.id,  # BE-9437: required, orthogonal to tenant resolution
                # tenant_key omitted -> resolved from tenant context
            )
            assert project.tenant_key == test_tenant_key
        finally:
            current_tenant.reset(token)
