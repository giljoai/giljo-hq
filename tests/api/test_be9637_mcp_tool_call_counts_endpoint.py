# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import McpToolCallMetric, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)
_ENDPOINT = "/api/v1/stats/mcp-tool-calls"


async def _seed_tenant_with_tool_counts(db_manager, counts: list[tuple[str, int, int]]) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()

        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        today = datetime.now(UTC).date()
        for tool_name, days_ago, call_count in counts:
            session.add(
                McpToolCallMetric(
                    tenant_key=tenant_key,
                    tool_name=tool_name,
                    day=today - timedelta(days=days_ago),
                    call_count=call_count,
                )
            )
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        return {
            "tenant_key": tenant_key,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
        }


@pytest_asyncio.fixture(scope="function")
async def seeded(db_manager) -> dict:
    return await _seed_tenant_with_tool_counts(
        db_manager,
        [
            ("health_check", 0, 3),
            ("health_check", 2, 4),
            ("list_projects", 1, 9),
            ("spawn_job", 40, 100),
        ],
    )


@pytest.mark.asyncio
async def test_counts_are_summed_over_the_window_and_ordered_busiest_first(
    api_client: AsyncClient, seeded: dict
) -> None:
    resp = await api_client.get(f"{_ENDPOINT}?days=30", headers=seeded["headers"])
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["window_days"] == 30
    totals = {row["tool_name"]: row["total_calls"] for row in body["tools"]}

    assert totals["list_projects"] == 9
    assert totals["health_check"] == 7, "two days of the same tool must sum, not overwrite"
    assert "spawn_job" not in totals, "a row 40 days old is outside a 30-day window"

    names = [row["tool_name"] for row in body["tools"]]
    assert names[:2] == ["list_projects", "health_check"], f"busiest first, got {names}"


@pytest.mark.asyncio
async def test_a_wider_window_reaches_the_older_row(api_client: AsyncClient, seeded: dict) -> None:
    resp = await api_client.get(f"{_ENDPOINT}?days=90", headers=seeded["headers"])
    assert resp.status_code == 200, resp.text
    totals = {row["tool_name"]: row["total_calls"] for row in resp.json()["tools"]}
    assert totals["spawn_job"] == 100


@pytest.mark.asyncio
async def test_one_tenants_tool_usage_never_reaches_another(api_client: AsyncClient, db_manager) -> None:
    tenant_a = await _seed_tenant_with_tool_counts(db_manager, [("health_check", 0, 5)])
    await _seed_tenant_with_tool_counts(db_manager, [("a_tool_only_tenant_b_calls", 0, 77)])

    resp = await api_client.get(_ENDPOINT, headers=tenant_a["headers"])
    assert resp.status_code == 200, resp.text
    names = {row["tool_name"] for row in resp.json()["tools"]}

    assert names == {"health_check"}, f"tenant A must see only its own tools, got {names}"


@pytest.mark.asyncio
async def test_the_window_is_bounded(api_client: AsyncClient, seeded: dict) -> None:
    resp = await api_client.get(f"{_ENDPOINT}?days=100000", headers=seeded["headers"])
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_unauthenticated_callers_are_refused(api_client: AsyncClient) -> None:
    resp = await api_client.get(_ENDPOINT)
    assert resp.status_code in (401, 403), resp.text
