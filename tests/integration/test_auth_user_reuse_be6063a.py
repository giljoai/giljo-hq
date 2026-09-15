# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from giljo_mcp.auth.dependencies import get_current_user
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache


async def _seed_user(db_manager, *, is_active: bool = True):
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    user_id = str(uuid4())
    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"Reuse Org {uuid4().hex[:6]}",
            slug=f"reuse-{uuid4().hex[:8]}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"reuse_user_{uuid4().hex[:8]}",
                email=f"reuse_{uuid4().hex[:8]}@example.com",
                role="developer",
                tenant_key=tenant_key,
                is_active=is_active,
                org_id=org.id,
            )
        )
        await session.commit()
    return tenant_key, user_id


async def _load_user(db_manager, tenant_key: str, user_id: str):
    from sqlalchemy import select

    from giljo_mcp.database import tenant_isolation_bypass
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session,
            reason="test mirrors middleware username->user resolution",
            models=(User,),
        ):
            result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


def _mint(tenant_key: str, user_id: str) -> str:
    return JWTManager.create_access_token(
        user_id=UUID(user_id),
        username="reuse_user",
        role="developer",
        tenant_key=tenant_key,
    )


def _request(stashed_user=None) -> SimpleNamespace:
    state = SimpleNamespace()
    if stashed_user is not None:
        state.auth_user = stashed_user
    return SimpleNamespace(url=SimpleNamespace(path="/api/projects"), state=state)


class _UsersSelectCounter:

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and "from users" in normalized:
            self.count += 1


def _attach_counter(db_manager) -> tuple[_UsersSelectCounter, callable]:
    sync_engine = db_manager.async_engine.sync_engine
    counter = _UsersSelectCounter()
    event.listen(sync_engine, "before_cursor_execute", counter)

    def _detach() -> None:
        event.remove(sync_engine, "before_cursor_execute", counter)

    return counter, _detach


@pytest.mark.asyncio
async def test_stashed_user_reused_without_second_select(db_manager):
    clear_revocation_cache()
    tenant_key, user_id = await _seed_user(db_manager)
    token = _mint(tenant_key, user_id)
    stashed = await _load_user(db_manager, tenant_key, user_id)
    assert stashed is not None

    counter, detach = _attach_counter(db_manager)
    try:
        async with db_manager.get_session_async() as db:
            user = await get_current_user(
                request=_request(stashed_user=stashed),
                access_token=token,
                x_api_key=None,
                authorization=None,
                db=db,
            )
    finally:
        detach()

    assert str(user.id) == user_id
    assert counter.count == 0, f"expected reuse (0 users SELECT), got {counter.count}"
    clear_revocation_cache()


@pytest.mark.asyncio
async def test_no_stash_falls_back_to_single_select(db_manager):
    clear_revocation_cache()
    tenant_key, user_id = await _seed_user(db_manager)
    token = _mint(tenant_key, user_id)

    counter, detach = _attach_counter(db_manager)
    try:
        async with db_manager.get_session_async() as db:
            user = await get_current_user(
                request=_request(stashed_user=None),
                access_token=token,
                x_api_key=None,
                authorization=None,
                db=db,
            )
    finally:
        detach()

    assert str(user.id) == user_id
    assert counter.count == 1, f"expected one fallback users SELECT, got {counter.count}"
    clear_revocation_cache()


@pytest.mark.asyncio
async def test_deactivated_user_stash_is_not_trusted(db_manager):
    clear_revocation_cache()
    tenant_key, user_id = await _seed_user(db_manager, is_active=False)
    token = _mint(tenant_key, user_id)
    stashed = await _load_user(db_manager, tenant_key, user_id)
    assert stashed is not None
    assert stashed.is_active is False

    async with db_manager.get_session_async() as db:
        with pytest.raises(Exception) as exc:
            await get_current_user(
                request=_request(stashed_user=stashed),
                access_token=token,
                x_api_key=None,
                authorization=None,
                db=db,
            )
    assert getattr(exc.value, "status_code", None) == 401
    clear_revocation_cache()


@pytest.mark.asyncio
async def test_unauthenticated_request_still_rejected(db_manager):
    clear_revocation_cache()
    async with db_manager.get_session_async() as db:
        with pytest.raises(Exception) as exc:
            await get_current_user(
                request=_request(stashed_user=None),
                access_token=None,
                x_api_key=None,
                authorization=None,
                db=db,
            )
    assert getattr(exc.value, "status_code", None) == 401
    clear_revocation_cache()
