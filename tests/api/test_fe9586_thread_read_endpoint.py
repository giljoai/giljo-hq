# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    seed = await _seed_tenant(db_manager)
    thread_id = await _thread_with_a_post(api_client, seed["headers"])

    assert (await _my_card(api_client, seed["headers"], thread_id))["unread"] is True

    resp = await api_client.post(f"/api/v1/threads/{thread_id}/read", headers=seed["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["participant_id"] == seed["user_id"]

    assert (await _my_card(api_client, seed["headers"], thread_id))["unread"] is False


@pytest.mark.asyncio
async def test_the_reader_is_the_session_not_the_body(api_client: AsyncClient, db_manager) -> None:
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
    seed = await _seed_tenant(db_manager)
    thread_id = await _thread_with_a_post(api_client, seed["headers"])

    first = await api_client.post(f"/api/v1/threads/{thread_id}/read", headers=seed["headers"])
    second = await api_client.post(f"/api/v1/threads/{thread_id}/read", headers=seed["headers"])

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["cursor_advanced"] is False


@pytest.mark.asyncio
async def test_another_tenant_cannot_mark_this_thread_read(api_client: AsyncClient, db_manager) -> None:
    a = await _seed_tenant(db_manager)
    b = await _seed_tenant(db_manager)
    thread_id = await _thread_with_a_post(api_client, a["headers"])

    resp = await api_client.post(f"/api/v1/threads/{thread_id}/read", headers=b["headers"])

    assert resp.status_code == 404, resp.text
    assert (await _my_card(api_client, a["headers"], thread_id))["unread"] is True


@pytest.mark.asyncio
async def test_an_unknown_thread_is_refused(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)

    resp = await api_client.post(f"/api/v1/threads/{uuid.uuid4()}/read", headers=seed["headers"])

    assert resp.status_code == 404, resp.text
