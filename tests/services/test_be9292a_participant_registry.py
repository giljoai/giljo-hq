# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Service-layer tests for BE-9292a — the participant registry is authoritative.

The MCP-boundary reproductions of both gaps live in
``tests/integration/test_be9292a_participant_registry_mcp_boundary.py``. These
cover what only the service layer can reach:

- ROWS ALREADY IN THE OLD SHAPE. The write-boundary fix stops the two registries
  diverging from now on, but every thread that already diverged would stay wedged
  forever without a second answer. Per the repo's data-facing-change rule the
  answer is tolerance, not data surgery: a reader holding a delivered post enrols
  itself on the next read, so a CE self-hoster with no operator recovers on its
  own and no migration touches live rows.
- THE COUNT AND THE DRAIN AGREE. get_workflow_status counted unread posts from
  the delivery registry while mark_read gated on the enrolment registry, so an
  agent could be shown as owing N replies it could not acknowledge — and be held
  at closeout for exactly that. The two must now agree.
- A DISPLAY LABEL SHADOWING A REGISTERED ID is announced rather than silently
  minted as a second identity.
- HANDING THE BATON BACK TO THE HUMAN keeps working, participant row or not.

Parallel-safe: db_session (TransactionalTestContext), no module-level mutable
state, each test owns its setup. Edition Scope: CE.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.models.auth import User
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.models.tasks import Message, MessageRecipient
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session: AsyncSession, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _deliver_the_old_way(
    db_session: AsyncSession,
    tenant: str,
    *,
    thread_id: str,
    to_agent: str,
    project_id: str | None = None,
    n: int = 1,
) -> None:
    """Deliver posts the way the code did BEFORE this fix: a message plus a
    ``message_recipients`` row, and NO participant row. This is the shape sitting in
    every database that ran the old build — it cannot be produced through
    ``post_to_thread`` any more, which is the point of the fix."""
    for i in range(n):
        msg = Message(
            tenant_key=tenant,
            project_id=project_id,
            thread_id=thread_id,
            content=f"decision needed {i}",
            message_type="direct",
            status="pending",
            requires_action=True,
            from_agent_id="em",
        )
        db_session.add(msg)
        await db_session.flush()
        db_session.add(MessageRecipient(message_id=msg.id, agent_id=to_agent, tenant_key=tenant))
    await db_session.commit()


async def _participant_row(db_session: AsyncSession, tenant: str, thread_id: str, pid: str):
    with tenant_session_context(db_session, tenant):
        return (
            await db_session.execute(
                select(CommParticipant).where(
                    CommParticipant.tenant_key == tenant,
                    CommParticipant.thread_id == thread_id,
                    CommParticipant.participant_id == pid,
                )
            )
        ).scalar_one_or_none()


async def test_thread_that_already_diverged_heals_itself_on_the_next_read(db_manager, db_session):
    """A reader holding a delivered post but no participant row (the pre-fix shape)
    drains successfully and is enrolled in passing — no migration, no operator."""
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="legacy divergence", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    await _deliver_the_old_way(db_session, tenant, thread_id=tid, to_agent="stranded-lane", n=2)
    assert await _participant_row(db_session, tenant, tid, "stranded-lane") is None, "precondition: no row yet"

    drained = await svc.get_thread_history(
        thread_id=tid, as_participant="stranded-lane", unread_only=True, mark_read=True, tenant_key=tenant
    )

    assert drained.get("success") is not False, f"a delivered-to reader was refused: {drained}"
    assert drained["marked_read"] == 2
    healed = await _participant_row(db_session, tenant, tid, "stranded-lane")
    assert healed is not None, "draining a delivered post must leave the reader in the directory"
    assert healed.participant_type == "agent"
    assert healed.last_seen_at is not None, "the read that healed the row is also activity"


