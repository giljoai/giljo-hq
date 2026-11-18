# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio

from api.startup.context_tuning_banner import CONTEXT_TUNING_DUE_DEDUPE_KEY, emit_context_tuning_due_banner
from giljo_mcp.models.auth import User
from giljo_mcp.models.notifications import Notification
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.notification_service import NotificationService
from giljo_mcp.tools.write_memory_entry import _check_and_emit_tuning_staleness


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


@pytest_asyncio.fixture
async def user_id(db_session, tenant_key):
    unique_id = str(uuid4())[:8]
    user = User(
        id=str(uuid4()),
        username=f"u_{unique_id}",
        email=f"u_{unique_id}@example.com",
        full_name="Banner User",
        password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    return user.id


def _due(count, threshold=10):
    return {
        "product_id": "prod-1",
        "product_name": "Acme",
        "projects_since_tune": count,
        "threshold": threshold,
    }


async def _emit(service, tenant_key, count, threshold=10):
    await emit_context_tuning_due_banner(service, tenant_key, _due(count, threshold), tools_route="/tools")


async def _visible(service, tenant_key, user_id):
    rows = await service.list_for_user(tenant_key, user_id, surface="banner")
    return [r for r in rows if r.dedupe_key == CONTEXT_TUNING_DUE_DEDUPE_KEY]


async def _dismiss(service, tenant_key, user_id):
    rows = await _visible(service, tenant_key, user_id)
    assert len(rows) == 1
    await service.mark_dismissed(tenant_key, str(rows[0].id), user_id)
    assert await _visible(service, tenant_key, user_id) == []


class TestDismissedBannerReturns:
    @pytest.mark.asyncio
    async def test_dismissed_at_10_hidden_until_20_then_shows_20(self, service, tenant_key, user_id):
        await _emit(service, tenant_key, 10)
        await _dismiss(service, tenant_key, user_id)

        for count in range(11, 20):
            await _emit(service, tenant_key, count)
            assert await _visible(service, tenant_key, user_id) == [], f"shown at {count}"

        await _emit(service, tenant_key, 20)
        rows = await _visible(service, tenant_key, user_id)
        assert len(rows) == 1
        assert "20 projects" in rows[0].body
        assert rows[0].payload["projects_since_tune"] == 20

    @pytest.mark.asyncio
    async def test_dismissed_again_at_20_returns_at_30(self, service, tenant_key, user_id):
        await _emit(service, tenant_key, 10)
        await _dismiss(service, tenant_key, user_id)
        await _emit(service, tenant_key, 20)
        await _dismiss(service, tenant_key, user_id)

        await _emit(service, tenant_key, 29)
        assert await _visible(service, tenant_key, user_id) == []
        await _emit(service, tenant_key, 30)
        rows = await _visible(service, tenant_key, user_id)
        assert len(rows) == 1
        assert "30 projects" in rows[0].body

    @pytest.mark.asyncio
    async def test_non_default_threshold_follows_same_rule(self, service, tenant_key, user_id):
        await _emit(service, tenant_key, 3, threshold=3)
        await _dismiss(service, tenant_key, user_id)
        await _emit(service, tenant_key, 5, threshold=3)
        assert await _visible(service, tenant_key, user_id) == []
        await _emit(service, tenant_key, 6, threshold=3)
        assert len(await _visible(service, tenant_key, user_id)) == 1

    @pytest.mark.asyncio
    async def test_review_resolves_row_and_next_banner_is_fresh(self, service, tenant_key, user_id):
        await _emit(service, tenant_key, 10)
        await _dismiss(service, tenant_key, user_id)
        await emit_context_tuning_due_banner(service, tenant_key, None, tools_route="/tools")

        await _emit(service, tenant_key, 10)
        rows = await _visible(service, tenant_key, user_id)
        assert len(rows) == 1
        assert "10 projects" in rows[0].body

    @pytest.mark.asyncio
    async def test_legacy_dismissed_row_returns_at_next_multiple(self, service, tenant_key, user_id, db_session):
        await _emit(service, tenant_key, 10)
        row = (await _visible(service, tenant_key, user_id))[0]
        row = await db_session.get(Notification, row.id)
        row.dismissed_at = datetime.now(UTC)
        await db_session.commit()

        await _emit(service, tenant_key, 19)
        assert await _visible(service, tenant_key, user_id) == []
        await _emit(service, tenant_key, 20)
        assert len(await _visible(service, tenant_key, user_id)) == 1


class TestCloseoutNoticeRhythm:
    @staticmethod
    async def _fires(count, threshold=10):
        staleness = {
            "is_stale": count >= threshold,
            "projects_since_tune": count,
            "threshold": threshold,
            "enabled": True,
        }
        product = type("P", (), {"id": "prod-1", "name": "Acme"})()
        with (
            patch(
                "giljo_mcp.services.product_tuning_service.ProductTuningService.check_tuning_staleness",
                new=AsyncMock(return_value=staleness),
            ),
            patch("giljo_mcp.tools.write_memory_entry.emit_websocket_event", new=AsyncOnce()) as emit,
        ):
            await _check_and_emit_tuning_staleness(
                product=product, tenant_key="t1", db_manager=object(), user_id="user-1"
            )
        return emit.calls

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("count", "expected"), [(9, 0), (10, 1), (11, 0), (19, 0), (20, 1)])
    async def test_fires_only_at_multiples(self, count, expected):
        assert await self._fires(count) == expected


class AsyncOnce:

    def __init__(self):
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
