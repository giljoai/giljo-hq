# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""IMP-6038 regression: upsert_by_dedupe_key resurface-after-hours behaviour.

NotificationService.upsert_by_dedupe_key(resurface_after_hours=N) must:
- Clear dismissed_at when an existing open row was dismissed MORE than N hours
  ago (the condition is still true — banner should reappear).
- Leave dismissed_at intact when the row was dismissed LESS than N hours ago
  (user recently dismissed; respect it).

These are service-layer tests exercised through NotificationService using the
test db_manager. The notification type used is ``system.skills_drift``
(the exact type used by the skills-drift banner) so payload validation passes.

Parallel-safe: each test uses a unique tenant_key (uuid suffix); the service
commits to db_manager's own sessions (not the transactional db_session), but
all rows are tenant-isolated so tests cannot cross-contaminate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models.notifications import Notification
from giljo_mcp.services.notification_service import NotificationService


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    """Directly set dismissed_at on a notification row (bypasses service layer).

    SEC-9276: Notification is now tenant-guard-registered. This helper looks up a
    single row by its globally-unique id (no tenant predicate) purely to seed test
    state for the resurface-after-hours behavior under test -- it is not exercising
    or verifying cross-tenant isolation, so the guard bypass here is legitimate test
    setup, not a mask over a real isolation gap.
    """
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(session, reason="test setup: seed dismissed_at by id", models=(Notification,)):
            await session.execute(
                update(Notification).where(Notification.id == notification_id).values(dismissed_at=dismissed_at)
            )
        await session.commit()


async def _fetch_notification(db_manager, notification_id: str) -> Notification | None:
    """Read a single notification row by its globally-unique id (see
    _set_dismissed_at above for why the bypass is legitimate here)."""
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(session, reason="test assert: read notification by id", models=(Notification,)):
            result = await session.execute(select(Notification).where(Notification.id == notification_id))
            return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_resurface_clears_dismissed_at_after_window(db_manager):
    """A row dismissed more than N hours ago gets dismissed_at cleared on re-upsert."""
    suffix = uuid4().hex[:8]
    tenant_key = f"resurface_old_{suffix}"
    dedupe_key = f"system.skills_drift.test_{suffix}"

    service = NotificationService(db_manager=db_manager)

    # Create the drift banner.
    notif = await _upsert_drift(service, tenant_key, dedupe_key)
    assert notif.dismissed_at is None

    # Simulate the user dismissing the banner 25 hours ago.
    dismissed_25h_ago = datetime.now(UTC) - timedelta(hours=25)
    await _set_dismissed_at(db_manager, notif.id, dismissed_25h_ago)

    # Confirm it's dismissed.
    row = await _fetch_notification(db_manager, notif.id)
    assert row.dismissed_at is not None

    # Re-emit drift with resurface_after_hours=24.
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

    # Drift persists and banner has resurfaced (dismissed_at cleared).
    row = await _fetch_notification(db_manager, notif.id)
    assert row is not None, "notification must still exist"
    assert row.resolved_at is None, "drift still present; row must remain open"
    assert row.dismissed_at is None, "dismissed_at must be cleared — banner should resurface after 24h window"


async def test_resurface_does_not_clear_recent_dismissal(db_manager):
    """A row dismissed less than N hours ago is left dismissed."""
    suffix = uuid4().hex[:8]
    tenant_key = f"resurface_new_{suffix}"
    dedupe_key = f"system.skills_drift.test2_{suffix}"

    service = NotificationService(db_manager=db_manager)

    notif = await _upsert_drift(service, tenant_key, dedupe_key)

    # Simulate dismissal 1 hour ago (within the 24h window).
    dismissed_1h_ago = datetime.now(UTC) - timedelta(hours=1)
    await _set_dismissed_at(db_manager, notif.id, dismissed_1h_ago)

    # Re-emit drift with resurface_after_hours=24.
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
    """Without resurface_after_hours, a dismissed row stays dismissed on re-upsert."""
    suffix = uuid4().hex[:8]
    tenant_key = f"resurface_noflag_{suffix}"
    dedupe_key = f"system.skills_drift.test3_{suffix}"

    service = NotificationService(db_manager=db_manager)

    notif = await _upsert_drift(service, tenant_key, dedupe_key)

    # Dismiss 48 hours ago.
    dismissed_48h_ago = datetime.now(UTC) - timedelta(hours=48)
    await _set_dismissed_at(db_manager, notif.id, dismissed_48h_ago)

    # Re-upsert WITHOUT resurface_after_hours.
    await _upsert_drift(service, tenant_key, dedupe_key)

    row = await _fetch_notification(db_manager, notif.id)
    assert row.dismissed_at is not None, "dismissed_at must NOT be cleared when resurface_after_hours is absent"