async def test_a_reader_with_nothing_delivered_is_not_enrolled_by_asking(db_manager, db_session):
    """The heal keys on DELIVERY, never on the request. Enrolment-by-asking would
    make the registry meaningless and let anyone ack a thread they have no standing
    on — mark_read is the one write path on this read."""
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="no standing", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.post_to_thread(thread_id=tid, content="town square", from_agent="em", tenant_key=tenant)

    refused = await svc.get_thread_history(thread_id=tid, as_participant="ghost", mark_read=True, tenant_key=tenant)

    assert refused["success"] is False
    assert refused["error"] == "NOT_A_PARTICIPANT"
    assert await _participant_row(db_session, tenant, tid, "ghost") is None


async def test_workflow_status_unread_count_and_drain_ability_agree(db_manager, db_session):
    """The defect in one sentence: an agent was counted as owing N replies by the
    delivery registry while the enrolment registry made those N impossible to
    acknowledge — and closeout blocked on the count. Count and drain must agree."""
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name="BE-9292a registry project",
        description="count vs drain",
        mission="count and drain must agree",
        status="active",
        tenant_key=tenant,
        product_id=_owning_product_project.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.commit()
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant,
        project_id=project.id,
        job_type="analyzer",
        mission="mission analyzer",
        status="active",
    )
    db_session.add(job)
    execution = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant,
        agent_display_name="analyzer",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(execution)

    thread = await svc.create_thread(
        subject="project thread", creator_id="em", project_id=project.id, tenant_key=tenant
    )
    tid = thread["thread_id"]
    await _deliver_the_old_way(
        db_session, tenant, thread_id=tid, to_agent=execution.agent_id, project_id=project.id, n=3
    )

    workflow = WorkflowStatusService(db_manager=None, tenant_manager=TenantManager(), test_session=db_session)
    before = await workflow.get_workflow_status(project.id, tenant)
    owed = next(d for d in before.agents if d.agent_id == execution.agent_id)
    assert owed.unread_messages == 3
    assert {t.thread_id: t.unread_count for t in owed.unread_by_thread}[tid] == 3

    drained = await svc.get_thread_history(
        thread_id=tid, as_participant=execution.agent_id, unread_only=True, mark_read=True, tenant_key=tenant
    )
    assert drained.get("success") is not False, f"the agent could not drain what it was counted for: {drained}"
    assert drained["marked_read"] == 3

    after = await workflow.get_workflow_status(project.id, tenant)
    settled = next(d for d in after.agents if d.agent_id == execution.agent_id)
    assert settled.unread_messages == 0, "what the agent drained must stop being counted against it"


async def test_display_label_author_is_told_which_id_is_registered(db_manager, db_session):
    """The incident shape: a conductor registered under an id posts under its
    friendly label. The label is not rewritten (BE-9037 keys on the declared slug),
    but the response now names the id a hand-off would actually reach."""
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="label vs id", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    conductor_id = str(uuid.uuid4())
    await svc.join_thread(
        thread_id=tid,
        participant_id=conductor_id,
        display_name="Ledger Zero Conductor",
        tenant_key=tenant,
    )

    posted = await svc.post_to_thread(
        thread_id=tid, content="chain advancing", from_agent="Ledger Zero Conductor", tenant_key=tenant
    )

    assert posted["from_agent_id"] == "Ledger Zero Conductor", "the declared slug is never rewritten"
    assert posted["attribution_warning"] is not None
    assert conductor_id in posted["attribution_warning"]

    # A second post from the now-registered label carries no warning — the notice
    # fires on the identity being minted, not on every message forever.
    again = await svc.post_to_thread(
        thread_id=tid, content="still advancing", from_agent="Ledger Zero Conductor", tenant_key=tenant
    )
    assert again["attribution_warning"] is None


