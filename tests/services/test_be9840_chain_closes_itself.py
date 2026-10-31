# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.chain_member_detach import detach_chain_member
from giljo_mcp.services.project_helpers import complete_chain_run_if_finished, mark_chain_member_status
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number
from tests.services.test_be9153_chain_settlement import _create_settlement_approval, _seed_member


pytestmark = pytest.mark.asyncio


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


async def _running_chain(
    db_session: AsyncSession, tenant_key: str, size: int = 2, review_policy: str = "auto_close"
) -> tuple[dict, list[str]]:
    product = Product(
        id=str(uuid4()), tenant_key=tenant_key, name=f"P {uuid4().hex[:6]}", description="x", is_active=False
    )
    db_session.add(product)
    ids = []
    for _ in range(size):
        project = Project(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"Member {uuid4().hex[:6]}",
            description="x",
            mission="x",
            status="active",
            execution_mode="claude_code_cli",
            series_number=next_series_number(),
        )
        db_session.add(project)
        ids.append(project.id)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    svc = _run_svc(db_session)
    run = await svc.create(
        project_ids=ids,
        resolved_order=ids,
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
        review_policy=review_policy,
    )
    await svc.update(
        run_id=run["id"],
        tenant_key=tenant_key,
        status="running",
        current_index=0,
        project_statuses=dict.fromkeys(ids, "implementing"),
    )
    return run, ids


async def _complete(db_session: AsyncSession, tenant_key: str, project_id: str) -> None:
    await mark_chain_member_status(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=project_id,
        tenant_key=tenant_key,
        status="completed",
        test_session=db_session,
    )


async def _detach(db_session: AsyncSession, tenant_key: str, project_id: str) -> bool:
    return await detach_chain_member(
        db_manager=None,
        tenant_manager=TenantManager(),
        project_id=project_id,
        tenant_key=tenant_key,
        test_session=db_session,
    )


async def _run_exists(db_session: AsyncSession, tenant_key: str, run_id: str) -> bool:
    try:
        await _run_svc(db_session).get(run_id=run_id, tenant_key=tenant_key)
    except ResourceNotFoundError:
        return False
    return True


async def test_last_member_completing_ends_the_run_without_the_conductor(db_session):
    tenant = TenantManager.generate_tenant_key()
    run, (p1, p2) = await _running_chain(db_session, tenant)

    await _complete(db_session, tenant, p1)
    assert await _run_exists(db_session, tenant, run["id"]), "one member still open: the run must stay"
    await _complete(db_session, tenant, p2)

    assert not await _run_exists(db_session, tenant, run["id"])


async def test_dropping_the_last_open_member_ends_the_run(db_session):
    tenant = TenantManager.generate_tenant_key()
    run, (p1, p2) = await _running_chain(db_session, tenant)

    await _complete(db_session, tenant, p1)
    assert await _detach(db_session, tenant, p2) is True

    assert not await _run_exists(db_session, tenant, run["id"])


async def test_dropping_a_member_while_another_is_open_keeps_the_run(db_session):
    tenant = TenantManager.generate_tenant_key()
    run, (p1, p2, _p3) = await _running_chain(db_session, tenant, size=3)

    await _complete(db_session, tenant, p1)
    assert await _detach(db_session, tenant, p2) is True

    assert await _run_exists(db_session, tenant, run["id"])


async def test_pending_settlement_approval_holds_the_run_open(db_session):
    tenant = TenantManager.generate_tenant_key()
    member = await _seed_member(db_session, tenant)
    run, (p1,) = await _running_chain(db_session, tenant, size=1)
    await _create_settlement_approval(db_session, tenant, member, run)

    await _complete(db_session, tenant, p1)

    assert await _run_exists(db_session, tenant, run["id"]), "BE-9153: settlement hold must keep the run"


async def test_conductor_finish_after_self_finish_is_a_noop(db_session):
    tenant = TenantManager.generate_tenant_key()
    run, (p1,) = await _running_chain(db_session, tenant, size=1)
    await _complete(db_session, tenant, p1)

    finished = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=run["conductor_agent_id"],
        tenant_key=tenant,
        test_session=db_session,
    )
    assert finished is False


async def _review(db_session: AsyncSession, tenant_key: str, run_id: str, project_id: str) -> None:
    await _run_svc(db_session).mark_member_reviewed(run_id=run_id, project_id=project_id, tenant_key=tenant_key)


async def test_per_card_run_stays_until_the_user_reviews_the_last_card(db_session):
    tenant = TenantManager.generate_tenant_key()
    run, (p1, p2) = await _running_chain(db_session, tenant, review_policy="per_card")

    await _complete(db_session, tenant, p1)
    await _complete(db_session, tenant, p2)
    assert await _run_exists(db_session, tenant, run["id"]), "completed but unreviewed: the user still has to review"
    after_member_path = await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)
    assert after_member_path["reviewed_project_ids"] == [], "the member path must not mark cards reviewed"

    await _review(db_session, tenant, run["id"], p1)
    assert await _run_exists(db_session, tenant, run["id"])
    await _review(db_session, tenant, run["id"], p2)
    assert not await _run_exists(db_session, tenant, run["id"])


async def test_per_card_run_ends_when_the_last_open_member_is_dropped_and_the_rest_are_reviewed(db_session):
    tenant = TenantManager.generate_tenant_key()
    run, (p1, p2) = await _running_chain(db_session, tenant, review_policy="per_card")

    await _complete(db_session, tenant, p1)
    await _review(db_session, tenant, run["id"], p1)
    assert await _run_exists(db_session, tenant, run["id"]), "p2 is still open"
    assert await _detach(db_session, tenant, p2) is True

    assert not await _run_exists(db_session, tenant, run["id"])


async def test_per_card_dropped_member_needs_no_review(db_session):
    tenant = TenantManager.generate_tenant_key()
    run, (p1, p2) = await _running_chain(db_session, tenant, review_policy="per_card")

    assert await _detach(db_session, tenant, p2) is True
    await _complete(db_session, tenant, p1)
    assert await _run_exists(db_session, tenant, run["id"])
    await _review(db_session, tenant, run["id"], p1)

    assert not await _run_exists(db_session, tenant, run["id"])


async def test_no_conductor_job_is_left_working_once_the_run_ended_itself(db_session):
    tenant = TenantManager.generate_tenant_key()
    run, (p1,) = await _running_chain(db_session, tenant, size=1)

    await _complete(db_session, tenant, p1)

    rows = (
        await db_session.execute(
            select(AgentJob.status, AgentExecution.status)
            .join(AgentExecution, AgentExecution.job_id == AgentJob.job_id)
            .where(AgentExecution.tenant_key == tenant, AgentExecution.agent_id == run["conductor_agent_id"])
        )
    ).all()
    assert rows == [("cancelled", "decommissioned")]
