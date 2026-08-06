# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9289a — the server owns Hub identity (registration, kind, harness, liveness).

Three verified defects, each reproduced here BEFORE the fix (fail-first):

1. ``add_participant`` is ``ON CONFLICT DO NOTHING``, so the nameless row written by
   ``_auto_enroll_project_roster`` wins permanently: a later ``join_thread`` carrying a
   real display name is silently discarded. The directory then has no name to render.
2. Poster registration only happens inside the BROADCAST branch and only when
   ``thread.project_id`` is set. A direct message registers nobody, and NO post on a
   standalone / chain thread registers anybody — so the poster has no participant row,
   and the UI has nothing authoritative to resolve the author against.
3. Nothing on a message says whether its author was an agent or the human user. The
   frontend guessed from the SHAPE of ``from_agent_id`` ("looks like a UUID therefore
   human"), which mislabeled agents that post under their own UUID.

The fix makes the SERVER resolve all of it: ``from_kind`` stamped at post time, a
participant row guaranteed for every poster on every thread, ``display_name`` upserted,
``harness`` stamped from the MCP handshake (never self-declared), ``last_seen_at``
stamped on post / read / poll.

MUSEUM RULE: ``from_agent_id`` keeps its exact functional meaning (recipient
self-exclusion, baton matching, read cursors — see comm_thread_service.py:268-279).
``from_kind`` is strictly additive alongside it; nothing is rewritten to a UUID.

Parallel-safe: real DB via the rollback-isolated ``db_session`` fixture
(TransactionalTestContext), no module-level mutable state, each test owns its setup,
every query is tenant-scoped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.models.tasks import Message
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9289a_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _participant(db_session, tenant: str, thread_id: str, participant_id: str) -> CommParticipant | None:
    with tenant_session_context(db_session, tenant):
        return (
            await db_session.execute(
                select(CommParticipant).where(
                    CommParticipant.tenant_key == tenant,
                    CommParticipant.thread_id == thread_id,
                    CommParticipant.participant_id == participant_id,
                )
            )
        ).scalar_one_or_none()


async def _message(db_session, tenant: str, message_id: str) -> Message:
    with tenant_session_context(db_session, tenant):
        return (
            await db_session.execute(select(Message).where(Message.tenant_key == tenant, Message.id == message_id))
        ).scalar_one()


async def _seed_project_with_agent(db_session, tenant: str, agent_id: str) -> str:
    """A project carrying one ACTIVE agent, so the auto-enroll roster path has a subject."""
    with tenant_session_context(db_session, tenant):
        project = Project(
            id=str(uuid.uuid4()),
            name=f"BE-9289a {uuid.uuid4().hex[:6]}",
            description="identity foundation test project",
            mission="exercise participant registration",
            status="active",
            tenant_key=tenant,
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
            implementation_launched_at=datetime.now(UTC),
        )
        db_session.add(project)
        await db_session.flush()

        job = AgentJob(
            tenant_key=tenant,
            project_id=project.id,
            job_type="implementer",
            mission="do work",
            status="active",
        )
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            AgentExecution(
                agent_id=agent_id,
                job_id=job.job_id,
                tenant_key=tenant,
                agent_display_name=f"display-{agent_id}",
                status="working",
            )
        )
        await db_session.flush()
    return project.id


# ---------------------------------------------------------------------------
# Defect 1 — a real name must survive a nameless enroll (DoD 3).
# ---------------------------------------------------------------------------


async def test_named_join_lands_over_nameless_enroll(db_manager, db_session):
    """FAIL-FIRST: enroll nameless, then join with a name — the name must land.

    Today ``add_participant`` is ON CONFLICT DO NOTHING, so the NULL-name row wins
    permanently and the directory can never learn the agent's name.
    """
    tenant = _tk("upsert")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="naming", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    # Enrolled by machinery, with no name (exactly what auto-enroll writes).
    await svc.join_thread(thread_id=tid, participant_id="agent-worker", tenant_key=tenant)
    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name is None

    # The agent now declares itself properly.
    await svc.join_thread(
        thread_id=tid, participant_id="agent-worker", display_name="Backend Implementer", tenant_key=tenant
    )

    row = await _participant(db_session, tenant, tid, "agent-worker")
    assert row.display_name == "Backend Implementer"


