# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6131a — REST integration tests for the sequence run record.

Two mandatory regression tests (spec DoD):
  a. Tenant isolation: a run created under tenant A is invisible to tenant B.
  b. Resume-from-index: persist current_index, re-fetch, assert it round-trips.

Parallel-safety rules (per DELIVERY_PIPELINE.md):
  - DB-touching: uses TransactionalTestContext (rollback at teardown) — each test
    gets its own session and its own rolled-back transaction.
  - No module-level mutable state.
  - Each test owns its setup (no ordering dependencies).

Pattern reference: tests/api/test_roadmap_endpoints.py (api_client fixture +
direct DB seeding via db_manager, auth via JWTManager + cookie header).
"""

from __future__ import annotations

import os
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
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)

# A valid execution_mode value (matches _STAGE_MODE_MAP output).
_EXECUTION_MODE = "claude_code_cli"
# Two fake project ids used across tests.
_PROJ_A = str(uuid.uuid4())
_PROJ_B = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_agent_coordination():
    """No-op override: API tests don't use agent_coordination."""
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_context_module():
    """No-op override: API tests manage db injection directly."""
    yield


async def _seed_user(db_manager) -> dict:
    """Create org + user for a fresh tenant; return token + tenant_key."""
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

        os.environ.setdefault("JWT_SECRET", "test_secret_key")
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
async def seed_user(db_manager):
    """Factory: mint a fresh tenant (org + user), purged at teardown.

    ``_seed_user`` COMMITS through a real ``db_manager`` session, so the
    ``TransactionalTestContext`` this suite otherwise relies on cannot roll
    those rows back — without an explicit purge the tenant's org+user rows
    persist in the per-worker test DB across runs (TSK-9199; same leak class
    as INF-9189, different tables). A test may mint several tenants, so the
    factory records every key it mints and purges them all.

    The minted-key list lives in the fixture (not at module scope), so the
    suite stays parallel-safe under xdist.
    """
    minted: list[str] = []

    async def _factory() -> dict:
        seeded = await _seed_user(db_manager)
        minted.append(seeded["tenant_key"])
        return seeded

    yield _factory

    for tenant_key in minted:
        await purge_tenant_rows(db_manager, tenant_key)


@pytest_asyncio.fixture(scope="function")
async def api_client(db_manager):
    """AsyncClient wired to the FastAPI app with db_manager injected into state."""
    from unittest.mock import MagicMock

    from api.app import app
    from api.app_state import state
    from giljo_mcp.auth import AuthManager
    from giljo_mcp.auth.dependencies import get_db_session
    from giljo_mcp.tenant import TenantManager
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_payload(project_ids=None, resolved_order=None, extra: dict | None = None) -> dict:
    pids = project_ids or [_PROJ_A, _PROJ_B]
    ro = resolved_order or [_PROJ_A, _PROJ_B]
    body = {
        "project_ids": pids,
        "resolved_order": ro,
        "execution_mode": _EXECUTION_MODE,
        "review_policy": "per_card",
        "status": "pending",
        "current_index": 0,
        "project_statuses": {pids[0]: "pending", pids[1]: "pending"},
    }
    if extra:
        body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Test (a): tenant isolation
# ---------------------------------------------------------------------------


async def test_tenant_a_run_invisible_to_tenant_b(api_client, seed_user):
    """A run created under tenant A must not be readable by tenant B.

    Regression for the hard requirement: every DB query filters by tenant_key.
    """
    tenant_a = await seed_user()
    tenant_b = await seed_user()

    # Tenant A creates a run.
    create_resp = await api_client.post(
        "/api/v1/sequence-runs",
        json=_run_payload(),
        headers=tenant_a["headers"],
    )
    assert create_resp.status_code == 201, create_resp.text
    run_id = create_resp.json()["id"]

    # Tenant A can read their own run.
    read_a = await api_client.get(f"/api/v1/sequence-runs/{run_id}", headers=tenant_a["headers"])
    assert read_a.status_code == 200, read_a.text
    assert read_a.json()["id"] == run_id

    # Tenant B must NOT be able to read tenant A's run (404, not a leak).
    read_b = await api_client.get(f"/api/v1/sequence-runs/{run_id}", headers=tenant_b["headers"])
    assert read_b.status_code == 404, (
        f"TENANT LEAK: tenant B read tenant A's sequence run. Status was {read_b.status_code}, body: {read_b.text}"
    )


# ---------------------------------------------------------------------------
# Test (b): resume-from-index round-trip
# ---------------------------------------------------------------------------


async def test_current_index_persists_and_resumes(api_client, seed_user):
    """current_index round-trips through create -> update -> GET.

    This proves the A-crash-resume invariant: after a crash the main orchestrator
    reads the persisted current_index and resumes from that project, not from 0.
    """
    tenant = await seed_user()

    # Create with initial index=0.
    create_resp = await api_client.post(
        "/api/v1/sequence-runs",
        json=_run_payload(extra={"current_index": 0, "status": "running"}),
        headers=tenant["headers"],
    )
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    run_id = body["id"]
    assert body["current_index"] == 0

    # Advance to index 1 (simulates orchestrator A finishing project 0).
    patch_resp = await api_client.patch(
        f"/api/v1/sequence-runs/{run_id}",
        json={"current_index": 1, "status": "running"},
        headers=tenant["headers"],
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["current_index"] == 1

    # GET must return index=1 (the crash-resume read).
    get_resp = await api_client.get(f"/api/v1/sequence-runs/{run_id}", headers=tenant["headers"])
    assert get_resp.status_code == 200, get_resp.text
    data = get_resp.json()
    assert data["current_index"] == 1, f"Resume invariant broken: expected current_index=1, got {data['current_index']}"
    assert data["status"] == "running"


# ---------------------------------------------------------------------------
# Bonus: validate 422 on bad enum values (service-layer input validation gate)
# ---------------------------------------------------------------------------


async def test_create_rejects_invalid_execution_mode(api_client, seed_user):
    """Invalid execution_mode must produce 422, not a DB-constraint 500."""
    tenant = await seed_user()
    bad_payload = _run_payload(extra={"execution_mode": "not_a_real_mode"})
    resp = await api_client.post("/api/v1/sequence-runs", json=bad_payload, headers=tenant["headers"])
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"


async def test_create_rejects_too_many_projects(api_client, seed_user):
    """More than 5 project_ids must produce 422 (cap enforcement)."""
    tenant = await seed_user()
    too_many = [str(uuid.uuid4()) for _ in range(6)]
    resp = await api_client.post(
        "/api/v1/sequence-runs",
        json={
            "project_ids": too_many,
            "resolved_order": too_many,
            "execution_mode": _EXECUTION_MODE,
        },
        headers=tenant["headers"],
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
