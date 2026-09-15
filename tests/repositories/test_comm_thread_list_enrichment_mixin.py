# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.tasks import Message
from giljo_mcp.repositories._comm_thread_list_enrichment_mixin import CommThreadListEnrichmentMixin
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_enrich_{suffix}_{uuid.uuid4().hex[:8]}"


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
    display_name: str = "Seeded Agent",
) -> None:
    with tenant_session_context(db_session, tenant):
        job = AgentJob(
            job_id=str(uuid.uuid4()),
            tenant_key=tenant,
            job_type="implementer",
        )
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            AgentExecution(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                job_id=job.job_id,
                tenant_key=tenant,
                agent_display_name=display_name,
                status=status,
                started_at=started_at,
            )
        )
        await db_session.flush()


async def _age_message(db_session, tenant: str, message_id: str, *, seconds: int = 60) -> None:
    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            update(Message)
            .where(Message.id == message_id, Message.tenant_key == tenant)
            .values(created_at=datetime.now(UTC) - timedelta(seconds=seconds))
        )
        await db_session.flush()


async def _seed_project(db_session, tenant: str, name: str) -> str:
    with tenant_session_context(db_session, tenant):
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
            name=name,
            description="enrichment test project",
            mission="exercise the card facts",
            status="active",
            tenant_key=tenant,
            product_id=_owning_product_project.id,
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
            implementation_launched_at=datetime.now(UTC),
        )
        db_session.add(project)
        await db_session.flush()
    return project.id




def test_the_repository_serves_the_enrichment_by_identity():
    assert issubclass(CommThreadRepository, CommThreadListEnrichmentMixin)
    assert CommThreadRepository.list_threads_enriched is CommThreadListEnrichmentMixin.list_threads_enriched




async def test_card_facts_for_a_project_thread(db_manager, db_session):
    tenant = _tk("facts")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant, "Quiet Cards rollout")
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="bound", creator_id="agent-orch", project_id=project_id, tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(
        thread_id=tid,
        participant_id="agent-alpha",
        display_name="Alpha",
        role="implementer",
        detected_harness="claude-code",
        tenant_key=tenant,
    )
    await svc.post_to_thread(thread_id=tid, content="shipping it now", from_agent="agent-alpha", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["project_name"] == "Quiet Cards rollout"
    assert card["last_message"]["excerpt"] == "shipping it now"
    assert card["last_message"]["author"] == "Alpha"
    assert card["last_message"]["created_at"]

    alpha = next(p for p in card["participants"] if p["participant_id"] == "agent-alpha")
    assert (alpha["display_name"], alpha["role"], alpha["harness"]) == ("Alpha", "implementer", "claude-code")
    assert "last_seen_at" in alpha


async def test_a_standalone_thread_has_no_project_name(db_manager, db_session):
    tenant = _tk("noproject")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="standalone", creator_id="agent-orch", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["project_name"] is None


async def test_a_silent_thread_has_no_last_message(db_manager, db_session):
    tenant = _tk("silent")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="quiet", creator_id="agent-orch", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["last_message"] is None
    assert card["unread"] is False




async def test_unread_is_true_when_never_read(db_manager, db_session):
    tenant = _tk("unread")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant)
    await svc.post_to_thread(thread_id=thread["thread_id"], content="hi", from_agent="agent-a", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["unread"] is True


async def test_unread_is_a_boolean_not_a_count(db_manager, db_session):
    tenant = _tk("bool")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    for n in range(3):
        await svc.post_to_thread(thread_id=tid, content=f"msg {n}", from_agent="agent-a", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["unread"] is True
    assert isinstance(card["unread"], bool)


async def test_unread_is_false_once_the_reader_has_drained_the_thread(db_manager, db_session):
    tenant = _tk("read")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="reader-1", tenant_key=tenant)
    await svc.post_to_thread(thread_id=tid, content="hi", from_agent="agent-a", tenant_key=tenant)
    await svc.get_thread_history(thread_id=tid, as_participant="reader-1", mark_read=True, tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="reader-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["unread"] is False


async def test_unread_is_per_viewer(db_manager, db_session):
    tenant = _tk("perviewer")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="reader-1", tenant_key=tenant)
    await svc.post_to_thread(thread_id=tid, content="hi", from_agent="agent-a", tenant_key=tenant)
    await svc.get_thread_history(thread_id=tid, as_participant="reader-1", mark_read=True, tenant_key=tenant)

    drained = next(
        t for t in (await svc.list_threads(viewer_id="reader-1", tenant_key=tenant))["threads"] if t["thread_id"] == tid
    )
    fresh = next(
        t for t in (await svc.list_threads(viewer_id="reader-2", tenant_key=tenant))["threads"] if t["thread_id"] == tid
    )

    assert drained["unread"] is False
    assert fresh["unread"] is True




async def test_last_message_names_the_post_it_describes(db_manager, db_session):
    tenant = _tk("anchor")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="hand-off", creator_id="agent-orch", tenant_key=tenant))["thread_id"]

    older = await svc.post_to_thread(thread_id=tid, content="first", from_agent="agent-a", tenant_key=tenant)
    newest = await svc.post_to_thread(thread_id=tid, content="over to you", from_agent="agent-a", tenant_key=tenant)
    await _age_message(db_session, tenant, older["message_id"])

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["last_message"]["id"] == newest["message_id"]
    assert card["last_message"]["id"] != older["message_id"]
    assert card["last_message"]["excerpt"] == "over to you"


