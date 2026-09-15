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
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.conductor_job_minter import mint_conductor_job
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed(db_manager, *, run_mode: str = "claude_code_cli") -> dict:
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

        pw_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode()
        user = User(
            username=f"u_{suffix}",
            email=f"u_{suffix}@example.com",
            password_hash=pw_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        product = Product(
            id=str(uuid.uuid4()),
            name=f"Product {suffix}",
            description="Test product",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(product)
        await session.flush()

        p1 = Project(
            id=str(uuid.uuid4()),
            name=f"Alpha {suffix}",
            description="Head project",
            mission="Build the alpha component.",
            tenant_key=tenant_key,
            product_id=product.id,
            status="inactive",
            series_number=next_series_number(),
            execution_mode=None,
        )
        p2 = Project(
            id=str(uuid.uuid4()),
            name=f"Beta {suffix}",
            description="Second project",
            mission="Build the beta component.",
            tenant_key=tenant_key,
            product_id=product.id,
            status="inactive",
            series_number=next_series_number(),
            execution_mode=None,
        )
        session.add_all([p1, p2])
        await session.flush()

        run = SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_ids=[p1.id, p2.id],
            resolved_order=[p1.id, p2.id],
            current_index=0,
            execution_mode=run_mode,
            status="pending",
            locked=False,
            project_statuses={p1.id: "pending", p2.id: "pending"},
        )
        session.add(run)
        await session.flush()

        conductor_identity = await mint_conductor_job(session, tenant_key=tenant_key, run_id=run.id)
        run.conductor_agent_id = conductor_identity["agent_id"]
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        headers = {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
        return {
            "headers": headers,
            "run_id": run.id,
            "head_pid": p1.id,
            "tail_pid": p2.id,
            "tenant_key": tenant_key,
        }


async def _get_project(db_manager, pid: str, tenant_key: str) -> Project:
    token = TenantManager.set_current_tenant(tenant_key)
    try:
        async with db_manager.get_session_async() as session:
            result = await session.execute(select(Project).where(Project.id == pid, Project.tenant_key == tenant_key))
            return result.scalar_one()
    finally:
        from giljo_mcp.tenant import current_tenant

        current_tenant.reset(token)


async def test_chain_staging_propagates_run_mode_to_all_members(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager, run_mode="claude_code_cli")

    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    head = await _get_project(db_manager, seed["head_pid"], seed["tenant_key"])
    tail = await _get_project(db_manager, seed["tail_pid"], seed["tenant_key"])
    assert head.execution_mode == "claude_code_cli", "head project mode not propagated"
    assert tail.execution_mode == "claude_code_cli", "tail project mode not propagated"


async def test_chain_staging_does_not_force_staged_on_downstream_member(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager, run_mode="claude_code_cli")

    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200

    tail = await _get_project(db_manager, seed["tail_pid"], seed["tenant_key"])
    assert tail.staging_status != "staged", "downstream member must not be pre-staged"


async def test_chain_staging_noop_when_run_has_no_mode(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager, run_mode="")

    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200

    head = await _get_project(db_manager, seed["head_pid"], seed["tenant_key"])
    tail = await _get_project(db_manager, seed["tail_pid"], seed["tenant_key"])
    assert not (head.execution_mode or "").strip(), "must not coerce a mode onto head"
    assert not (tail.execution_mode or "").strip(), "must not coerce a mode onto tail"
