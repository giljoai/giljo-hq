# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.conductor_staging_builder import build_conductor_staging_response
from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging
from giljo_mcp.services.sequence_chain_context import ChainContext
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


async def _seed_project(session: AsyncSession, tenant_key: str, product_id: str | None = None) -> str:
    if product_id is None:
        product = Product(
            id=str(uuid.uuid4()),
            name=f"BE-9462 Product {uuid.uuid4().hex[:6]}",
            description="Chain product.",
            tenant_key=tenant_key,
            is_active=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(product)
        await session.flush()
        product_id = product.id
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9462 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=product_id,
        series_number=1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def test_conductor_staging_response_folds_creator_id_into_create_thread() -> None:
    chain_ctx = ChainContext(
        run_id="run-be9462",
        role="conductor",
        current_index=0,
        resolved_order=["p1", "p2"],
        is_staging=True,
        conductor_agent_id="cond-be9462",
        execution_mode="claude_code_cli",
    )
    resp = build_conductor_staging_response(
        chain_ctx=chain_ctx, job_id="job-be9462", agent_id="cond-be9462", tenant_key="tk_be9462"
    )
    chapter = resp["orchestrator_protocol"]["ch_chain_staging"]

    assert 'creator_id="cond-be9462"' in chapter, (
        "the conductor's own agent_id must be threaded into the rendered create_thread call"
    )
    assert "join_thread" not in chapter, (
        "the join_thread line is now redundant (create_thread's creator_id already enrols) and must be gone"
    )
    assert "sequence_run_id" in chapter
    assert "hub_thread_id" in chapter


@pytest.mark.asyncio
async def test_one_call_create_thread_enrols_conductor_by_name(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    p1 = await _seed_project(db_session, tenant)

    run = await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session).create(
        project_ids=[p1],
        resolved_order=[p1],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    conductor_agent_id = run["conductor_agent_id"]
    run_id = run["id"]

    chapter = _build_ch_chain_staging(
        run_id=run_id,
        resolved_order=[p1],
        execution_mode="claude_code_cli",
        job_id="job-be9462",
        agent_id=conductor_agent_id,
    )
    assert f'creator_id="{conductor_agent_id}"' in chapter
    assert "join_thread" not in chapter

    comm = CommThreadService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    thread = await comm.create_thread(
        subject="Chain: repro", sequence_run_id=run_id, creator_id=conductor_agent_id, tenant_key=tenant
    )
    thread_id = thread["thread_id"]
    assert thread["sequence_run_id"] == run_id, "sequence_run_id must come back set (the prose's own check)"

    directory = await comm.list_participants(thread_id=thread_id, tenant_key=tenant)
    names = [p["participant_id"] for p in directory["participants"]]
    print(f"[BE-9462 GREEN] participants after the ONE-CALL create_thread(creator_id=...): {names!r}")

    assert conductor_agent_id in names, (
        "MEASUREMENT: create_thread(creator_id=<conductor agent_id>) alone -- the ONE call the "
        "new prose renders -- lands the conductor on its own thread's participant directory."
    )


@pytest.mark.asyncio
async def test_legacy_no_agent_id_caller_keeps_the_prior_two_step_script(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    p1 = await _seed_project(db_session, tenant)

    run = await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session).create(
        project_ids=[p1],
        resolved_order=[p1],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    conductor_agent_id = run["conductor_agent_id"]
    run_id = run["id"]

    chapter = _build_ch_chain_staging(
        run_id=run_id, resolved_order=[p1], execution_mode="claude_code_cli", job_id="job-legacy"
    )
    assert "creator_id" not in chapter, "no agent_id in scope -> no creator_id rendered, exactly as before"
    assert "join_thread(thread_id=<the returned id>)" in chapter, "the legacy path keeps the explicit join step"

    comm = CommThreadService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    thread = await comm.create_thread(subject="Chain: legacy", sequence_run_id=run_id, tenant_key=tenant)
    thread_id = thread["thread_id"]

    directory = await comm.list_participants(thread_id=thread_id, tenant_key=tenant)
    assert [p["participant_id"] for p in directory["participants"]] == [], (
        "create_thread alone (no creator_id) must still produce an empty directory on this path"
    )

    await comm.join_thread(thread_id=thread_id, participant_id=conductor_agent_id, tenant_key=tenant)
    directory = await comm.list_participants(thread_id=thread_id, tenant_key=tenant)
    names = [p["participant_id"] for p in directory["participants"]]
    assert conductor_agent_id in names, "the legacy two-step script must still land the conductor on the thread"
