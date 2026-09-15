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
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)




async def _seed(db_manager) -> dict:
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
            execution_mode="multi_terminal",
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
            execution_mode="multi_terminal",
        )
        session.add_all([p1, p2])
        await session.flush()

        run = await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session).create(
            project_ids=[p1.id, p2.id],
            resolved_order=[p1.id, p2.id],
            execution_mode="multi_terminal",
            tenant_key=tenant_key,
        )
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
            "run_id": run["id"],
            "head_pid": p1.id,
            "tenant_key": tenant_key,
        }




async def test_chain_staging_prompt_fresh_run_returns_200(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager)
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("prompt"), "chain-staging prompt must not be empty"
    assert body.get("orchestrator_job_id"), "orchestrator_job_id must be present"
    assert body.get("head_project_id") == seed["head_pid"]
    assert body.get("run_id") == seed["run_id"]


async def test_chain_staging_prompt_is_flat_text_not_json_blob(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager)
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]

    assert "\\u2550" not in prompt, "box-drawing chars must not be \\uXXXX-escaped"
    assert not prompt.lstrip().startswith("{"), "prompt must be flat text, not a JSON object"
    assert "CHAIN ORCHESTRATOR" in prompt.upper(), "chain staging prompt must name the chain orchestrator role"


async def test_chain_staging_prompt_is_thin_bootstrap_with_identity(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager)
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    prompt = body["prompt"]

    assert "YOUR IDENTITY" in prompt, "the identity block must be present"
    assert body["orchestrator_job_id"] in prompt, "the conductor's job_id must appear in the identity block"
    assert "get_staging_instructions(" in prompt, "the bootstrap must call get_staging_instructions"
    assert "AGENT TEMPLATES" not in prompt, "the agent_templates appendix must NOT be inlined"
    assert "ORDER OF OPERATIONS" not in prompt, "the fat chapter body must NOT be inlined"


async def test_chain_staging_prompt_nonexistent_run_returns_404(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager)
    fake_run_id = str(uuid.uuid4())
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{fake_run_id}",
        headers=seed["headers"],
    )
    assert resp.status_code == 404, f"Expected 404 for unknown run, got {resp.status_code}"


async def test_chain_staging_prompt_other_tenant_returns_404(api_client: AsyncClient, db_manager):
    seed_a = await _seed(db_manager)
    seed_b = await _seed(db_manager)
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed_a['run_id']}",
        headers=seed_b["headers"],
    )
    assert resp.status_code == 404, f"Cross-tenant leak: got {resp.status_code}"


async def test_chain_staging_prompt_idempotent_second_call(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager)
    url = f"/api/v1/prompts/chain-staging/{seed['run_id']}"
    r1 = await api_client.get(url, headers=seed["headers"])
    r2 = await api_client.get(url, headers=seed["headers"])
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json().get("orchestrator_job_id") == r2.json().get("orchestrator_job_id")
