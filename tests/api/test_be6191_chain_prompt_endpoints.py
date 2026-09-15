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
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)




async def _seed(db_manager, *, execution_mode: str = "claude_code_cli") -> dict:
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
            execution_mode=execution_mode,
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
            execution_mode=execution_mode,
        )
        session.add_all([p1, p2])
        await session.flush()

        run = await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session).create(
            project_ids=[p1.id, p2.id],
            resolved_order=[p1.id, p2.id],
            execution_mode=execution_mode,
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
            "conductor_agent_id": run["conductor_agent_id"],
        }


async def _projectless_job_id(db_manager, tenant_key: str, conductor_agent_id: str) -> str:
    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = tenant_key
        row = await session.execute(
            select(AgentExecution.job_id).where(
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.agent_id == conductor_agent_id,
            )
        )
        return str(row.scalar_one())




async def test_chain_staging_returns_thin_projectless_prompt(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager)
    projectless_job_id = await _projectless_job_id(db_manager, seed["tenant_key"], seed["conductor_agent_id"])

    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    prompt = body["prompt"]

    assert "get_staging_instructions(" in prompt, "staging bootstrap must call get_staging_instructions"
    assert projectless_job_id in prompt, "the project-less conductor job_id must appear in the prompt"

    assert "AGENT TEMPLATES" not in prompt, "the agent_templates appendix must NOT be inlined"
    assert "ORDER OF OPERATIONS" not in prompt, "the chapter body must NOT be inlined"
    assert "STAND UP THE HUB THREAD" not in prompt, "the staging chapter body must NOT be inlined"

    assert body["orchestrator_job_id"] == projectless_job_id




async def test_resolved_job_is_projectless(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager)
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200
    job_id = resp.json()["orchestrator_job_id"]

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = seed["tenant_key"]
        row = await session.execute(
            select(AgentJob.project_id).where(
                AgentJob.job_id == job_id,
                AgentJob.tenant_key == seed["tenant_key"],
            )
        )
        project_id = row.scalar_one()
    assert project_id is None, "resolved job must be the project-less chain orchestrator (project_id IS NULL)"




async def test_staging_toolsearch_bootstrap_for_claude(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager, execution_mode="claude_code_cli")
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "TOOLSEARCH BOOTSTRAP" in prompt, "claude harness must carry the ToolSearch STEP 0 bootstrap"
    assert "ToolSearch(query=" in prompt, "the one-line ToolSearch call must be rendered"




async def test_staging_no_toolsearch_for_codex(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager, execution_mode="codex_cli")
    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "TOOLSEARCH BOOTSTRAP" not in prompt, "codex harness must NOT carry the ToolSearch bootstrap"




async def test_mode_correct_protocol_multi_terminal(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager, execution_mode="multi_terminal")
    projectless_job_id = await _projectless_job_id(db_manager, seed["tenant_key"], seed["conductor_agent_id"])

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = seed["tenant_key"]
        resp = await MissionService(
            db_manager=None, tenant_manager=TenantManager(), test_session=session
        ).get_staging_instructions(projectless_job_id, seed["tenant_key"])

    capability = resp["orchestrator_protocol"]["ch_capability"]
    assert "FRESH OS TERMINAL" in capability, "CH_CAPABILITY must name the fresh OS terminal sub-orch spawn"
    assert "EXECUTION MODE = multi_terminal" in capability




async def test_mode_correct_protocol_subagent(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager, execution_mode="claude_code_cli")
    projectless_job_id = await _projectless_job_id(db_manager, seed["tenant_key"], seed["conductor_agent_id"])

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = seed["tenant_key"]
        resp = await MissionService(
            db_manager=None, tenant_manager=TenantManager(), test_session=session
        ).get_staging_instructions(projectless_job_id, seed["tenant_key"])

    capability = resp["orchestrator_protocol"]["ch_capability"]
    assert "Task()/subagent" in capability, "subagent CH_CAPABILITY must name the Task()/subagent path"
    assert "EXECUTION MODE = claude_code_cli" in capability




async def test_chain_implementation_returns_projectless_drive_bootstrap(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager, execution_mode="claude_code_cli")
    projectless_job_id = await _projectless_job_id(db_manager, seed["tenant_key"], seed["conductor_agent_id"])

    resp = await api_client.get(
        f"/api/v1/prompts/chain-implementation/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    prompt = body["prompt"]

    assert "get_job_mission(" in prompt, "implementation bootstrap must call get_job_mission"
    assert projectless_job_id in prompt, "the project-less conductor job_id must appear"
    assert body["orchestrator_job_id"] == projectless_job_id
    assert "TOOLSEARCH BOOTSTRAP" in prompt
    assert "AUTO-CONTINUE LOOP" not in prompt, "the drive chapter body must NOT be inlined"
    assert "CRASH-RESUME" not in prompt, "the drive chapter body must NOT be inlined"




async def test_legacy_run_without_conductor_409(api_client: AsyncClient, db_manager):
    seed = await _seed(db_manager)
    from giljo_mcp.models.sequence_runs import SequenceRun

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = seed["tenant_key"]
        row = await session.execute(
            select(SequenceRun).where(
                SequenceRun.id == seed["run_id"],
                SequenceRun.tenant_key == seed["tenant_key"],
            )
        )
        run = row.scalar_one()
        run.conductor_agent_id = None
        await session.commit()

    resp = await api_client.get(
        f"/api/v1/prompts/chain-staging/{seed['run_id']}",
        headers=seed["headers"],
    )
    assert resp.status_code == 409, f"Expected 409 for legacy run, got {resp.status_code}: {resp.text}"
    assert "recreate the chain" in resp.json()["message"].lower()
