# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""REST contract for the operator's read watermark (FE-9586).

``POST /api/v1/threads/{id}/read`` is the fact the dashboard could never state.
The service test (tests/services/test_fe9586_operator_read_watermark.py) pins the
watermark semantics; this pins the SHIM: the identity comes from the session and
never from the body, the effect is visible on the caller's own card, tenant
isolation holds, and an unknown thread is refused rather than silently enrolling
the caller in nothing.

Parallel-safe: api_client fixture, fresh tenant per test, no ordering deps.
"""

from __future__ import annotations

import secrets
import uuid

import bcrypt
import pytest
from httpx import AsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed_tenant(db_manager) -> dict:
    """Org + user in a fresh isolated tenant.

    Deliberately the SAME construction as tests/api/test_comm_threads_endpoints.py
    rather than a fresh one: ``User.display_name`` is a derived property with no
    setter, so a hand-rolled seed passing it fails at ORM construction. Copying the
    working seed is how this file stays a test of the endpoint instead of a test of
    my own fixture.
    """
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(
            name=f"Org {suffix}",
            slug=f"org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
            first_name="Test",
            last_name=f"User{suffix}",
        )
        session.add(user)
        await session.flush()

        with tenant_session_context(session, tenant_key):
            await ensure_default_types_seeded(session, tenant_key)

        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        return {
            "tenant_key": tenant_key,
            "user_id": user.id,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
        }


async def _thread_with_a_post(api_client: AsyncClient, headers: dict) -> str:
    created = await api_client.post("/api/v1/threads", headers=headers, json={"subject": "T"})
    assert created.status_code == 200, created.text
    thread_id = created.json()["thread_id"]
    posted = await api_client.post(f"/api/v1/threads/{thread_id}/post", headers=headers, json={"content": "hi"})
    assert posted.status_code == 200, posted.text
    return thread_id


async def _my_card(api_client: AsyncClient, headers: dict, thread_id: str) -> dict:
    listed = await api_client.get("/api/v1/threads", headers=headers)
    assert listed.status_code == 200, listed.text
    return next(t for t in listed.json()["threads"] if t["thread_id"] == thread_id)


@pytest.mark.asyncio
async def test_marking_read_clears_the_callers_own_unread_card(api_client: AsyncClient, db_manager) -> None:
    """The whole point, end to end through the shim: the card stops claiming there is
    something new. Asserted with a positive control first, so a green here cannot mean
    "the flag was never true"."""
    seed = await _seed_tenant(db_manager)
    thread_id = await _thread_with_a_post(api_client, seed["headers"])

    assert (await _my_card(api_client, seed["headers"], thread_id))["unread"] is True

    resp = await api_client.post(f"/api/v1/threads/{thread_id}/read", headers=seed["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["participant_id"] == seed["user_id"]

    assert (await _my_card(api_client, seed["headers"], thread_id))["unread"] is False


@pytest.mark.asyncio
async def test_the_reader_is_the_session_not_the_body(api_client: AsyncClient, db_manager) -> None:
    """No body is accepted, so no caller can mark a thread read on someone else's
    behalf. A declared identity here would be an impersonation surface."""
    seed = await _seed_tenant(db_manager)
    thread_id = await _thread_with_a_post(api_client, seed["headers"])

    resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/read",
        headers=seed["headers"],
        json={"user_id": "somebody-else"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["participant_id"] == seed["user_id"]


@pytest.mark.asyncio
async def test_marking_read_is_idempotent_over_the_wire(api_client: AsyncClient, db_manager) -> None:
    """Write-on-open fires on every open, so the second call must be a clean no-op:
    cursor_advanced false because nothing was newer, not an error."""
    seed = await _seed_tenant(db_manager)
    thread_id = await _thread_with_a_post(api_client, seed["headers"])

    first = await api_client.post(f"/api/v1/threads/{thread_id}/read", headers=seed["headers"])
    second = await api_client.post(f"/api/v1/threads/{thread_id}/read", headers=seed["headers"])

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["cursor_advanced"] is False


@pytest.mark.asyncio
async def test_another_tenant_cannot_mark_this_thread_read(api_client: AsyncClient, db_manager) -> None:
    """Tenant isolation on a WRITE path: tenant B must not reach tenant A's thread,
    and A's card must be untouched by the attempt."""
    a = await _seed_tenant(db_manager)
    b = await _seed_tenant(db_manager)
    thread_id = await _thread_with_a_post(api_client, a["headers"])

    resp = await api_client.post(f"/api/v1/threads/{thread_id}/read", headers=b["headers"])

    assert resp.status_code == 404, resp.text
    assert (await _my_card(api_client, a["headers"], thread_id))["unread"] is True


@pytest.mark.asyncio
async def test_an_unknown_thread_is_refused(api_client: AsyncClient, db_manager) -> None:
    """404, not a silent enrolment in a thread that does not exist."""
    seed = await _seed_tenant(db_manager)

    resp = await api_client.post(f"/api/v1/threads/{uuid.uuid4()}/read", headers=seed["headers"])

    assert resp.status_code == 404, resp.text
