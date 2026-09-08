# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression tests for D16 (Headless S3d): a resolved banner used to emit no
WS event at all -- ``resolve_by_dedupe_key``, ``resolve_open_by_type``, and
the update-existing branch of ``upsert_by_dedupe_key`` committed silently.
An answered agent question (or any auto-cleared system condition) sat on
screen until the next full page load.

Covers the fix at the layer the bug actually lived in -- NotificationService
-- plus the CE banner family that calls through it end-to-end
(api/startup/background_tasks.py, _emit_pending_migrations_banner). The SaaS
family (src/giljo_mcp/saas/notifications/banner_emitter.py) gets the same
regression case in tests/saas/notifications/test_fe9501d_d16_saas_family.py
-- CE test code must never import from saas/ (edition isolation).

Parallel-safe: TransactionalTestContext (db_session) + no module globals.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.notification_service import NotificationService


@pytest_asyncio.fixture
async def tenant_key(db_session):
    unique_id = str(uuid4())[:8]
    org = Organization(
        id=str(uuid4()),
        tenant_key=f"d16_tenant_{unique_id}",
        name=f"Org {unique_id}",
        slug=f"org-{unique_id}",
        is_active=True,
    )
    db_session.add(org)
    await db_session.commit()
    return org.tenant_key


@pytest.fixture
def ws_manager():
    mock = AsyncMock()
    mock.broadcast_to_tenant = AsyncMock()
    return mock


@pytest_asyncio.fixture
async def service(db_manager, db_session, ws_manager):
    return NotificationService(db_manager=db_manager, websocket_manager=ws_manager, session=db_session)


def _events(mock, event_type: str) -> list:
    return [call for call in mock.broadcast_to_tenant.call_args_list if call.kwargs.get("event_type") == event_type]


class TestResolveByDedupeKeyEmitsResolved:
    """The service-layer fix: resolve_by_dedupe_key must broadcast
    notification:resolved with the resolved row's id, not commit silently."""

    @pytest.mark.asyncio
    async def test_resolving_an_open_row_emits_resolved_with_its_id(self, service, tenant_key, ws_manager):
        created = await service.create(
            tenant_key=tenant_key,
            notification_type="api_key.expiring_soon",
            severity="warning",
            title="API key expires soon",
            dedupe_key="d16:probe-1",
            surface="banner",
            payload={"api_key_id": "key-1", "name": "My Key", "expires_at": "2026-06-30T00:00:00+00:00"},
        )
        ws_manager.broadcast_to_tenant.reset_mock()

        rowcount = await service.resolve_by_dedupe_key(tenant_key, "d16:probe-1")

        assert rowcount == 1
        resolved_events = _events(ws_manager, "notification:resolved")
        assert len(resolved_events) == 1
        assert resolved_events[0].kwargs["data"]["ids"] == [str(created.id)]

    @pytest.mark.asyncio
    async def test_resolving_a_nonexistent_dedupe_key_emits_nothing(self, service, tenant_key, ws_manager):
        rowcount = await service.resolve_by_dedupe_key(tenant_key, "d16:never-existed")

        assert rowcount == 0
        assert _events(ws_manager, "notification:resolved") == []


class TestResolveOpenByTypeEmitsResolved:
    @pytest.mark.asyncio
    async def test_resolving_by_type_emits_resolved_with_ids(self, service, tenant_key, ws_manager):
        first = await service.create(
            tenant_key=tenant_key,
            notification_type="system.update_available",
            severity="info",
            title="Update available",
            dedupe_key="system.update_available:v1",
            surface="banner",
        )
        ws_manager.broadcast_to_tenant.reset_mock()

        rowcount = await service.resolve_open_by_type(tenant_key, "system.update_available")

        assert rowcount == 1
        resolved_events = _events(ws_manager, "notification:resolved")
        assert len(resolved_events) == 1
        assert resolved_events[0].kwargs["data"]["ids"] == [str(first.id)]


class TestUpsertUpdateBranchEmitsUpdated:
    """The update-existing branch of upsert_by_dedupe_key must broadcast
    notification:updated so a live client's copy stays current (e.g. a
    "5 pending migrations" row refreshing to "3 pending migrations")."""

    @pytest.mark.asyncio
    async def test_refreshing_an_open_row_emits_updated(self, service, tenant_key, ws_manager):
        await service.upsert_by_dedupe_key(
            tenant_key=tenant_key,
            notification_type="system.pending_migrations",
            severity="warning",
            title="5 database migrations pending",
            dedupe_key="system.pending_migrations",
            surface="banner",
            role_filter="admin",
            payload={"pending": 5, "head": "ce_0040"},
        )
        ws_manager.broadcast_to_tenant.reset_mock()

        updated = await service.upsert_by_dedupe_key(
            tenant_key=tenant_key,
            notification_type="system.pending_migrations",
            severity="warning",
            title="3 database migrations pending",
            dedupe_key="system.pending_migrations",
            surface="banner",
            role_filter="admin",
            payload={"pending": 3, "head": "ce_0040"},
        )

        updated_events = _events(ws_manager, "notification:updated")
        assert len(updated_events) == 1
        assert updated_events[0].kwargs["data"]["id"] == str(updated.id)
        assert updated_events[0].kwargs["data"]["title"] == "3 database migrations pending"
        # The insert path's notification:new must NOT also fire on an update.
        assert _events(ws_manager, "notification:new") == []


class TestCeBannerFamilyResolveIsLive:
    """CE family (background_tasks.py): a pending-migrations banner clearing
    (migrations applied) must broadcast notification:resolved, not just
    commit -- the exact D16 symptom for the CE emitter path."""

    @pytest.mark.asyncio
    async def test_pending_migrations_clearing_emits_resolved(self, service, tenant_key, ws_manager):
        from api.startup import background_tasks

        await background_tasks._emit_pending_migrations_banner(service, tenant_key, {"pending": 2, "head": "ce_0040"})
        ws_manager.broadcast_to_tenant.reset_mock()

        await background_tasks._emit_pending_migrations_banner(service, tenant_key, None)

        assert len(_events(ws_manager, "notification:resolved")) == 1
