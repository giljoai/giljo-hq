# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


@pytest.fixture
async def project_service(project_service_with_session):
    return project_service_with_session


@pytest_asyncio.fixture
async def be_taxonomy(db_session, test_tenant_key) -> TaxonomyType:
    tt = TaxonomyType(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        abbreviation="BE",
        label="Backend",
        color="#1f6feb",
        sort_order=1,
    )
    db_session.add(tt)
    await db_session.commit()
    await db_session.refresh(tt)
    return tt


@pytest_asyncio.fixture
async def active_product(db_session, test_tenant_key) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"BE-9663 Product {uuid4().hex[:6]}",
        description="Product for BE-9663 revive tests",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_project_update = AsyncMock()
    return ws


@pytest_asyncio.fixture
async def ws_mock() -> MagicMock:
    return _mock_ws()


@pytest_asyncio.fixture
async def project_service_ws(db_manager, db_session, test_tenant_key, ws_mock) -> ProjectService:
    tm = TenantManager()
    tm.set_current_tenant(test_tenant_key)
    return ProjectService(db_manager=db_manager, tenant_manager=tm, test_session=db_session, websocket_manager=ws_mock)


class TestReviveClearsDeletedAt:

    @pytest.mark.asyncio
    async def test_reviving_via_update_project_does_not_let_a_new_project_reuse_its_serial(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        trashed = await project_service.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        assert trashed.series_number == 1

        await project_service.deletion.delete_project(project_id=trashed.id)

        revived = await project_service.update_project(project_id=trashed.id, updates={"status": "inactive"})

        revived_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        assert revived_row.deleted_at is None, "revive via update_project must clear deleted_at"

        newcomer = await project_service.create_project(
            name="Newcomer",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )

        assert newcomer.series_number != revived.series_number, (
            "a project revived through update_project must not have its serial reissued "
            f"to a new project (both are {newcomer.series_number})"
        )

    @pytest.mark.asyncio
    async def test_reviving_via_update_project_mints_a_fresh_serial_like_restore_does(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        trashed = await project_service.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        original_serial = trashed.series_number
        await project_service.deletion.delete_project(project_id=trashed.id)

        reused_by = await project_service.create_project(
            name="Reused the freed serial",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        assert reused_by.series_number == original_serial

        revived = await project_service.update_project(project_id=trashed.id, updates={"status": "inactive"})

        assert revived.series_number != original_serial, (
            "revive must mint a fresh serial, not resurrect the old (already-reused) number"
        )
        assert revived.series_number != reused_by.series_number


class TestReviveClearsDeletedAtStaleRowTolerance:

    @pytest.mark.asyncio
    async def test_stale_deleted_at_on_a_live_project_does_not_free_its_serial(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        stale = await project_service.create_project(
            name="Stale",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        stale_row = (await db_session.execute(select(Project).where(Project.id == stale.id))).scalar_one()
        stale_row.deleted_at = datetime.now(UTC)
        await db_session.commit()

        newcomer = await project_service.create_project(
            name="Newcomer",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )

        assert newcomer.series_number != stale.series_number, (
            "a live project with a stale deleted_at must not free its serial for reuse"
        )


class TestReviveBroadcastsStatusChanged:

    @pytest.mark.asyncio
    async def test_reviving_deleted_project_broadcasts_status_changed(
        self,
        project_service_ws: ProjectService,
        ws_mock: MagicMock,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        trashed = await project_service_ws.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service_ws.deletion.delete_project(project_id=trashed.id)
        ws_mock.broadcast_project_update.reset_mock()

        await project_service_ws.update_project(project_id=trashed.id, updates={"status": "inactive"})

        ws_mock.broadcast_project_update.assert_awaited()
        _, kwargs = ws_mock.broadcast_project_update.call_args
        assert kwargs["project_id"] == trashed.id
        assert kwargs["update_type"] == "status_changed", (
            "a revive over the harness door must broadcast so an open dashboard refreshes off the trash view"
        )

    @pytest.mark.asyncio
    async def test_reviving_completed_project_broadcasts_status_changed(
        self,
        project_service_ws: ProjectService,
        ws_mock: MagicMock,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        finished = await project_service_ws.create_project(
            name="Finished",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        finished_row = (await db_session.execute(select(Project).where(Project.id == finished.id))).scalar_one()
        finished_row.status = "completed"
        await db_session.commit()
        ws_mock.broadcast_project_update.reset_mock()

        await project_service_ws.update_project(project_id=finished.id, updates={"status": "inactive"})

        ws_mock.broadcast_project_update.assert_awaited()
        _, kwargs = ws_mock.broadcast_project_update.call_args
        assert kwargs["project_id"] == finished.id
        assert kwargs["update_type"] == "status_changed"


class TestReviveDeletedToOtherTargetStatuses:

    @pytest.mark.asyncio
    async def test_revive_deleted_directly_to_parked_clears_deleted_at_and_serial_not_reused(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        trashed = await project_service.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service.deletion.delete_project(project_id=trashed.id)

        revived = await project_service.update_project(project_id=trashed.id, updates={"status": "parked"})

        assert revived.status == ProjectStatus.PARKED
        revived_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        assert revived_row.deleted_at is None, "deleted -> parked must clear deleted_at"

        newcomer = await project_service.create_project(
            name="Newcomer",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        assert newcomer.series_number != revived.series_number

    @pytest.mark.asyncio
    async def test_revive_deleted_directly_to_completed_clears_deleted_at_and_serial_not_reused(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        trashed = await project_service.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service.deletion.delete_project(project_id=trashed.id)

        revived = await project_service.update_project(project_id=trashed.id, updates={"status": "completed"})

        assert revived.status == ProjectStatus.COMPLETED
        revived_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        assert revived_row.deleted_at is None, "deleted -> completed must clear deleted_at"

        newcomer = await project_service.create_project(
            name="Newcomer",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        assert newcomer.series_number != revived.series_number

    @pytest.mark.asyncio
    async def test_revive_deleted_directly_to_cancelled_clears_deleted_at_and_serial_not_reused(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        trashed = await project_service.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service.deletion.delete_project(project_id=trashed.id)

        revived = await project_service.update_project(project_id=trashed.id, updates={"status": "cancelled"})

        assert revived.status == ProjectStatus.CANCELLED
        revived_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        assert revived_row.deleted_at is None, "deleted -> cancelled must clear deleted_at"

        newcomer = await project_service.create_project(
            name="Newcomer",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        assert newcomer.series_number != revived.series_number

    @pytest.mark.asyncio
    async def test_revive_deleted_directly_to_superseded_clears_deleted_at_and_serial_not_reused(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        successor = await project_service.create_project(
            name="Successor",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        trashed = await project_service.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service.deletion.delete_project(project_id=trashed.id)

        revived = await project_service.update_project(
            project_id=trashed.id,
            updates={"status": "superseded", "successor_project_id": successor.id},
        )

        assert revived.status == ProjectStatus.SUPERSEDED
        revived_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        assert revived_row.deleted_at is None, "deleted -> superseded must clear deleted_at"

        newcomer = await project_service.create_project(
            name="Newcomer",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        assert newcomer.series_number != revived.series_number


class TestStaleDeletedAtProjectCanStillBeTrashed:

    @pytest.mark.asyncio
    async def test_stale_deleted_at_project_can_still_be_trashed(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        stale = await project_service.create_project(
            name="Stale",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        stale_row = (await db_session.execute(select(Project).where(Project.id == stale.id))).scalar_one()
        stale_row.deleted_at = datetime.now(UTC)
        await db_session.commit()

        await project_service.deletion.delete_project(project_id=stale.id)

        trashed_row = (await db_session.execute(select(Project).where(Project.id == stale.id))).scalar_one()
        assert trashed_row.status == ProjectStatus.DELETED
        assert trashed_row.deleted_at is not None


class TestReviveDeletedGatedOnUserMutableTarget:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", ["deleted", "terminated"])
    async def test_deleted_source_to_non_user_mutable_target_is_a_noop(
        self,
        target: str,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        trashed = await project_service.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service.deletion.delete_project(project_id=trashed.id)
        before_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        original_deleted_at = before_row.deleted_at
        original_serial = before_row.series_number
        assert original_deleted_at is not None

        await project_service.update_project(project_id=trashed.id, updates={"status": target})

        after_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        assert after_row.deleted_at == original_deleted_at, (
            f"status={target!r} on an already-trashed project must not un-trash it -- "
            f"deleted_at changed from {original_deleted_at} to {after_row.deleted_at}"
        )
        assert after_row.series_number == original_serial, (
            f"status={target!r} on an already-trashed project must not re-mint its serial"
        )


class TestReviveDeletedValidatesBeforeRestoring:

    @pytest.mark.asyncio
    async def test_revive_to_superseded_without_successor_leaves_trash_state_untouched(
        self,
        project_service_ws: ProjectService,
        ws_mock: MagicMock,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        trashed = await project_service_ws.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service_ws.deletion.delete_project(project_id=trashed.id)
        before_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        original_deleted_at = before_row.deleted_at
        original_serial = before_row.series_number
        ws_mock.broadcast_project_update.reset_mock()

        with pytest.raises(ValidationError) as exc_info:
            await project_service_ws.update_project(project_id=trashed.id, updates={"status": "superseded"})
        assert exc_info.value.error_code == "SUPERSEDE_REQUIRES_SUCCESSOR"

        after_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        assert after_row.deleted_at == original_deleted_at, "a rejected revive must leave deleted_at set"
        assert after_row.series_number == original_serial, "a rejected revive must not re-mint the serial"
        ws_mock.broadcast_project_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revive_to_superseded_with_ineligible_successor_leaves_trash_state_untouched(
        self,
        project_service_ws: ProjectService,
        ws_mock: MagicMock,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        ineligible_successor = await project_service_ws.create_project(
            name="Ineligible successor",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        successor_row = (
            await db_session.execute(select(Project).where(Project.id == ineligible_successor.id))
        ).scalar_one()
        successor_row.status = ProjectStatus.CANCELLED
        await db_session.commit()

        trashed = await project_service_ws.create_project(
            name="Trashed",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service_ws.deletion.delete_project(project_id=trashed.id)
        before_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        original_deleted_at = before_row.deleted_at
        original_serial = before_row.series_number
        ws_mock.broadcast_project_update.reset_mock()

        with pytest.raises(ValidationError) as exc_info:
            await project_service_ws.update_project(
                project_id=trashed.id,
                updates={"status": "superseded", "successor_project_id": ineligible_successor.id},
            )
        assert exc_info.value.error_code == "SUPERSEDE_REQUIRES_SUCCESSOR"

        after_row = (await db_session.execute(select(Project).where(Project.id == trashed.id))).scalar_one()
        assert after_row.deleted_at == original_deleted_at, "a rejected revive must leave deleted_at set"
        assert after_row.series_number == original_serial, "a rejected revive must not re-mint the serial"
        ws_mock.broadcast_project_update.assert_not_awaited()


class TestSupersedeValidationIsSingleOwner:

    @pytest.mark.asyncio
    async def test_both_doors_reject_the_same_invalid_supersede_identically(
        self,
        project_service: ProjectService,
        db_session,
        test_tenant_key: str,
        active_product: Product,
        be_taxonomy: TaxonomyType,
    ):
        plain_door = await project_service.create_project(
            name="Plain door",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        revive_door = await project_service.create_project(
            name="Revive door",
            mission="m",
            description="d",
            product_id=active_product.id,
            tenant_key=test_tenant_key,
            project_type_id=be_taxonomy.id,
        )
        await project_service.deletion.delete_project(project_id=revive_door.id)

        with pytest.raises(ValidationError) as plain_exc:
            await project_service.update_project(project_id=plain_door.id, updates={"status": "superseded"})
        with pytest.raises(ValidationError) as revive_exc:
            await project_service.update_project(project_id=revive_door.id, updates={"status": "superseded"})

        assert plain_exc.value.error_code == revive_exc.value.error_code == "SUPERSEDE_REQUIRES_SUCCESSOR"
        assert plain_exc.value.message == revive_exc.value.message, (
            "the plain write and the revive path must reject an invalid supersede identically -- "
            f"plain={plain_exc.value.message!r} revive={revive_exc.value.message!r}"
        )
