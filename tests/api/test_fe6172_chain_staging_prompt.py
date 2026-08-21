# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-6172 Part A regression — GET /api/v1/prompts/chain-staging/{run_id}.

Before FE-6172, this endpoint returned 404 for a freshly-elected chain that had
never been staged. After the fix, the endpoint returns 200 with a non-empty prompt.

BE-6191 repointed the endpoint at the run's DEDICATED, project-less chain
orchestrator (run.conductor_agent_id) and made the prompt a THIN bootstrap. The
seed now mints a conductor (via SequenceRunService.create) and the behavioral
assertions track the thin contract (the fat-paste / agent_templates appendix is
gone). The fresh-run-returns-200 and tenant-isolation regressions remain.

Edition scope: CE.
"""

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


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------


async def _seed(db_manager) -> dict:
    """Create tenant + user + product + two projects + a freshly-elected SequenceRun.

    The run is created via SequenceRunService.create so its DEDICATED, project-less
    chain orchestrator is minted (run.conductor_agent_id populated): the state
    immediately after chain election. The endpoint resolves that orchestrator and
    returns 200 with a thin bootstrap (BE-6191).
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
            series_number=uuid.uuid4().int % 9000 + 1,
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
            series_number=uuid.uuid4().int % 9000 + 1,
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_chain_staging_prompt_fresh_run_returns_200(api_client: AsyncClient, db_manager):
    """FE-6172 PART A regression: endpoint returns 200 for a never-staged chain.

    Before the fix, the endpoint returned 404 with:
      'No orchestrator job found for the head project … Stage the chain first.'
    After the fix, it creates the orchestrator job on the fly and returns a
    non-empty prompt.
    """
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
    """FE-6176c regression: the chain staging prompt is a FLAT, readable prompt —
    NOT a json.dumps blob with ensure_ascii-escaped box-drawing chars.

    BE-6191: the prompt is now a thin bootstrap (no inlined chapters), so the flat-text
    guard is asserted via the bootstrap shape rather than chapter content.
    """
    seed = await _seed(db_manager)
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]

    # The decoded prompt must NOT carry the literal escape sequence the bug produced.
    assert "\\u2550" not in prompt, "box-drawing chars must not be \\uXXXX-escaped"
    # It must be a flat prompt, not a JSON object of chapters.
    assert not prompt.lstrip().startswith("{"), "prompt must be flat text, not a JSON object"
    # It must identify the project-less chain orchestrator (the thin bootstrap role line).
    assert "CHAIN ORCHESTRATOR" in prompt.upper(), "chain staging prompt must name the chain orchestrator role"


async def test_chain_staging_prompt_is_thin_bootstrap_with_identity(api_client: AsyncClient, db_manager):
    """BE-6191: the chain staging prompt is a THIN bootstrap that surfaces the
    orchestrator identity ids and a get_staging_instructions step, and does NOT inline
    the fat chapter bodies or the dropped agent_templates appendix.
    """
    seed = await _seed(db_manager)
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    prompt = body["prompt"]

    # Identity surfaced with the conductor's own job_id (returned in the body).
    assert "YOUR IDENTITY" in prompt, "the identity block must be present"
    assert body["orchestrator_job_id"] in prompt, "the conductor's job_id must appear in the identity block"
    # Step 2 fetches the full protocol itself.
    assert "get_staging_instructions(" in prompt, "the bootstrap must call get_staging_instructions"
    # The fat-paste / appendix are gone (no chapter BODY inlined).
    assert "AGENT TEMPLATES" not in prompt, "the agent_templates appendix must NOT be inlined"
    assert "ORDER OF OPERATIONS" not in prompt, "the fat chapter body must NOT be inlined"


async def test_chain_staging_prompt_nonexistent_run_returns_404(api_client: AsyncClient, db_manager):
    """Missing run returns 404 — unchanged behaviour."""
    seed = await _seed(db_manager)
    fake_run_id = str(uuid.uuid4())
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{fake_run_id}",
        headers=seed["headers"],
    )
    assert resp.status_code == 404, f"Expected 404 for unknown run, got {resp.status_code}"


async def test_chain_staging_prompt_other_tenant_returns_404(api_client: AsyncClient, db_manager):
    """A run belonging to another tenant is invisible — returns 404."""
    seed_a = await _seed(db_manager)
    seed_b = await _seed(db_manager)
    # seed_b's headers, asking for seed_a's run
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed_a['run_id']}",
        headers=seed_b["headers"],
    )
    assert resp.status_code == 404, f"Cross-tenant leak: got {resp.status_code}"


async def test_chain_staging_prompt_idempotent_second_call(api_client: AsyncClient, db_manager):
    """Calling the endpoint twice is safe: the second call reuses the existing orchestrator job."""
    seed = await _seed(db_manager)
    url = f"/api/v1/prompts/chain-staging/{seed['run_id']}"
    r1 = await api_client.get(url, headers=seed["headers"])
    r2 = await api_client.get(url, headers=seed["headers"])
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Both must return the same orchestrator_job_id (reuse path, not double-create).
    assert r1.json().get("orchestrator_job_id") == r2.json().get("orchestrator_job_id")
