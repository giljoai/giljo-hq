# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models.notifications import Notification
from giljo_mcp.services.notification_service import NotificationService


pytestmark = pytest.mark.asyncio



_DRIFT_PAYLOAD = {
    "current": "2.0.0",
    "announced": "1.0.0",
    "message": "test drift",
}


async def _upsert_drift(service: NotificationService, tenant_key: str, dedupe_key: str) -> Notification:
    return await service.upsert_by_dedupe_key(
        tenant_key=tenant_key,
        notification_type="system.skills_drift",
        severity="info",
        title="Test drift banner",
        body="drift body",
        dedupe_key=dedupe_key,
        surface="banner",
        role_filter="admin",
        payload=_DRIFT_PAYLOAD,
        dismissible=True,
    )


async def _set_dismissed_at(db_manager, notification_id: str, dismissed_at: datetime) -> None:
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(session, reason="test setup: seed dismissed_at by id", models=(Notification,)):
            await session.execute(
                update(Notification).where(Notification.id == notification_id).values(dismissed_at=dismissed_at)
            )
        await session.commit()


async def _fetch_notification(db_manager, notification_id: str) -> Notification | None:
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(session, reason="test assert: read notification by id", models=(Notification,)):
            result = await session.execute(select(Notification).where(Notification.id == notification_id))
            return result.scalar_one_or_none()




async def test_resurface_clears_dismissed_at_after_window(db_manager):
    suffix = uuid4().hex[:8]
    tenant_key = f"resurface_old_{suffix}"
    dedupe_key = f"system.skills_drift.test_{suffix}"

    service = NotificationService(db_manager=db_manager)

    notif = await _upsert_drift(service, tenant_key, dedupe_key)
    assert notif.dismissed_at is None

    dismissed_25h_ago = datetime.now(UTC) - timedelta(hours=25)
    await _set_dismissed_at(db_manager, notif.id, dismissed_25h_ago)

    row = await _fetch_notification(db_manager, notif.id)
    assert row.dismissed_at is not None

    await service.upsert_by_dedupe_key(
        tenant_key=tenant_key,
        notification_type="system.skills_drift",
        severity="info",
        title="Test drift banner",
        body="drift body updated",
        dedupe_key=dedupe_key,
        surface="banner",
        role_filter="admin",
        payload=_DRIFT_PAYLOAD,
        dismissible=True,
        resurface_after_hours=24,
    )

    row = await _fetch_notification(db_manager, notif.id)
    assert row is not None, "notification must still exist"
    assert row.resolved_at is None, "drift still present; row must remain open"
    assert row.dismissed_at is None, "dismissed_at must be cleared — banner should resurface after 24h window"


async def test_resurface_does_not_clear_recent_dismissal(db_manager):
    suffix = uuid4().hex[:8]
    tenant_key = f"resurface_new_{suffix}"
    dedupe_key = f"system.skills_drift.test2_{suffix}"

    service = NotificationService(db_manager=db_manager)

    notif = await _upsert_drift(service, tenant_key, dedupe_key)

    dismissed_1h_ago = datetime.now(UTC) - timedelta(hours=1)
    await _set_dismissed_at(db_manager, notif.id, dismissed_1h_ago)

    await service.upsert_by_dedupe_key(
        tenant_key=tenant_key,
        notification_type="system.skills_drift",
        severity="info",
        title="Test drift banner",
        body="drift body updated",
        dedupe_key=dedupe_key,
        surface="banner",
        role_filter="admin",
        payload=_DRIFT_PAYLOAD,
        dismissible=True,
        resurface_after_hours=24,
    )

    row = await _fetch_notification(db_manager, notif.id)
    assert row is not None
    assert row.dismissed_at is not None, "dismissed_at must NOT be cleared — dismissal is within the 24h window"


async def test_resurface_not_triggered_without_flag(db_manager):
    suffix = uuid4().hex[:8]
    tenant_key = f"resurface_noflag_{suffix}"
    dedupe_key = f"system.skills_drift.test3_{suffix}"

    service = NotificationService(db_manager=db_manager)

    notif = await _upsert_drift(service, tenant_key, dedupe_key)

    dismissed_48h_ago = datetime.now(UTC) - timedelta(hours=48)
    await _set_dismissed_at(db_manager, notif.id, dismissed_48h_ago)

    await _upsert_drift(service, tenant_key, dedupe_key)

    row = await _fetch_notification(db_manager, notif.id)
    assert row.dismissed_at is not None, "dismissed_at must NOT be cleared when resurface_after_hours is absent"