async def test_baton_can_still_be_handed_back_to_the_human(db_manager, db_session):
    """A human is reachable through the Hub whether or not they ever spoke on the
    thread — my-turn is per-user, not per-participation. Refusing this would strand
    every agent trying to hand a decision back to the operator."""
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    user = User(id=str(uuid.uuid4()), tenant_key=tenant, username=f"operator_{uuid.uuid4().hex[:6]}")
    db_session.add(user)
    await db_session.commit()

    thread = await svc.create_thread(subject="needs a human", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    assert await _participant_row(db_session, tenant, tid, user.id) is None, "precondition: never joined"

    handoff = await svc.pass_baton(thread_id=tid, to=user.id, tenant_key=tenant)
    assert handoff.get("success") is not False, f"the operator was refused the baton: {handoff}"
    assert handoff["next_action_owner"] == user.id


async def test_undeliverable_baton_is_refused_with_the_ids_that_would_work(db_manager, db_session):
    """The refusal has to be actionable: an agent reading it must be able to fix the
    hand-off from the payload alone, without guessing."""
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="unroutable", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="lane-a", tenant_key=tenant)

    refused = await svc.pass_baton(thread_id=tid, to="Some Display Label", tenant_key=tenant)

    assert refused["success"] is False
    assert refused["error"] == "BATON_TARGET_NOT_A_PARTICIPANT"
    assert refused["requested"] == "Some Display Label"
    assert refused["valid_participants"] == ["em", "lane-a"]
    assert "join_thread" in refused["hint"]
    # The refusal reports the owner it did NOT change, so a caller patching its view
    # from this response cannot blank the baton the thread still holds.
    assert refused["next_action_owner"] == "em"

    history = await svc.get_thread_history(thread_id=tid, tenant_key=tenant)
    assert history["thread"]["next_action_owner"] == "em", "a refused hand-off moves nothing"


async def test_the_auto_pass_path_is_validated_like_any_other_hand_off(db_manager, db_session):
    """BE-9292a-F1 at the service layer. The BE-9197 auto-pass sets
    ``pass_baton_to := to_participant``, and the addressee was exempt from validation
    as an identity the post enrols — so the guard could not fire on the default
    hand-off. A directed action-request naming a display LABEL is now refused, and the
    refusal names the id that would have reached the conductor."""
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="auto-pass", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    conductor_id = str(uuid.uuid4())
    await svc.join_thread(
        thread_id=tid, participant_id=conductor_id, display_name="Ledger Zero Conductor", tenant_key=tenant
    )

    refused = await svc.post_to_thread(
        thread_id=tid,
        content="DONE - baton back to you",
        from_agent="sub-orch",
        to_participant="Ledger Zero Conductor",
        requires_action=True,
        pass_baton_to="Ledger Zero Conductor",  # what _resolve_pass_baton_to derives
        tenant_key=tenant,
    )

    assert refused["success"] is False
    assert refused["error"] == "TARGET_IS_A_DISPLAY_NAME"
    assert refused["field"] == "to_participant", "the refusal names the string the caller typed"
    assert refused["registered_id"] == conductor_id
    assert refused["next_action_owner"] == "em"

    history = await svc.get_thread_history(thread_id=tid, tenant_key=tenant)
    assert history["thread"]["next_action_owner"] == "em", "a refused hand-off moves nothing"
    assert await _participant_row(db_session, tenant, tid, "Ledger Zero Conductor") is None


async def test_a_label_already_minted_as_a_participant_is_still_refused(db_manager, db_session):
    """The permanence half. A phantom row for a label used to satisfy the registry
    check on every later call, so the validator's own allowlist was fed by unvalidated
    input and the guard decayed with each mistyped addressee. The collision check
    outranks registration, which also heals threads already carrying such a row —
    tolerance rather than data surgery, so no CE self-hoster needs an operator."""
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="already poisoned", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    conductor_id = str(uuid.uuid4())
    await svc.join_thread(
        thread_id=tid, participant_id=conductor_id, display_name="Ledger Zero Conductor", tenant_key=tenant
    )
    # The phantom row a pre-fix build would have minted, planted directly.
    await svc.join_thread(thread_id=tid, participant_id="Ledger Zero Conductor", tenant_key=tenant)
    assert await _participant_row(db_session, tenant, tid, "Ledger Zero Conductor") is not None

    refused = await svc.pass_baton(thread_id=tid, to="Ledger Zero Conductor", tenant_key=tenant)

    assert refused["success"] is False, "a registered phantom laundered the hand-off past the validator"
    assert refused["error"] == "TARGET_IS_A_DISPLAY_NAME"
    assert refused["registered_id"] == conductor_id


