# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_tsk9457_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _seed_execution(
    db_session,
    tenant: str,
    agent_id: str,
    status: str,
    *,
    started_at: datetime | None,
) -> None:
    with tenant_session_context(db_session, tenant):
        job = AgentJob(job_id=str(uuid.uuid4()), tenant_key=tenant, job_type="implementer")
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            AgentExecution(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                job_id=job.job_id,
                tenant_key=tenant,
                agent_display_name=f"display-{agent_id}",
                status=status,
                started_at=started_at,
            )
        )
        await db_session.flush()


async def _card_view_status(svc: CommThreadService, tenant: str, thread_id: str, agent_id: str) -> str | None:
    listed = await svc.list_threads(viewer_id="user-operator", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread_id)
    return next(p for p in card["participants"] if p["participant_id"] == agent_id).get("status")


async def _detail_view_status(svc: CommThreadService, tenant: str, thread_id: str, agent_id: str):
    listed = await svc.list_participants(thread_id=thread_id, tenant_key=tenant)
    return next(p for p in listed["participants"] if p["participant_id"] == agent_id)


async def _thread_with_agent(svc: CommThreadService, tenant: str, agent_id: str) -> str:
    thread = await svc.create_thread(subject="TSK-9457", creator_id="user-operator", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id=agent_id, display_name="Alpha", tenant_key=tenant)
    return tid




async def test_detail_view_reports_the_silent_agent_as_silent(db_manager, db_session):
    tenant = _tk("silent")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    agent_id = "agent-alpha"

    tid = await _thread_with_agent(svc, tenant, agent_id)
    await _seed_execution(db_session, tenant, agent_id, "silent", started_at=datetime.now(UTC))

    alpha = await _detail_view_status(svc, tenant, tid, agent_id)

    assert "status" in alpha, (
        "list_participants served no status key at all; useAgentStatusDot then normalises "
        "an absent status with a present last_seen_at to 'idle', which statusConfig labels "
        "'Monitoring' — a lost agent rendered as a working one"
    )
    assert alpha["status"] == "silent"


async def test_both_views_agree_on_one_agent(db_manager, db_session):
    tenant = _tk("agree")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    agent_id = "agent-alpha"

    tid = await _thread_with_agent(svc, tenant, agent_id)
    await _seed_execution(db_session, tenant, agent_id, "silent", started_at=datetime.now(UTC))

    card = await _card_view_status(svc, tenant, tid, agent_id)
    detail = await _detail_view_status(svc, tenant, tid, agent_id)

    assert card == "silent"
    assert detail.get("status") == card, (
        f"card view says {card!r}, detail view says {detail.get('status')!r} — same agent, two screens, two answers"
    )


async def test_the_two_views_agree_across_every_status_the_board_can_show(db_manager, db_session):
    tenant = _tk("statuses")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    for status in ("working", "silent", "idle", "blocked", "sleeping", "complete", "awaiting_user"):
        agent_id = f"agent-{status}"
        tid = await _thread_with_agent(svc, tenant, agent_id)
        await _seed_execution(db_session, tenant, agent_id, status, started_at=datetime.now(UTC))

        card = await _card_view_status(svc, tenant, tid, agent_id)
        detail = await _detail_view_status(svc, tenant, tid, agent_id)

        assert card == status
        assert detail.get("status") == status, f"{status}: card={card!r} detail={detail.get('status')!r}"


async def test_succession_resolves_to_the_same_execution_on_both_views(db_manager, db_session):
    tenant = _tk("succession")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    agent_id = "agent-alpha"

    tid = await _thread_with_agent(svc, tenant, agent_id)
    now = datetime.now(UTC)
    await _seed_execution(db_session, tenant, agent_id, "complete", started_at=now - timedelta(hours=2))
    await _seed_execution(db_session, tenant, agent_id, "silent", started_at=now)

    card = await _card_view_status(svc, tenant, tid, agent_id)
    detail = await _detail_view_status(svc, tenant, tid, agent_id)

    assert card == "silent"
    assert detail.get("status") == "silent"


async def test_an_agent_with_no_execution_reports_null_not_a_healthy_default(db_manager, db_session):
    tenant = _tk("noexec")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    agent_id = "agent-ghost"

    tid = await _thread_with_agent(svc, tenant, agent_id)

    card = await _card_view_status(svc, tenant, tid, agent_id)
    detail = await _detail_view_status(svc, tenant, tid, agent_id)

    assert card is None
    assert "status" in detail
    assert detail["status"] is None


async def test_status_is_tenant_scoped(db_manager, db_session):
    mine = _tk("mine")
    theirs = _tk("theirs")
    await _seed(db_session, mine)
    await _seed(db_session, theirs)
    svc = _service(db_manager, db_session)
    agent_id = "agent-shared-name"

    tid = await _thread_with_agent(svc, mine, agent_id)
    await _seed_execution(db_session, theirs, agent_id, "working", started_at=datetime.now(UTC))

    detail = await _detail_view_status(svc, mine, tid, agent_id)

    assert detail["status"] is None


async def test_liveness_carries_the_status_alongside_its_own_freshness_band(db_manager, db_session):
    tenant = _tk("liveness")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    agent_id = "agent-alpha"

    tid = await _thread_with_agent(svc, tenant, agent_id)
    await _seed_execution(db_session, tenant, agent_id, "silent", started_at=datetime.now(UTC))

    liveness = await svc.get_participant_liveness(thread_id=tid, tenant_key=tenant)
    alpha = next(p for p in liveness["participants"] if p["participant_id"] == agent_id)

    assert alpha["status"] == "silent"
    assert "liveness" in alpha
