# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9457 — one agent, two views, two different statuses.

Reported by the operator: *"an agent listed as silent on the main card view, shows as
'monitoring' when you click into the card. different status for different views of same
agent."*

"Silent" means we have lost contact. "Monitoring" means it is working. A user acting on
the wrong one either abandons a healthy agent or waits on a dead one.

WHAT WAS ACTUALLY WRONG. Both views render the same component (``AgentPill.vue``)
through the same map (``statusConfig.js``: ``silent -> 'Silent'``, ``idle ->
'Monitoring'``), so this was never a display-map bug. They were handed different VALUES:

- the Hub thread-card list gets ``status`` from ``agent_executions`` via
  ``_comm_thread_list_enrichment_mixin.list_threads_enriched`` -> ``'silent'``;
- the opened thread's header pills come from ``GET /threads/{id}/participants`` ->
  ``CommThreadService.list_participants``, whose payload had **no status key at all**.
  ``useAgentStatusDot.displayStatus`` reads an absent status with a present
  ``last_seen_at`` as ``'idle'``, and ``'idle'`` is labelled "Monitoring".

So the detail view was not reporting a competing judgement. It was reporting a default it
invented because it was handed nothing — and it invented the one that reads HEALTHY for
an agent we had lost contact with, defeating ``useAgentStatusDot``'s own stated rule that
absent data must not read as healthy.

These tests pin both views to the one source (``agent_executions``, newest execution by
``started_at DESC`` — the rule ``AgentJobRepository.get_latest_execution`` uses) and fail
if they ever diverge again.

Parallel-safe: real DB via the rollback-isolated ``db_session`` fixture, no module-level
mutable state, each test owns its setup, every query is tenant-scoped.
"""

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
    """One ``agent_executions`` row for ``agent_id``.

    Several rows per agent is the normal case — succession reuses the agent_id — so the
    ordering rule is part of what "same source" has to mean.
    """
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
    """What the MAIN CARD VIEW shows — GET /threads, the Hub thread-card list."""
    listed = await svc.list_threads(viewer_id="user-operator", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread_id)
    return next(p for p in card["participants"] if p["participant_id"] == agent_id).get("status")


async def _detail_view_status(svc: CommThreadService, tenant: str, thread_id: str, agent_id: str):
    """What CLICKING INTO THE CARD shows — GET /threads/{id}/participants.

    Returns the participant dict so a test can tell ``status: None`` (we have no
    execution for this agent) apart from no ``status`` key at all (the defect: the client
    then fabricates ``idle`` / "Monitoring").
    """
    listed = await svc.list_participants(thread_id=thread_id, tenant_key=tenant)
    return next(p for p in listed["participants"] if p["participant_id"] == agent_id)


async def _thread_with_agent(svc: CommThreadService, tenant: str, agent_id: str) -> str:
    thread = await svc.create_thread(subject="TSK-9457", creator_id="user-operator", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id=agent_id, display_name="Alpha", tenant_key=tenant)
    return tid


# ---------------------------------------------------------------------------
# The reproduction
# ---------------------------------------------------------------------------


async def test_detail_view_reports_the_silent_agent_as_silent(db_manager, db_session):
    """FAIL-FIRST: the operator's exact report.

    An agent the silence detector marked ``silent`` must not read as anything else in the
    participant directory. Before the fix this assertion fails on a MISSING key, which is
    precisely the defect — the client fills the hole with ``idle``/"Monitoring".
    """
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
    """The regression pin the DoD asks for: the card and the detail must never diverge.

    Asserted as an EQUALITY between the two payloads rather than against a literal, so it
    still fails if either side is changed to read somewhere new.
    """
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
    """Not just ``silent``. ``idle`` is included deliberately: it is the value the broken
    detail view happened to guess, so a fix that hard-codes agreement only for ``silent``
    would pass the test above and still be wrong.
    """
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
    """One ``agent_id`` accumulates several executions through succession. Both views must
    pick the SAME row (``started_at DESC LIMIT 1``) or they disagree again for a different
    reason — a fix that serves *a* status but resolves it differently is not a fix.
    """
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
    """The other half of the invariant, and the reason the fix is a real status rather
    than a coalesced default: an agent that joined but never registered an execution must
    serve ``None``.

    The client renders ``None`` + no sighting as a hollow "Never checked in" ring. Filling
    a default in here would claim we heard from something we never heard from — the same
    error in the opposite direction, and the enrichment query documents it as deliberate.
    """
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
    """A same-named agent in another tenant must not supply this one's status."""
    mine = _tk("mine")
    theirs = _tk("theirs")
    await _seed(db_session, mine)
    await _seed(db_session, theirs)
    svc = _service(db_manager, db_session)
    agent_id = "agent-shared-name"

    tid = await _thread_with_agent(svc, mine, agent_id)
    # Only the OTHER tenant has an execution for this agent id.
    await _seed_execution(db_session, theirs, agent_id, "working", started_at=datetime.now(UTC))

    detail = await _detail_view_status(svc, mine, tid, agent_id)

    assert detail["status"] is None


async def test_liveness_carries_the_status_alongside_its_own_freshness_band(db_manager, db_session):
    """Second-order effect, pinned so it is deliberate rather than accidental.

    ``get_participant_liveness`` builds its rows as ``{**row, "liveness": ...}`` over
    ``list_participants``, so it now carries ``status`` too. That is right and worth
    keeping: ``liveness`` is a freshness judgement made from ``last_seen_at``, ``status``
    is what the agent's execution actually says, and they answer different questions. A
    conductor deciding whether to reassign wants both — an agent can be ``quiet`` on the
    thread while still ``working`` in its harness.

    Pinned because a future refactor that stops spreading the row would drop the field
    silently, and a caller reading only ``liveness`` would be back to one signal.
    """
    tenant = _tk("liveness")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    agent_id = "agent-alpha"

    tid = await _thread_with_agent(svc, tenant, agent_id)
    await _seed_execution(db_session, tenant, agent_id, "silent", started_at=datetime.now(UTC))

    liveness = await svc.get_participant_liveness(thread_id=tid, tenant_key=tenant)
    alpha = next(p for p in liveness["participants"] if p["participant_id"] == agent_id)

    assert alpha["status"] == "silent"
    assert "liveness" in alpha  # its own band is untouched
