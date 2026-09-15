# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.auth import User
from giljo_mcp.models.notifications import Notification
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.notification_service import NotificationService


VALID_PAYLOAD = {
    "api_key_id": "key-123",
    "name": "My Key",
    "expires_at": "2026-06-30T00:00:00+00:00",
}


@pytest_asyncio.fixture
async def service(db_manager, db_session):
    return NotificationService(db_manager=db_manager, websocket_manager=None, session=db_session)


@pytest_asyncio.fixture
async def tenant_key(db_session):
    unique_id = str(uuid4())[:8]
    org = Organization(
        id=str(uuid4()),
        tenant_key=f"test_tenant_{unique_id}",
        name=f"Org {unique_id}",
        slug=f"org-{unique_id}",
        is_active=True,
    )
    db_session.add(org)
    await db_session.commit()
    return org.tenant_key


async def _make_user(db_session, tenant_key: str) -> str:
    unique_id = str(uuid4())[:8]
    user = User(
        id=str(uuid4()),
        username=f"nuser_{unique_id}",
        email=f"nuser_{unique_id}@example.com",
        full_name="Notif User",
        password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    return user.id


@pytest_asyncio.fixture
async def user_id(db_session, tenant_key):
    return await _make_user(db_session, tenant_key)


def _create_kwargs(**overrides) -> dict:
    base = {
        "notification_type": "api_key.expiring_soon",
        "severity": "warning",
        "title": "API key expires soon",
        "dedupe_key": "api_key.expiring_soon:key-123",
        "payload": dict(VALID_PAYLOAD),
    }
    base.update(overrides)
    return base


class TestNotificationCreate:
    @pytest.mark.asyncio
    async def test_create_persists_notification(self, service, tenant_key, db_session):
        result = await service.create(tenant_key=tenant_key, **_create_kwargs())

        assert result.id is not None
        assert result.type == "api_key.expiring_soon"
        assert result.severity == "warning"
        assert result.payload["api_key_id"] == "key-123"

    @pytest.mark.asyncio
    async def test_create_dedupes_open_notification(self, service, tenant_key, db_session):
        first = await service.create(tenant_key=tenant_key, **_create_kwargs())
        second = await service.create(tenant_key=tenant_key, **_create_kwargs())

        assert first.id == second.id
        stmt = select(Notification).where(
            Notification.tenant_key == tenant_key,
            Notification.dedupe_key == "api_key.expiring_soon:key-123",
        )
        rows = (await db_session.execute(stmt)).scalars().all()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_create_rejects_invalid_severity(self, service, tenant_key):
        with pytest.raises(ValidationError, match="Invalid notification severity"):
            await service.create(tenant_key=tenant_key, **_create_kwargs(severity="nope"))

    @pytest.mark.asyncio
    async def test_create_rejects_unknown_type(self, service, tenant_key):
        with pytest.raises(ValidationError, match="Unknown notification type"):
            await service.create(
                tenant_key=tenant_key,
                **_create_kwargs(notification_type="not.registered", payload={}),
            )

    @pytest.mark.asyncio
    async def test_create_rejects_bad_payload(self, service, tenant_key):
        with pytest.raises(ValidationError, match="Invalid notification payload"):
            await service.create(
                tenant_key=tenant_key,
                **_create_kwargs(payload={"api_key_id": "only-this"}),
            )


class TestNotificationListAndLifecycle:
    @pytest.mark.asyncio
    async def test_list_includes_user_and_tenant_scoped(self, service, tenant_key, user_id):
        await service.create(
            tenant_key=tenant_key,
            user_id=user_id,
            **_create_kwargs(dedupe_key="api_key.expiring_soon:user-key"),
        )
        await service.create(
            tenant_key=tenant_key,
            user_id=None,
            **_create_kwargs(dedupe_key="api_key.expiring_soon:tenant-key"),
        )

        rows = await service.list_for_user(tenant_key, user_id)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_list_excludes_other_users(self, service, tenant_key, user_id, db_session):
        await service.create(
            tenant_key=tenant_key,
            user_id=user_id,
            **_create_kwargs(dedupe_key="api_key.expiring_soon:other"),
        )
        other_user_id = await _make_user(db_session, tenant_key)

        rows = await service.list_for_user(tenant_key, other_user_id)
        assert rows == []

    @pytest.mark.asyncio
    async def test_list_excludes_dismissed_by_default(self, service, tenant_key, user_id):
        created = await service.create(tenant_key=tenant_key, user_id=user_id, **_create_kwargs())
        await service.mark_dismissed(tenant_key, created.id, user_id)

        assert await service.list_for_user(tenant_key, user_id) == []
        assert len(await service.list_for_user(tenant_key, user_id, include_dismissed=True)) == 1

    @pytest.mark.asyncio
    async def test_mark_read_sets_read_at(self, service, tenant_key, user_id):
        created = await service.create(tenant_key=tenant_key, user_id=user_id, **_create_kwargs())

        updated = await service.mark_read(tenant_key, created.id, user_id)
        assert updated.read_at is not None

    @pytest.mark.asyncio
    async def test_mark_read_unknown_id_raises(self, service, tenant_key):
        with pytest.raises(ResourceNotFoundError):
            await service.mark_read(tenant_key, str(uuid4()), str(uuid4()))

    @pytest.mark.asyncio
    async def test_resolve_clears_then_allows_reemit(self, service, tenant_key):
        first = await service.create(tenant_key=tenant_key, **_create_kwargs())

        resolved = await service.resolve_by_dedupe_key(tenant_key, "api_key.expiring_soon:key-123")
        assert resolved == 1

        second = await service.create(tenant_key=tenant_key, **_create_kwargs())
        assert second.id != first.id

    @pytest.mark.asyncio
    async def test_expires_at_is_persisted(self, service, tenant_key):
        expires = datetime.now(UTC) + timedelta(days=5)
        result = await service.create(tenant_key=tenant_key, expires_at=expires, **_create_kwargs())
        assert result.expires_at is not None


async def _make_user_with_role(db_session, tenant_key: str, role: str) -> str:
    unique_id = str(uuid4())[:8]
    user = User(
        id=str(uuid4()),
        username=f"nuser_{unique_id}",
        email=f"nuser_{unique_id}@example.com",
        full_name="Notif User",
        password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode("utf-8"),
        role=role,
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    return user.id


class TestNotificationBannerColumns:

    @pytest.mark.asyncio
    async def test_create_persists_banner_columns(self, service, tenant_key):
        result = await service.create(
            tenant_key=tenant_key,
            surface="banner",
            role_filter="admin",
            cta_label="View status",
            cta_route="system-status",
            dismissible=False,
            **_create_kwargs(dedupe_key="api_key.expiring_soon:banner"),
        )
        assert result.surface == "banner"
        assert result.role_filter == "admin"
        assert result.cta_label == "View status"
        assert result.cta_route == "system-status"
        assert result.dismissible is False

    @pytest.mark.asyncio
    async def test_create_defaults_surface_bell_dismissible_true(self, service, tenant_key):
        result = await service.create(tenant_key=tenant_key, **_create_kwargs())
        assert result.surface == "bell"
        assert result.dismissible is True
        assert result.role_filter is None

    @pytest.mark.asyncio
    async def test_create_rejects_invalid_surface(self, service, tenant_key):
        with pytest.raises(ValidationError, match="Invalid notification surface"):
            await service.create(tenant_key=tenant_key, surface="popup", **_create_kwargs())

    @pytest.mark.asyncio
    async def test_list_filters_by_surface(self, service, tenant_key, user_id):
        await service.create(
            tenant_key=tenant_key,
            user_id=user_id,
            surface="bell",
            **_create_kwargs(dedupe_key="api_key.expiring_soon:bell-row"),
        )
        await service.create(
            tenant_key=tenant_key,
            user_id=user_id,
            surface="banner",
            **_create_kwargs(dedupe_key="api_key.expiring_soon:banner-row"),
        )
        both = await service.create(
            tenant_key=tenant_key,
            user_id=user_id,
            surface="both",
            **_create_kwargs(dedupe_key="api_key.expiring_soon:both-row"),
        )

        banners = await service.list_for_user(tenant_key, user_id, surface="banner")
        banner_ids = {r.id for r in banners}
        assert both.id in banner_ids
        assert all(r.surface in ("banner", "both") for r in banners)
        assert len(banner_ids) == 2

    @pytest.mark.asyncio
    async def test_role_filter_excludes_non_admin(self, service, tenant_key, db_session):
        admin_id = await _make_user_with_role(db_session, tenant_key, "admin")
        dev_id = await _make_user_with_role(db_session, tenant_key, "developer")

        await service.create(
            tenant_key=tenant_key,
            user_id=None,
            role_filter="admin",
            **_create_kwargs(dedupe_key="system.pending_migrations"),
        )

        admin_rows = await service.list_for_user(tenant_key, admin_id)
        dev_rows = await service.list_for_user(tenant_key, dev_id)

        assert len(admin_rows) == 1
        assert dev_rows == []


class TestUpsertByDedupeKey:

    @pytest.mark.asyncio
    async def test_upsert_creates_when_absent(self, service, tenant_key):
        result = await service.upsert_by_dedupe_key(
            tenant_key=tenant_key,
            notification_type="system.pending_migrations",
            severity="warning",
            title="2 pending migrations",
            dedupe_key="system.pending_migrations",
            surface="banner",
            role_filter="admin",
            payload={"pending": 2, "head": "ce_0040"},
        )
        assert result.id is not None
        assert result.surface == "banner"
        assert result.payload["pending"] == 2

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_open_row(self, service, tenant_key, db_session):
        first = await service.upsert_by_dedupe_key(
            tenant_key=tenant_key,
            notification_type="system.pending_migrations",
            severity="warning",
            title="2 pending migrations",
            dedupe_key="system.pending_migrations",
            surface="banner",
            role_filter="admin",
            payload={"pending": 2, "head": "ce_0040"},
        )
        second = await service.upsert_by_dedupe_key(
            tenant_key=tenant_key,
            notification_type="system.pending_migrations",
            severity="error",
            title="5 pending migrations",
            dedupe_key="system.pending_migrations",
            surface="banner",
            role_filter="admin",
            cta_label="Apply",
            cta_route="system-status",
            payload={"pending": 5, "head": "ce_0041"},
        )

        assert first.id == second.id
        assert second.payload["pending"] == 5
        assert second.severity == "error"
        assert second.title == "5 pending migrations"
        assert second.cta_label == "Apply"

        stmt = select(Notification).where(
            Notification.tenant_key == tenant_key,
            Notification.dedupe_key == "system.pending_migrations",
        )
        rows = (await db_session.execute(stmt)).scalars().all()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_create_does_not_update_payload_but_upsert_does(self, service, tenant_key):
        await service.create(
            tenant_key=tenant_key,
            notification_type="system.pending_migrations",
            severity="warning",
            title="2 pending",
            dedupe_key="system.pending_migrations",
            surface="banner",
            payload={"pending": 2, "head": "ce_0040"},
        )
        after_create = await service.create(
            tenant_key=tenant_key,
            notification_type="system.pending_migrations",
            severity="error",
            title="9 pending",
            dedupe_key="system.pending_migrations",
            surface="banner",
            payload={"pending": 9, "head": "ce_0099"},
        )
        assert after_create.payload["pending"] == 2

        after_upsert = await service.upsert_by_dedupe_key(
            tenant_key=tenant_key,
            notification_type="system.pending_migrations",
            severity="error",
            title="9 pending",
            dedupe_key="system.pending_migrations",
            surface="banner",
            payload={"pending": 9, "head": "ce_0099"},
        )
        assert after_upsert.payload["pending"] == 9

    @pytest.mark.asyncio
    async def test_upsert_rejects_unknown_type(self, service, tenant_key):
        with pytest.raises(ValidationError, match="Unknown notification type"):
            await service.upsert_by_dedupe_key(
                tenant_key=tenant_key,
                notification_type="not.registered",
                severity="warning",
                title="x",
                dedupe_key="x",
                payload={},
            )
