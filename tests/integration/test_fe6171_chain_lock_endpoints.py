# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import secrets
import uuid
from datetime import UTC, datetime

import bcrypt
import pytest
import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("GILJO_MODE") == "saas",
        reason="CE chain REST contract; on SaaS an unlicensed tenant's writes are 402 by design",
    ),
]

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)
_MODE = "claude_code_cli"


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_agent_coordination():
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_context_module():
    yield


async def _seed_user(db_manager) -> dict:
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


async def _seed_project(db_manager, tenant_key: str) -> str:
    async with db_manager.get_session_async() as session:
        product = Product(
            id=str(uuid.uuid4()),
            name="Chain Product",
            description="desc",
            tenant_key=tenant_key,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(product)
        await session.flush()
        project = Project(
            id=str(uuid.uuid4()),
            name="Chain Project",
            description="human requirements",
            mission="mission",
            tenant_key=tenant_key,
            product_id=product.id,
            status=ProjectStatus.INACTIVE,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(project)
        await session.commit()
        return project.id


@pytest_asyncio.fixture(scope="function")
async def api_client(db_manager):
    from unittest.mock import MagicMock

    from api.app import app
    from api.app_state import state
    from giljo_mcp.auth import AuthManager
    from giljo_mcp.auth.dependencies import get_db_session
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    async def _mock_db_session():
        async with db_manager.get_session_async() as session:
            yield session

    app.dependency_overrides[get_db_session] = _mock_db_session
    state.db_manager = db_manager
    app.state.db_manager = db_manager
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    app.state.tool_accessor = state.tool_accessor

    mock_config = MagicMock()
    mock_config.jwt.secret_key = "test_secret_key"
    mock_config.jwt.algorithm = "HS256"
    mock_config.jwt.expiration_minutes = 30
    mock_config.get = MagicMock(
        side_effect=lambda key, default=None: {
            "security.auth_enabled": True,
            "security.api_keys_required": False,
        }.get(key, default)
    )
    state.config = mock_config
    app.state.config = mock_config
    app.state.auth = AuthManager(mock_config, db=None)
    state.auth = app.state.auth

    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as client:
        yield client

    app.dependency_overrides.clear()
    if hasattr(app.state, "auth"):
        del app.state.auth


def _payload(pids: list[str], extra: dict | None = None) -> dict:
    body = {
        "project_ids": pids,
        "resolved_order": list(pids),
        "execution_mode": _MODE,
        "status": "pending",
        "current_index": 0,
        "project_statuses": dict.fromkeys(pids, "pending"),
    }
    if extra:
        body.update(extra)
    return body


async def _create_run(api_client, headers, pids: list[str], extra: dict | None = None) -> dict:
    resp = await api_client.post("/api/v1/sequence-runs", json=_payload(pids, extra), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()




async def test_patch_locked_stage_then_unstage(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    pids = [str(uuid.uuid4()), str(uuid.uuid4())]
    run = await _create_run(api_client, tenant["headers"], pids)
    assert run["locked"] is False

    staged = await api_client.patch(
        f"/api/v1/sequence-runs/{run['id']}", json={"locked": True}, headers=tenant["headers"]
    )
    assert staged.status_code == 200, staged.text
    assert staged.json()["locked"] is True

    unstaged = await api_client.patch(
        f"/api/v1/sequence-runs/{run['id']}", json={"locked": False}, headers=tenant["headers"]
    )
    assert unstaged.status_code == 200, unstaged.text
    assert unstaged.json()["locked"] is False




async def test_delete_member_removes_one(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    run = await _create_run(api_client, tenant["headers"], [p1, p2, p3])

    resp = await api_client.delete(f"/api/v1/sequence-runs/{run['id']}/members/{p2}", headers=tenant["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project_ids"] == [p1, p3]
    assert body["status"] == "pending"


async def test_delete_member_reduce_to_one_dissolves_no_activate(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    lone = await _seed_project(db_manager, tenant["tenant_key"])
    other = str(uuid.uuid4())
    run = await _create_run(api_client, tenant["headers"], [lone, other])

    resp = await api_client.delete(f"/api/v1/sequence-runs/{run['id']}/members/{other}", headers=tenant["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled", "removal leaving 1 dissolves the run"

    async with db_manager.get_session_async(tenant_key=tenant["tenant_key"]) as session:
        row = await session.execute(
            select(Project).where(Project.id == lone, Project.tenant_key == tenant["tenant_key"])
        )
        project = row.scalar_one()
        assert project.status == ProjectStatus.INACTIVE, "reduce-to-1 must NOT auto-activate the lone project"
        assert project.implementation_launched_at is None


async def test_delete_member_ultralock_running_422(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    run = await _create_run(api_client, tenant["headers"], [p1, p2, p3], extra={"status": "running"})

    resp = await api_client.delete(f"/api/v1/sequence-runs/{run['id']}/members/{p2}", headers=tenant["headers"])
    assert resp.status_code == 422, "member edit must be refused on a running (ultralocked) run"


async def test_patch_unstage_ultralock_running_422(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    pids = [str(uuid.uuid4()), str(uuid.uuid4())]
    run = await _create_run(api_client, tenant["headers"], pids, extra={"status": "running", "locked": True})

    resp = await api_client.patch(
        f"/api/v1/sequence-runs/{run['id']}", json={"locked": False}, headers=tenant["headers"]
    )
    assert resp.status_code == 422, "Unstage must be refused on a running (ultralocked) run"


async def test_delete_member_unknown_run_404(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    resp = await api_client.delete(
        f"/api/v1/sequence-runs/{uuid.uuid4()}/members/{uuid.uuid4()}", headers=tenant["headers"]
    )
    assert resp.status_code == 404, resp.text


async def test_delete_member_tenant_isolation(api_client, db_manager):
    tenant_a = await _seed_user(db_manager)
    tenant_b = await _seed_user(db_manager)
    p1, p2, p3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    run_a = await _create_run(api_client, tenant_a["headers"], [p1, p2, p3])

    resp = await api_client.delete(f"/api/v1/sequence-runs/{run_a['id']}/members/{p2}", headers=tenant_b["headers"])
    assert resp.status_code == 404, "TENANT LEAK: B reached A's run"
