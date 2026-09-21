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

from api.endpoints.prompts import _build_conductor_bootstrap, _conductor_mcp_url
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.conductor_job_minter import mint_conductor_job
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)
_CHAIN_MODE = "claude_code_cli"


async def _seed_chain(
    db_manager,
    *,
    member_staging_status: str = "staged",
    head_launched: bool = False,
    head_closed_out: bool = False,
    current_index: int = 0,
) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        session.info["tenant_key"] = tenant_key

        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()

        user = User(
            username=f"u_{suffix}",
            email=f"u_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
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

        members = []
        for index, label in enumerate(("Alpha", "Beta")):
            launched = head_launched and index == 0
            project = Project(
                id=str(uuid.uuid4()),
                name=f"{label} {suffix}",
                description=f"{label} project",
                mission=f"Build the {label.lower()} component.",
                tenant_key=tenant_key,
                product_id=product.id,
                status="inactive",
                series_number=next_series_number(),
                execution_mode=_CHAIN_MODE,
                staging_status=member_staging_status,
                implementation_launched_at=(datetime.now(UTC) if launched else None),
                closeout_executed_at=(datetime.now(UTC) if (head_closed_out and index == 0) else None),
            )
            session.add(project)
            members.append(project)

        solo = Project(
            id=str(uuid.uuid4()),
            name=f"Solo {suffix}",
            description="Not a chain member",
            mission="Stand alone.",
            tenant_key=tenant_key,
            product_id=product.id,
            status="inactive",
            series_number=next_series_number(),
            execution_mode=_CHAIN_MODE,
            staging_status="staged",
        )
        session.add(solo)
        await session.flush()

        run = SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_ids=[m.id for m in members],
            resolved_order=[m.id for m in members],
            current_index=current_index,
            execution_mode=_CHAIN_MODE,
            status="running",
            locked=True,
            chain_mission="Deliver both components in order.",
            project_statuses={m.id: "pending" for m in members},
        )
        session.add(run)
        await session.flush()

        conductor_identity = await mint_conductor_job(session, tenant_key=tenant_key, run_id=run.id)
        run.conductor_agent_id = conductor_identity["agent_id"]

        member_identities = []
        for member in members:
            job_id = generate_uuid()
            agent_id = generate_uuid()
            session.add(
                AgentJob(
                    job_id=job_id,
                    tenant_key=tenant_key,
                    project_id=member.id,
                    mission=member.mission,
                    job_type="orchestrator",
                    status="active",
                )
            )
            session.add(
                AgentExecution(
                    agent_id=agent_id,
                    job_id=job_id,
                    tenant_key=tenant_key,
                    agent_display_name="orchestrator",
                    agent_name="orchestrator",
                    status="waiting",
                    health_status="unknown",
                    project_phase="staging",
                )
            )
            member_identities.append({"job_id": job_id, "agent_id": agent_id})

        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        return {
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
            "tenant_key": tenant_key,
            "run_id": run.id,
            "head_pid": members[0].id,
            "head_alias": members[0].alias,
            "tail_pid": members[1].id,
            "solo_pid": solo.id,
            "conductor_agent_id": conductor_identity["agent_id"],
            "conductor_job_id": conductor_identity["job_id"],
            "members": member_identities,
        }




async def test_member_prompt_addresses_its_own_orchestrator(api_client: AsyncClient, db_manager):
    seed = await _seed_chain(db_manager)
    head = seed["members"][0]

    resp = await api_client.get(f"/api/v1/prompts/chain-member/{seed['head_pid']}", headers=seed["headers"])

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["orchestrator_job_id"] == head["job_id"]
    assert body["project_id"] == seed["head_pid"]
    assert body["run_id"] == seed["run_id"]

    prompt = body["prompt"]
    assert head["job_id"] in prompt and head["agent_id"] in prompt
    assert seed["conductor_job_id"] not in prompt, "a member must never be handed the conductor's identity"
    assert seed["head_pid"] in prompt, "the member's bootstrap must name the project it owns"
    assert "get_staging_instructions(" in prompt




async def test_member_prompt_comes_from_the_shared_builder(api_client: AsyncClient, db_manager):
    seed = await _seed_chain(db_manager)
    head = seed["members"][0]

    resp = await api_client.get(f"/api/v1/prompts/chain-member/{seed['head_pid']}", headers=seed["headers"])
    assert resp.status_code == 200

    expected = _build_conductor_bootstrap(
        identity={
            "agent_id": head["agent_id"],
            "job_id": head["job_id"],
            "run_id": seed["run_id"],
            "project_id": seed["head_pid"],
        },
        mcp_url=_conductor_mcp_url(),
        phase="staging",
        harness_is_claude=True,
    )
    assert resp.json()["prompt"] == expected, (
        "the member prompt must be the shared builder's output verbatim — a second prompt "
        "engine for the headless/member door is forbidden (ruling 19)"
    )




async def test_staged_out_member_switches_to_the_implementation_fetch(api_client: AsyncClient, db_manager):
    seed = await _seed_chain(db_manager, member_staging_status="staging_complete", head_launched=True)

    resp = await api_client.get(f"/api/v1/prompts/chain-member/{seed['head_pid']}", headers=seed["headers"])
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert "get_job_mission(" in prompt
    assert "get_staging_instructions(" not in prompt




async def test_non_member_project_returns_404(api_client: AsyncClient, db_manager):
    seed = await _seed_chain(db_manager)

    resp = await api_client.get(f"/api/v1/prompts/chain-member/{seed['solo_pid']}", headers=seed["headers"])
    assert resp.status_code == 404, f"Expected 404 for a non-member, got {resp.status_code}: {resp.text}"

    missing = await api_client.get(f"/api/v1/prompts/chain-member/{uuid.uuid4()}", headers=seed["headers"])
    assert missing.status_code == 404




async def test_launch_refuses_member_whose_predecessor_has_not_closed_out(api_client: AsyncClient, db_manager):
    seed = await _seed_chain(db_manager)

    resp = await api_client.patch(
        f"/api/agent-jobs/projects/{seed['tail_pid']}/launch-implementation",
        headers=seed["headers"],
    )

    assert resp.status_code == 404, f"Expected a refusal, got {resp.status_code}: {resp.text}"
    body = resp.json()
    rendered = f"{body.get('message', '')} {body.get('context', {})}"
    assert seed["head_alias"] in rendered, f"the refusal must name the project the user is waiting on; got {body!r}"




async def test_launch_succeeds_for_the_member_at_the_current_index(api_client: AsyncClient, db_manager):
    seed = await _seed_chain(db_manager)

    resp = await api_client.patch(
        f"/api/agent-jobs/projects/{seed['head_pid']}/launch-implementation",
        headers=seed["headers"],
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["implementation_launched_at"]