async def test_nameless_rejoin_does_not_wipe_an_existing_name(db_manager, db_session):
    """The upsert must not swing the other way: a later NAMELESS join preserves the name."""
    tenant = _tk("preserve")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="naming", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.join_thread(thread_id=tid, participant_id="agent-worker", display_name="Real Name", tenant_key=tenant)
    await svc.join_thread(thread_id=tid, participant_id="agent-worker", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name == "Real Name"


async def test_declared_name_survives_a_later_auto_enroll(db_manager, db_session):
    """FAIL-FIRST (audit B1): a name the agent DECLARED must survive auto-enroll.

    The other direction of the upsert, and the one that fails. ``_auto_enroll_project_roster``
    passes a NON-NULL roster display_name and re-runs on EVERY broadcast to a
    project-anchored thread. Under an incoming-write-always-wins rule the badge is
    decided by whichever write happened last: declared name → broadcast → roster name →
    re-join → declared name → broadcast → ... A flapping badge is exactly the chaos this
    chain exists to remove, so authority is settled by WRITER, not by column.
    """
    tenant = _tk("nameflap")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agent(db_session, tenant, "agent-worker")
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="naming", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]
    # The agent declares itself properly. join_thread is an AUTHORITATIVE writer.
    await svc.join_thread(
        thread_id=tid, participant_id="agent-worker", display_name="P1 Orchestrator", tenant_key=tenant
    )

    # A broadcast re-runs auto-enroll over the whole roster — a PLACEHOLDER writer.
    await svc.post_to_thread(thread_id=tid, content="ship it", from_agent="agent-orch", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name == "P1 Orchestrator"


async def test_auto_enroll_still_fills_a_blank_name(db_manager, db_session):
    """The placeholder writer must still FILL blanks — it just may not CORRECT.

    Guards the fix from over-swinging: an agent that never joined has no name, and the
    roster name is strictly better than nothing for the card.
    """
    tenant = _tk("namefill")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agent(db_session, tenant, "agent-worker")
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="naming", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]
    # Enrolled by machinery with no name at all, never having declared itself.
    await svc.join_thread(thread_id=tid, participant_id="agent-worker", tenant_key=tenant)
    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name is None

    await svc.post_to_thread(thread_id=tid, content="ship it", from_agent="agent-orch", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name == "display-agent-worker"


async def test_declared_role_survives_a_later_auto_enroll(db_manager, db_session):
    """GUARD: the ``auto-enrolled`` placeholder must never overwrite a role the agent
    declared — step c renders a role-tinted badge off this field. Same rule as the name:
    auto-enroll is a placeholder writer, so it fills blanks and never corrects."""
    tenant = _tk("role")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agent(db_session, tenant, "agent-worker")
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="roles", creator_id="agent-orch", project_id=project_id, tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-worker", role="implementer", tenant_key=tenant)

    # A broadcast on a project thread re-runs auto-enroll over the whole roster.
    await svc.post_to_thread(thread_id=tid, content="ship it", from_agent="agent-orch", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-worker")).role == "implementer"


# ---------------------------------------------------------------------------
# Defect 2 — every poster registered, on every thread (DoD 2).
# ---------------------------------------------------------------------------


async def test_post_on_standalone_thread_registers_the_poster(db_manager, db_session):
    """FAIL-FIRST: a post on a STANDALONE thread must register its author.

    Today registration only runs in the broadcast branch and only when the thread is
    project-anchored, so a standalone / chain thread leaves the poster with no row.
    """
    tenant = _tk("standalone")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="standalone", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.post_to_thread(thread_id=tid, content="hello", from_agent="lane-3-worker", tenant_key=tenant)

    row = await _participant(db_session, tenant, tid, "lane-3-worker")
    assert row is not None, "a poster on a standalone thread must be registered"
    assert row.participant_type == "agent"
    assert row.display_name  # never NULL — the card has a name to render


async def test_direct_message_registers_the_poster(db_manager, db_session):
    """FAIL-FIRST: the DM branch skips registration entirely today."""
    tenant = _tk("dm")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="dm", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-beta", tenant_key=tenant)

    await svc.post_to_thread(
        thread_id=tid, content="just you", from_agent="agent-alpha", to_participant="agent-beta", tenant_key=tenant
    )

    assert await _participant(db_session, tenant, tid, "agent-alpha") is not None


async def test_registering_the_poster_does_not_make_it_its_own_recipient(db_manager, db_session):
    """Self-exclusion still holds once the poster is a participant (museum rule:
    ``from_agent_id`` keeps its self-exclusion meaning)."""
    tenant = _tk("selfexcl")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="excl", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-beta", tenant_key=tenant)

    result = await svc.post_to_thread(thread_id=tid, content="ping", from_agent="agent-alpha", tenant_key=tenant)

    assert "agent-alpha" not in result["recipients"]
    assert "agent-beta" in result["recipients"]


# ---------------------------------------------------------------------------
# Defect 3 — from_kind resolved server-side (DoD 1).
# ---------------------------------------------------------------------------


async def test_agent_post_is_stamped_from_kind_agent(db_manager, db_session):
    """An agent post carries from_kind 'agent' — even when the slug is UUID-shaped.

    This is the original incident: an agent posting under its own UUID was rendered as
    the HUMAN user because the frontend guessed from the string's shape.
    """
    tenant = _tk("kindagent")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="kind", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    uuid_shaped_agent = str(uuid.uuid4())

    result = await svc.post_to_thread(
        thread_id=tid, content="I am an agent", from_agent=uuid_shaped_agent, tenant_key=tenant
    )

    msg = await _message(db_session, tenant, result["message_id"])
    assert msg.from_kind == "agent"
    # Museum rule: the functional identity field is untouched, still the declared slug.
    assert msg.from_agent_id == uuid_shaped_agent


async def test_principal_fallback_post_is_stamped_from_kind_user(db_manager, db_session):
    """A post with no from_agent falls back to the principal and is stamped 'user'."""
    tenant = _tk("kinduser")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="kind", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    result = await svc.post_to_thread(thread_id=tid, content="I am the operator", user_id="user-123", tenant_key=tenant)

    msg = await _message(db_session, tenant, result["message_id"])
    assert msg.from_kind == "user"


async def test_from_kind_is_exposed_on_the_read_path(db_manager, db_session):
    """The serializer both the MCP and REST reads share must carry from_kind."""
    tenant = _tk("kindread")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="kind", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.post_to_thread(thread_id=tid, content="hi", from_agent="agent-alpha", tenant_key=tenant)

    history = await svc.get_thread_history(thread_id=tid, tenant_key=tenant)
    assert history["messages"][0]["from_kind"] == "agent"


# ---------------------------------------------------------------------------
# DoD 4/5 — harness stamped server-side, last_seen_at stamped on activity.
# ---------------------------------------------------------------------------


async def test_harness_is_stamped_from_the_detected_token(db_manager, db_session):
    """The harness comes from the MCP handshake, threaded down as detected_harness."""
    tenant = _tk("harness")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="harness", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.join_thread(
        thread_id=tid, participant_id="agent-alpha", detected_harness="claude-code", tenant_key=tenant
    )

    assert (await _participant(db_session, tenant, tid, "agent-alpha")).harness == "claude-code"


async def test_harness_defaults_to_generic_when_undetected(db_manager, db_session):
    """No detection (REST post, in-memory transport, unknown clientInfo) → 'generic'."""
    tenant = _tk("generic")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="harness", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.post_to_thread(thread_id=tid, content="no clientInfo here", from_agent="agent-alpha", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-alpha")).harness == "generic"


async def test_a_later_detected_harness_updates_the_row(db_manager, db_session):
    """An agent that reconnects from a different harness re-stamps — server-owned,
    always trustworthy, so latest wins."""
    tenant = _tk("reharness")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="harness", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.join_thread(thread_id=tid, participant_id="agent-alpha", detected_harness="codex", tenant_key=tenant)
    await svc.join_thread(
        thread_id=tid, participant_id="agent-alpha", detected_harness="claude-code", tenant_key=tenant
    )

    assert (await _participant(db_session, tenant, tid, "agent-alpha")).harness == "claude-code"


async def test_last_seen_is_stamped_on_post(db_manager, db_session):
    """Liveness: posting stamps last_seen_at, so a live/idle dot is derivable."""
    tenant = _tk("seen")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="seen", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.post_to_thread(thread_id=tid, content="here", from_agent="agent-alpha", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-alpha")).last_seen_at is not None


async def test_last_seen_advances_on_read(db_manager, db_session):
    """A read is activity too — an agent that only listens still reads as alive.

    Joining already stamps liveness, so the meaningful assertion is that a subsequent
    READ ADVANCES the mark rather than merely setting it once.
    """
    tenant = _tk("seenread")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="seen", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-reader", tenant_key=tenant)
    at_join = (await _participant(db_session, tenant, tid, "agent-reader")).last_seen_at
    assert at_join is not None

    await svc.get_thread_history(thread_id=tid, as_participant="agent-reader", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-reader")).last_seen_at > at_join


async def test_read_does_not_enrol_a_non_participant(db_manager, db_session):
    """The liveness stamp is an UPDATE, never an insert: reading a thread you never
    joined must not silently register you as a participant."""
    tenant = _tk("seenlurk")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="seen", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.get_thread_history(thread_id=tid, as_participant="agent-lurker", tenant_key=tenant)

    assert await _participant(db_session, tenant, tid, "agent-lurker") is None


async def test_baton_poll_advances_last_seen_across_threads(db_manager, db_session):
    """get_my_turn is thread-agnostic, so it marks the agent alive on every thread it
    belongs to — the common case for an agent that is waiting rather than talking."""
    tenant = _tk("seenpoll")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    first = (await svc.create_thread(subject="one", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    second = (await svc.create_thread(subject="two", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    await svc.join_thread(thread_id=first, participant_id="agent-waiter", tenant_key=tenant)
    await svc.join_thread(thread_id=second, participant_id="agent-waiter", tenant_key=tenant)
    before = [
        (await _participant(db_session, tenant, first, "agent-waiter")).last_seen_at,
        (await _participant(db_session, tenant, second, "agent-waiter")).last_seen_at,
    ]

    await svc.get_my_turn(agent_id="agent-waiter", tenant_key=tenant)

    assert (await _participant(db_session, tenant, first, "agent-waiter")).last_seen_at > before[0]
    assert (await _participant(db_session, tenant, second, "agent-waiter")).last_seen_at > before[1]


async def test_participant_read_exposes_harness_and_last_seen(db_manager, db_session):
    """The directory read must carry the two new fields — step b's enriched list and
    step c's agent pills both consume them."""
    tenant = _tk("directory")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="directory", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(
        thread_id=tid,
        participant_id="agent-alpha",
        display_name="Alpha",
        detected_harness="claude-code",
        tenant_key=tenant,
    )

    listed = await svc.list_participants(thread_id=tid, tenant_key=tenant)
    alpha = next(p for p in listed["participants"] if p["participant_id"] == "agent-alpha")
    assert alpha["harness"] == "claude-code"
    assert "last_seen_at" in alpha


async def test_an_undetected_post_does_not_downgrade_a_known_harness(db_manager, db_session):
    """FAIL-FIRST (found by BE-9289b's enrichment tests): ``generic`` must never clobber
    a real detection.

    ``generic`` is the resolver's "I could not tell" value, not an observation. Under a
    plain latest-non-null-wins rule, an agent that joined from claude-code and then
    posted through any path without clientInfo — the REST route, the in-memory
    transport — had its harness silently rewritten to generic. The pill then lied about
    a fact the whole point of which is that agents cannot misreport it.
    """
    tenant = _tk("harnessdowngrade")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="harness", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(
        thread_id=tid, participant_id="agent-alpha", detected_harness="claude-code", tenant_key=tenant
    )

    # A post with no detection at all — the common REST path.
    await svc.post_to_thread(thread_id=tid, content="still me", from_agent="agent-alpha", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-alpha")).harness == "claude-code"


async def test_a_genuine_reconnect_from_another_harness_still_updates(db_manager, db_session):
    """The guard must not swing the other way: a CONCRETE new detection still wins."""
    tenant = _tk("harnessswitch")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="harness", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-alpha", detected_harness="codex", tenant_key=tenant)
    await svc.post_to_thread(
        thread_id=tid, content="moved", from_agent="agent-alpha", detected_harness="claude-code", tenant_key=tenant
    )

    assert (await _participant(db_session, tenant, tid, "agent-alpha")).harness == "claude-code"