async def test_the_message_anchor_is_the_message_id_not_the_thread_id(db_manager, db_session):
    tenant = _tk("anchorlabel")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="labelled", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    await svc.post_to_thread(thread_id=tid, content="a post", from_agent="agent-a", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["last_message"]["id"] != tid
    assert card["last_message"]["id"] != card["thread_id"]




async def test_the_agent_path_stays_unenriched(db_manager, db_session):
    tenant = _tk("optin")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant)

    listed = await svc.list_threads(tenant_key=tenant)

    assert listed["threads"]
    for key in ("project_name", "participants", "last_message", "unread"):
        assert key not in listed["threads"][0]


async def test_enrichment_is_tenant_scoped(db_manager, db_session):
    mine, theirs = _tk("mine"), _tk("theirs")
    await _seed(db_session, mine)
    await _seed(db_session, theirs)
    svc_mine = _service(db_manager, db_session)
    tid = (await svc_mine.create_thread(subject="t", creator_id="agent-orch", tenant_key=mine))["thread_id"]
    await svc_mine.post_to_thread(thread_id=tid, content="mine", from_agent="agent-a", tenant_key=mine)

    listed = await svc_mine.list_threads(viewer_id="operator-1", tenant_key=theirs)

    assert all(t["thread_id"] != tid for t in listed["threads"])




async def test_a_bound_thread_is_titled_from_its_project(db_manager, db_session):
    tenant = _tk("title")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant, "Message Hub redesign")
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(
        subject="(project comms)", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["title"] == "Message Hub redesign"
    assert card["subject"] == "(project comms)"


async def test_a_chain_hub_keeps_its_stored_subject_run_id_and_all(db_manager, db_session):
    tenant = _tk("chainhub")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    run_id = str(uuid.uuid4())
    subject = f"Chain: Message Hub redesign - run {run_id}"
    thread = await svc.create_thread(subject=subject, creator_id="conductor", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["title"] == subject
    assert run_id in card["title"]


async def test_a_bound_threads_organic_subject_still_yields_the_project_title(db_manager, db_session):
    tenant = _tk("organic")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant, "Canonical Project Name")
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(
        subject="some agent's own wording", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["title"] == "Canonical Project Name"




async def test_thread_list_survives_a_viewer_who_belongs_to_several_threads(db_manager, db_session):
    tenant = _tk("multi")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    viewer = "operator-multi"

    first = await svc.create_thread(subject="first thread", creator_id="agent-orch", tenant_key=tenant)
    second = await svc.create_thread(subject="second thread", creator_id="agent-orch", tenant_key=tenant)
    for thread in (first, second):
        await svc.join_thread(thread_id=thread["thread_id"], participant_id=viewer, tenant_key=tenant)
    await svc.post_to_thread(
        thread_id=first["thread_id"], content="something new", from_agent="agent-orch", tenant_key=tenant
    )

    listed = await svc.list_threads(viewer_id=viewer, tenant_key=tenant)

    ids = {t["thread_id"] for t in listed["threads"]}
    assert {first["thread_id"], second["thread_id"]} <= ids

    by_id = {t["thread_id"]: t for t in listed["threads"]}
    assert by_id[first["thread_id"]]["unread"] is True
    assert by_id[second["thread_id"]]["unread"] is False




async def _card_with(svc, tenant: str, tid: str, viewer: str = "operator-1") -> dict:
    listed = await svc.list_threads(viewer_id=viewer, tenant_key=tenant)
    return next(t for t in listed["threads"] if t["thread_id"] == tid)


async def _join_and_card(svc, tenant: str, agent_id: str) -> dict:
    thread = await svc.create_thread(subject="status dot", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id=agent_id, display_name="Alpha", tenant_key=tenant)
    card = await _card_with(svc, tenant, tid)
    return next(p for p in card["participants"] if p["participant_id"] == agent_id)


async def test_participant_status_comes_from_the_latest_execution(db_manager, db_session):
    tenant = _tk("status_latest")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    await _seed_execution(db_session, tenant, "agent-alpha", "complete", started_at=datetime(2026, 1, 1, tzinfo=UTC))
    await _seed_execution(db_session, tenant, "agent-alpha", "working", started_at=datetime(2026, 6, 1, tzinfo=UTC))

    assert (await _join_and_card(svc, tenant, "agent-alpha"))["status"] == "working"


async def test_a_staged_successor_outranks_the_execution_it_replaced(db_manager, db_session):
    tenant = _tk("status_staged")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    await _seed_execution(db_session, tenant, "agent-beta", "complete", started_at=datetime(2026, 5, 1, tzinfo=UTC))
    await _seed_execution(db_session, tenant, "agent-beta", "staged", started_at=None)

    assert (await _join_and_card(svc, tenant, "agent-beta"))["status"] == "staged"


async def test_status_is_null_when_the_agent_never_registered_an_execution(db_manager, db_session):
    tenant = _tk("status_absent")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    participant = await _join_and_card(svc, tenant, "agent-ghost")
    assert "status" in participant, "the key must be present so the client can distinguish it from an old payload"
    assert participant["status"] is None


async def test_participant_status_is_tenant_scoped(db_manager, db_session):
    mine = _tk("status_mine")
    theirs = _tk("status_theirs")
    await _seed(db_session, mine)
    await _seed(db_session, theirs)
    svc = _service(db_manager, db_session)

    await _seed_execution(db_session, theirs, "agent-shared", "working", started_at=datetime(2026, 6, 1, tzinfo=UTC))

    assert (await _join_and_card(svc, mine, "agent-shared"))["status"] is None
