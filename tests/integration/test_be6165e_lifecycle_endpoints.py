# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6165e — REST integration tests for the chain lifecycle endpoints.

Covers the two new routes end-to-end (auth + tenant scope + service):
  GET  /api/v1/sequence-runs?status=...        — durable-election read-back
  POST /api/v1/sequence-runs/{run_id}/release  — graceful | cancel

Fixture pattern mirrors tests/integration/test_be6131a_sequence_run_rest.py
(api_client + JWT cookie auth + db_manager seeding). Parallel-safe:
TransactionalTestContext is not used here (the API commits); each test seeds its
own tenants with unique keys, so per-worker DBs never collide.
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
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio

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

    # Save process-global state so this fixture leaves no leak. Overwriting
    # state.config with a MagicMock and not restoring it poisons a later
    # create_app() build: its SPA static mount probes
    # state.config.get_nested("paths.static"), which on a mock resolves to a
    # nonexistent path, silently dropping the ("", frozenset()) route and
    # flaking tests/unit/test_be6042b_app_surface.py.
    _saved_state = {
        "db_manager": state.db_manager,
        "tenant_manager": state.tenant_manager,
        "tool_accessor": state.tool_accessor,
        "config": state.config,
        "auth": state.auth,
    }

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
    # Restore process-global state so a later create_app()/global-app test sees
    # the real config (and the SPA static mount) instead of this fixture's mock.
    state.db_manager = _saved_state["db_manager"]
    state.tenant_manager = _saved_state["tenant_manager"]
    state.tool_accessor = _saved_state["tool_accessor"]
    state.config = _saved_state["config"]
    state.auth = _saved_state["auth"]


def _payload(extra: dict | None = None) -> dict:
    pa, pb = str(uuid.uuid4()), str(uuid.uuid4())
    body = {
        "project_ids": [pa, pb],
        "resolved_order": [pa, pb],
        "execution_mode": _MODE,
        "status": "running",
        "current_index": 0,
        "project_statuses": {pa: "implementing", pb: "pending"},
    }
    if extra:
        body.update(extra)
    return body


async def _seed_live_members(db_manager, tenant_key: str, run: dict) -> None:
    """Insert live (non-terminal) project rows for the run's members so the
    BE-6200 live-member filter in list_active keeps the run. A real chain always
    has real member projects; default INACTIVE status is non-terminal -> 'live'."""
    member_ids = list(dict.fromkeys((run.get("resolved_order") or []) + (run.get("project_ids") or [])))
    async with db_manager.get_session_async() as session:
        for pid in member_ids:
            # BE-9437: product_id is NOT NULL. One product per member -- these are
            # INACTIVE so idx_project_single_active_per_product does not bite, but
            # a product each keeps the members independent.
            product_id = str(uuid.uuid4())
            session.add(
                Product(
                    id=product_id,
                    tenant_key=tenant_key,
                    name=f"chain-member-product-{pid[:8]}",
                    description="owning product for a chain member",
                    is_active=False,
                )
            )
            session.add(
                Project(
                    id=pid,
                    product_id=product_id,
                    tenant_key=tenant_key,
                    name=f"chain-member-{pid[:8]}",
                    description="live chain member",
                    mission="member mission",
                    # BE-9429: uq_project_taxonomy_active is NULLS NOT DISTINCT,
                    # so these all-NULL taxonomy rows collide without a serial.
                    series_number=next_series_number(),
                )
            )
        await session.commit()


async def _create_run(api_client, tenant: dict, extra: dict | None = None, *, db_manager=None) -> dict:
    resp = await api_client.post("/api/v1/sequence-runs", json=_payload(extra), headers=tenant["headers"])
    assert resp.status_code == 201, resp.text
    run = resp.json()
    if db_manager is not None:
        await _seed_live_members(db_manager, tenant["tenant_key"], run)
    return run


# ---------------------------------------------------------------------------
# GET list — durable-election read-back
# ---------------------------------------------------------------------------


async def test_list_active_tenant_isolation(api_client, db_manager):
    tenant_a = await _seed_user(db_manager)
    tenant_b = await _seed_user(db_manager)

    run_a = await _create_run(api_client, tenant_a, db_manager=db_manager)
    await _create_run(api_client, tenant_b, db_manager=db_manager)

    resp = await api_client.get("/api/v1/sequence-runs", headers=tenant_a["headers"])
    assert resp.status_code == 200, resp.text
    ids = {r["id"] for r in resp.json()}
    assert run_a["id"] in ids
    assert all(r["tenant_key"] == tenant_a["tenant_key"] for r in resp.json()), "TENANT LEAK in list"


async def test_list_status_filter_excludes_completed(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    run = await _create_run(api_client, tenant, db_manager=db_manager)
    await api_client.patch(
        f"/api/v1/sequence-runs/{run['id']}", json={"status": "completed"}, headers=tenant["headers"]
    )

    default = await api_client.get("/api/v1/sequence-runs", headers=tenant["headers"])
    assert run["id"] not in {r["id"] for r in default.json()}, "completed run leaked into the active default"

    only_completed = await api_client.get(
        "/api/v1/sequence-runs", params={"status": "completed"}, headers=tenant["headers"]
    )
    assert {r["id"] for r in only_completed.json()} == {run["id"]}


async def test_list_rejects_invalid_status(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    resp = await api_client.get("/api/v1/sequence-runs", params={"status": "bogus"}, headers=tenant["headers"])
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# POST release — cancel (forced) + graceful (terminated, with precondition)
# ---------------------------------------------------------------------------


async def test_release_cancel_ends_run_no_project_mutation(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    run = await _create_run(api_client, tenant, db_manager=db_manager)
    before_statuses = run["project_statuses"]

    resp = await api_client.post(
        f"/api/v1/sequence-runs/{run['id']}/release", params={"mode": "cancel"}, headers=tenant["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled"
    # No ProjectStatus mutation: project_statuses map unchanged.
    assert body["project_statuses"] == before_statuses

    # Freed membership: the run drops out of the active list.
    active = await api_client.get("/api/v1/sequence-runs", headers=tenant["headers"])
    assert run["id"] not in {r["id"] for r in active.json()}


async def test_release_graceful_requires_inflight_closed(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    # in-flight project (index 0) is "implementing" — not closed out.
    run = await _create_run(api_client, tenant)

    rejected = await api_client.post(
        f"/api/v1/sequence-runs/{run['id']}/release", params={"mode": "graceful"}, headers=tenant["headers"]
    )
    assert rejected.status_code == 422, "graceful must reject while the in-flight project is still running"

    # Close out the in-flight project, then graceful succeeds -> terminated.
    head_pid = run["resolved_order"][0]
    await api_client.patch(
        f"/api/v1/sequence-runs/{run['id']}",
        json={"project_statuses": {head_pid: "completed"}},
        headers=tenant["headers"],
    )
    ok = await api_client.post(
        f"/api/v1/sequence-runs/{run['id']}/release", params={"mode": "graceful"}, headers=tenant["headers"]
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "terminated"


async def test_release_rejects_bad_mode(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    run = await _create_run(api_client, tenant)
    resp = await api_client.post(
        f"/api/v1/sequence-runs/{run['id']}/release", params={"mode": "nuke"}, headers=tenant["headers"]
    )
    assert resp.status_code == 422, resp.text


async def test_release_unknown_run_404(api_client, db_manager):
    tenant = await _seed_user(db_manager)
    resp = await api_client.post(
        f"/api/v1/sequence-runs/{uuid.uuid4()}/release", params={"mode": "cancel"}, headers=tenant["headers"]
    )
    assert resp.status_code == 404, resp.text
