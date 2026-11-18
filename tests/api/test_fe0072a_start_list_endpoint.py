# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import bcrypt
import pytest
from httpx import AsyncClient

from api.endpoints.mcp_session import MCPSessionManager
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)
URL = "/api/onboarding/start-list"

EMPTY_BODY = {
    "rows": {
        "tool_connected": {"done": False, "live": False, "tool_name": None},
        "skills_installed": {"done": False},
        "product_exists": {"done": False, "product_name": None},
        "project_created": {"done": False, "project_id": None, "project_name": None},
        "project_staged": {"done": False, "has_project": False, "mode": None, "requested": False},
        "project_built": {"done": False, "in_progress": False, "awaiting_review": False},
    },
    "done_count": 0,
    "step_count": 6,
}


async def _seed_tenant(db_manager) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
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
        await session.commit()
        token = JWTManager.create_access_token(
            user_id=user.id, username=user.username, role="developer", tenant_key=tenant_key
        )
        return {
            "tenant_key": tenant_key,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
        }


async def _connect_tool(db_manager, tenant_key: str, client_name: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await MCPSessionManager(session).create_session(
                tenant_key=tenant_key,
                user_id=None,
                client_info={"name": client_name, "version": "1.0.0"},
                auth_method="oauth_jwt",
            )
            await session.commit()


async def test_start_list_refuses_a_caller_who_is_not_signed_in(api_client: AsyncClient) -> None:
    resp = await api_client.get(URL)

    assert resp.status_code == 401


async def test_start_list_for_a_fresh_account_has_exactly_the_contract_shape(
    api_client: AsyncClient, db_manager
) -> None:
    seed = await _seed_tenant(db_manager)

    resp = await api_client.get(URL, headers=seed["headers"])

    assert resp.status_code == 200, resp.text
    assert resp.json() == EMPTY_BODY


async def test_start_list_reflects_the_signed_in_accounts_real_progress(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    await _connect_tool(db_manager, seed["tenant_key"], "claude-code")
    await ProductService(db_manager, seed["tenant_key"]).create_product(name="Atlas")

    body = (await api_client.get(URL, headers=seed["headers"])).json()

    assert body["rows"]["tool_connected"] == {"done": True, "live": True, "tool_name": "Claude Code"}
    assert body["rows"]["product_exists"] == {"done": True, "product_name": "Atlas"}
    assert body["done_count"] == 2
    assert isinstance(body["done_count"], int)


async def test_start_list_takes_no_tenant_or_product_from_the_request(api_client: AsyncClient, db_manager) -> None:
    caller = await _seed_tenant(db_manager)
    other = await _seed_tenant(db_manager)
    await _connect_tool(db_manager, other["tenant_key"], "claude-code")
    other_product = await ProductService(db_manager, other["tenant_key"]).create_product(name="Not yours")

    resp = await api_client.get(
        URL,
        params={"tenant_key": other["tenant_key"], "product_id": other_product.id},
        headers=caller["headers"],
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == EMPTY_BODY


async def _seed_project(db_manager, tenant_key: str, name: str, **columns) -> str:
    from sqlalchemy import update

    from giljo_mcp.models import Project
    from giljo_mcp.services.project_service import ProjectService

    product = await ProductService(db_manager, tenant_key).create_product(name=f"Prod {uuid.uuid4().hex[:6]}")
    tm = TenantManager()
    tm.set_current_tenant(tenant_key)
    detail = await ProjectService(db_manager=db_manager, tenant_manager=tm).create_project(
        name=name, mission="m", product_id=product.id, tenant_key=tenant_key
    )
    if columns:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            with tenant_session_context(session, tenant_key):
                await session.execute(
                    update(Project).where(Project.id == detail.id, Project.tenant_key == tenant_key).values(**columns)
                )
                await session.commit()
    return detail.id


async def test_start_list_carries_the_six_step_fields_for_a_staged_project(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    project_id = await _seed_project(
        db_manager, seed["tenant_key"], "Add a search box", staging_status="staging_complete", execution_mode="subagent"
    )

    body = (await api_client.get(URL, headers=seed["headers"])).json()

    assert body["rows"]["project_created"] == {
        "done": True,
        "project_id": project_id,
        "project_name": "Add a search box",
    }
    assert body["rows"]["project_staged"] == {"done": True, "has_project": True, "mode": "subagent", "requested": False}
    assert body["rows"]["project_built"] == {"done": False, "in_progress": False, "awaiting_review": False}
    assert (body["done_count"], body["step_count"]) == (3, 6)


async def test_start_list_marks_a_launched_active_project_in_progress_and_a_cancelled_one_not(
    api_client: AsyncClient, db_manager
) -> None:
    now = datetime.now(UTC)
    seed = await _seed_tenant(db_manager)
    project_id = await _seed_project(
        db_manager,
        seed["tenant_key"],
        "Build it",
        status="active",
        staging_status="staging_complete",
        implementation_launched_at=now,
        ever_launched_at=now,
    )

    running = (await api_client.get(URL, headers=seed["headers"])).json()["rows"]["project_built"]
    await _set_status(db_manager, seed["tenant_key"], project_id, "cancelled")
    stopped = (await api_client.get(URL, headers=seed["headers"])).json()["rows"]["project_built"]

    assert running == {"done": False, "in_progress": True, "awaiting_review": False}
    assert stopped == {"done": False, "in_progress": False, "awaiting_review": False}


async def test_start_list_reads_a_finished_project_as_done_even_when_it_is_trashed(
    api_client: AsyncClient, db_manager
) -> None:
    now = datetime.now(UTC)
    seed = await _seed_tenant(db_manager)
    project_id = await _seed_project(
        db_manager,
        seed["tenant_key"],
        "Shipped",
        status="completed",
        staging_status="staging_complete",
        implementation_launched_at=now,
        ever_launched_at=now,
        closeout_executed_at=now,
        completed_at=now,
        reviewed_at=now,
    )

    finished = (await api_client.get(URL, headers=seed["headers"])).json()["rows"]["project_built"]
    await _set_status(db_manager, seed["tenant_key"], project_id, "deleted", deleted_at=now)
    trashed = (await api_client.get(URL, headers=seed["headers"])).json()["rows"]

    assert finished == {"done": True, "in_progress": False, "awaiting_review": False}
    assert trashed["project_built"] == {"done": True, "in_progress": False, "awaiting_review": False}
    assert trashed["project_created"] == {"done": False, "project_id": None, "project_name": None}


async def _set_status(db_manager, tenant_key: str, project_id: str, status: str, **extra) -> None:
    from sqlalchemy import update

    from giljo_mcp.models import Project

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await session.execute(
                update(Project)
                .where(Project.id == project_id, Project.tenant_key == tenant_key)
                .values(status=status, **extra)
            )
            await session.commit()


_AFTER_REVIEW_STEP = datetime(2026, 11, 17, tzinfo=UTC)
_BEFORE_REVIEW_STEP = datetime(2026, 10, 1, tzinfo=UTC)


def _closed(when: datetime, **extra) -> dict:
    return {
        "status": "completed",
        "staging_status": "staging_complete",
        "implementation_launched_at": when,
        "ever_launched_at": when,
        "closeout_executed_at": when,
        "completed_at": when,
        **extra,
    }


async def test_start_list_pins_row_four_to_the_first_project_and_reads_requested(
    api_client: AsyncClient, db_manager
) -> None:
    seed = await _seed_tenant(db_manager)
    first = await _seed_project(db_manager, seed["tenant_key"], "First idea", created_at=_BEFORE_REVIEW_STEP)
    await _seed_project(
        db_manager, seed["tenant_key"], "Newer idea", created_at=_AFTER_REVIEW_STEP, staging_status="staged"
    )

    rows = (await api_client.get(URL, headers=seed["headers"])).json()["rows"]

    assert rows["project_created"] == {"done": True, "project_id": first, "project_name": "First idea"}
    assert rows["project_staged"] == {"done": False, "has_project": True, "mode": None, "requested": True}


async def test_start_list_reads_row_six_awaiting_review_then_done_for_a_new_account(
    api_client: AsyncClient, db_manager
) -> None:
    seed = await _seed_tenant(db_manager)
    project_id = await _seed_project(db_manager, seed["tenant_key"], "Shipped", **_closed(_AFTER_REVIEW_STEP))

    waiting = (await api_client.get(URL, headers=seed["headers"])).json()
    await _set_status(db_manager, seed["tenant_key"], project_id, "completed", reviewed_at=_AFTER_REVIEW_STEP)
    reviewed = (await api_client.get(URL, headers=seed["headers"])).json()

    assert waiting["rows"]["project_built"] == {"done": False, "in_progress": False, "awaiting_review": True}
    assert waiting["done_count"] == 3
    assert reviewed["rows"]["project_built"] == {"done": True, "in_progress": False, "awaiting_review": False}
    assert reviewed["done_count"] == 4


async def test_start_list_keeps_an_account_that_finished_before_reviews_existed_at_done(
    api_client: AsyncClient, db_manager
) -> None:
    seed = await _seed_tenant(db_manager)
    await _seed_project(db_manager, seed["tenant_key"], "Old build", **_closed(_BEFORE_REVIEW_STEP))

    body = (await api_client.get(URL, headers=seed["headers"])).json()

    assert body["rows"]["project_built"] == {"done": True, "in_progress": False, "awaiting_review": False}
    assert body["done_count"] == 4
