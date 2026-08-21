# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6185 — REST integration tests for the chain_mission edit/lock path.

Proves the FE edit pen can PATCH chain_mission, that an over-cap value returns a
clean 422 (not a DB-constraint 500), and that a write on a running (ultralocked)
run returns 422 (read-only after Implement) — the failing layer here is the PATCH
boundary, so these run through the real ASGI transport.

Parallel-safety rules (per DELIVERY_PIPELINE.md): db_manager-seeded, no
module-level mutable state, each test owns its setup.

Pattern reference: tests/integration/test_be6131a_sequence_run_rest.py.
"""

from __future__ import annotations

import secrets
import uuid

import bcrypt
import pytest
import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.sequence_run_service import MAX_CHAIN_MISSION_CHARS
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)
_EXECUTION_MODE = "claude_code_cli"


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


def _run_payload(status: str = "pending") -> dict:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    return {
        "project_ids": [a, b],
        "resolved_order": [a, b],
        "execution_mode": _EXECUTION_MODE,
        "review_policy": "per_card",
        "status": status,
        "current_index": 0,
        "project_statuses": {a: "pending", b: "pending"},
    }


async def test_patch_chain_mission_round_trips(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    create = await api_client.post("/api/v1/sequence-runs", json=_run_payload(), headers=tenant["headers"])
    assert create.status_code == 201, create.text
    run_id = create.json()["id"]
    assert create.json()["chain_mission"] is None

    patch = await api_client.patch(
        f"/api/v1/sequence-runs/{run_id}",
        json={"chain_mission": "do A then B"},
        headers=tenant["headers"],
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["chain_mission"] == "do A then B"

    get = await api_client.get(f"/api/v1/sequence-runs/{run_id}", headers=tenant["headers"])
    assert get.status_code == 200, get.text
    assert get.json()["chain_mission"] == "do A then B"


async def test_patch_over_cap_chain_mission_returns_422(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    create = await api_client.post("/api/v1/sequence-runs", json=_run_payload(), headers=tenant["headers"])
    assert create.status_code == 201, create.text
    run_id = create.json()["id"]

    resp = await api_client.patch(
        f"/api/v1/sequence-runs/{run_id}",
        json={"chain_mission": "z" * (MAX_CHAIN_MISSION_CHARS + 1)},
        headers=tenant["headers"],
    )
    assert resp.status_code == 422, f"Expected clean 422, got {resp.status_code}: {resp.text}"


async def test_patch_chain_mission_refused_on_running_run(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    create = await api_client.post(
        "/api/v1/sequence-runs", json=_run_payload(status="running"), headers=tenant["headers"]
    )
    assert create.status_code == 201, create.text
    run_id = create.json()["id"]

    resp = await api_client.patch(
        f"/api/v1/sequence-runs/{run_id}",
        json={"chain_mission": "too late, already running"},
        headers=tenant["headers"],
    )
    assert resp.status_code == 422, f"Expected 422 read-only refusal, got {resp.status_code}: {resp.text}"