async def test_an_unknown_addressee_that_shadows_nobody_is_still_delivered(db_manager, db_session):
    """The regression the narrow check must not cause. First-contact directed posts
    are legitimate, common and previously working; only a genuine collision is
    refused, because only a collision has a registered agent hiding behind it."""
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="first contact", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(
        thread_id=tid, participant_id=str(uuid.uuid4()), display_name="Ledger Zero Conductor", tenant_key=tenant
    )

    posted = await svc.post_to_thread(
        thread_id=tid,
        content="lane-z: take it",
        from_agent="em",
        to_participant="lane-z-never-seen",
        requires_action=True,
        pass_baton_to="lane-z-never-seen",
        tenant_key=tenant,
    )

    assert posted.get("success") is not False, f"a plain first-contact addressee was refused: {posted}"
    assert posted["baton_passed"] is True
    assert await _participant_row(db_session, tenant, tid, "lane-z-never-seen") is not None


async def test_a_string_that_is_both_an_id_and_a_display_name_is_refused_honestly(db_manager, db_session):
    """A recorded decision, not an accident.

    When a string is BOTH a registered id and another participant's display name,
    delivery is genuinely ambiguous, and the two cases that produce it — a legacy
    phantom row and a real id that happens to match a display name — cannot be told
    apart from the columns. It refuses either way, because guessing which identity the
    sender meant is precisely how the original hand-off was lost. What it must not do
    is claim the target is 'not an id' when it is one.
    """
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="ambiguous", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="conductor", display_name="Relay", tenant_key=tenant)
    await svc.join_thread(thread_id=tid, participant_id="Relay", display_name="Relay Coordinator", tenant_key=tenant)

    refused = await svc.pass_baton(thread_id=tid, to="Relay", tenant_key=tenant)

    assert refused["success"] is False
    assert refused["error"] == "TARGET_IS_A_DISPLAY_NAME"
    assert "ambiguous" in refused["hint"]
    assert "not an id" not in refused["hint"], "the hint must not deny an id that genuinely exists"
    assert "conductor" in refused["hint"]


async def test_the_remedy_the_ambiguous_refusal_names_actually_clears_the_shadow(db_manager, db_session):
    """BE-9292a-F2 — a refusal that names a remedy has to be right about it.

    The ambiguous case ships the only remedy there is, and it is documented nowhere
    else: have the SHADOWER re-join under a display name that is not another
    participant's id. That claim rests on ``join_thread`` being the sole authoritative
    writer of ``display_name`` — every other writer fills blanks and never corrects —
    so if it were wrong the refusal would be permanent and the payload would be a
    second piece of misdirection rather than a fix. Walked end to end here: refuse,
    follow the printed remedy, hand off again, and the turn must land.
    """
    tenant = f"tk_be9292a_{uuid.uuid4().hex[:8]}"
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="shadowed", creator_id="em", tenant_key=tenant)
    tid = thread["thread_id"]
    # The replacement-lane shape: a new lane joins under the name of the one it took over.
    await svc.join_thread(thread_id=tid, participant_id="lane-a", display_name="Relay", tenant_key=tenant)
    await svc.join_thread(thread_id=tid, participant_id="lane-a-replacement", display_name="lane-a", tenant_key=tenant)

    refused = await svc.pass_baton(thread_id=tid, to="lane-a", tenant_key=tenant)
    assert refused["success"] is False
    assert refused["registered_id"] == "lane-a-replacement"

    # Follow the remedy verbatim: the shadower re-joins under a name that is not an id.
    await svc.join_thread(
        thread_id=tid, participant_id="lane-a-replacement", display_name="Relay Replacement", tenant_key=tenant
    )

    passed = await svc.pass_baton(thread_id=tid, to="lane-a", tenant_key=tenant)
    assert passed.get("success") is not False, f"the remedy the payload prints does not work: {passed}"
    history = await svc.get_thread_history(thread_id=tid, tenant_key=tenant)
    assert history["thread"]["next_action_owner"] == "lane-a", "the turn did not land on the agent that polls it"
