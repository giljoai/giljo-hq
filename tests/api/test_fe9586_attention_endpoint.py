# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""REST contract for the operator's attention read (FE-9586).

``GET /api/v1/threads/attention`` is the ONE read behind the thread-post banner
family. tests/services/test_fe9586_operator_attention.py pins the semantics; this
pins the SHIM: the route is not shadowed by ``GET /{thread_id}``, the reader is
the session, tenant isolation holds even between two operators who share a
display name, and an unauthenticated caller is refused rather than told it is all
caught up.

Note on the fixtures: a mention must be authored by SOMEBODY ELSE, because your
own post naming you is not being named. The REST post endpoint stamps the
authenticated user as the author, so these tests seed a second user in the same
tenant and post as them -- an operator posting their own name would be silently
excluded and the test would pass for the wrong reason.

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


async def _seed_tenant(db_manager, *, display_first: str = "Test", display_last: str | None = None) -> dict:
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
            first_name=display_first,
            last_name=(display_last if display_last is not None else f"User{suffix}"),
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
            "display_name": user.display_name,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
        }


async def _second_user(db_manager, tenant_key: str, org_id: str | None = None) -> dict:
    """Another user inside an EXISTING tenant, so one can name the other."""
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        if org_id is None:
            org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
            session.add(org)
            await session.flush()
            org_id = org.id
        user = User(
            username=f"agent_{suffix}",
            email=f"agent_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
            tenant_key=tenant_key,
            role="developer",
            org_id=org_id,
            first_name="Other",
            last_name=f"Person{suffix}",
        )
        session.add(user)
        await session.flush()
        user_id = user.id
        await session.commit()

    token = JWTManager.create_access_token(
        user_id=user_id, username=f"agent_{suffix}", role="developer", tenant_key=tenant_key
    )
    return {
        "user_id": user_id,
        "headers": {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        },
    }


async def _thread(api_client: AsyncClient, headers: dict) -> str:
    created = await api_client.post("/api/v1/threads", headers=headers, json={"subject": "T"})
    assert created.status_code == 200, created.text
    return created.json()["thread_id"]


@pytest.mark.asyncio
async def test_attention_is_declared_above_the_thread_id_route(api_client: AsyncClient, db_manager) -> None:
    """The shadowing trap, pinned as behaviour rather than trusted to file order.

    A literal path registered AFTER ``GET /{thread_id}`` is swallowed by it, and this
    call would be served as a thread whose id is the word "attention" -- a 404 that
    looks like a missing thread rather than a misregistered route. Asserting the
    payload SHAPE is what distinguishes the two.
    """
    seed = await _seed_tenant(db_manager)

    resp = await api_client.get("/api/v1/threads/attention", headers=seed["headers"])

    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"mentions", "directed_action"}


@pytest.mark.asyncio
async def test_attention_reports_a_post_naming_the_operator(api_client: AsyncClient, db_manager) -> None:
    """End to end through the shim, with the name resolved server-side from the
    session -- the client sends nothing but its cookie."""
    seed = await _seed_tenant(db_manager)
    other = await _second_user(db_manager, seed["tenant_key"])
    thread_id = await _thread(api_client, seed["headers"])
    posted = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=other["headers"],
        json={"content": f"{seed['display_name']}, please look at this"},
    )
    assert posted.status_code == 200, posted.text

    resp = await api_client.get("/api/v1/threads/attention", headers=seed["headers"])

    assert resp.status_code == 200, resp.text
    assert [m["thread_id"] for m in resp.json()["mentions"]] == [thread_id]


@pytest.mark.asyncio
async def test_attention_is_empty_for_a_quiet_tenant(api_client: AsyncClient, db_manager) -> None:
    """Negative control: a thread that names nobody reports nothing. Without this a
    read that returned every thread would pass the test above."""
    seed = await _seed_tenant(db_manager)
    thread_id = await _thread(api_client, seed["headers"])
    await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "routine status, nobody named"},
    )

    resp = await api_client.get("/api/v1/threads/attention", headers=seed["headers"])

    assert resp.json() == {"mentions": [], "directed_action": []}


@pytest.mark.asyncio
async def test_attention_does_not_reach_another_tenants_threads(api_client: AsyncClient, db_manager) -> None:
    """Two operators who happen to share a display name must not see each other's
    mentions. The seed gives both the same name deliberately."""
    a = await _seed_tenant(db_manager)
    b = await _seed_tenant(db_manager, display_first=a["display_name"].split()[0], display_last="")
    other = await _second_user(db_manager, a["tenant_key"])
    thread_id = await _thread(api_client, a["headers"])
    await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=other["headers"],
        json={"content": f"{b['display_name']} you are named in tenant A"},
    )

    resp = await api_client.get("/api/v1/threads/attention", headers=b["headers"])

    assert resp.json()["mentions"] == []


@pytest.mark.asyncio
async def test_attention_requires_authentication(api_client: AsyncClient, db_manager) -> None:
    """It reports one person's obligations, so an unauthenticated caller gets nothing
    -- not an empty list, which would read as "you are all caught up"."""
    resp = await api_client.get("/api/v1/threads/attention")

    assert resp.status_code in (401, 403), resp.text
