# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
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
            name=f"BE-9289a {uuid.uuid4().hex[:6]}",
            description="identity foundation test project",
            mission="exercise participant registration",
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




async def test_named_join_lands_over_nameless_enroll(db_manager, db_session):
    tenant = _tk("upsert")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="naming", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.join_thread(thread_id=tid, participant_id="agent-worker", tenant_key=tenant)
    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name is None

    await svc.join_thread(
        thread_id=tid, participant_id="agent-worker", display_name="Backend Implementer", tenant_key=tenant
    )

    row = await _participant(db_session, tenant, tid, "agent-worker")
    assert row.display_name == "Backend Implementer"


async def test_nameless_rejoin_does_not_wipe_an_existing_name(db_manager, db_session):
    tenant = _tk("preserve")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="naming", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.join_thread(thread_id=tid, participant_id="agent-worker", display_name="Real Name", tenant_key=tenant)
    await svc.join_thread(thread_id=tid, participant_id="agent-worker", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name == "Real Name"


async def test_declared_name_survives_a_later_auto_enroll(db_manager, db_session):
    tenant = _tk("nameflap")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agent(db_session, tenant, "agent-worker")
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="naming", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]
    await svc.join_thread(
        thread_id=tid, participant_id="agent-worker", display_name="P1 Orchestrator", tenant_key=tenant
    )

    await svc.post_to_thread(thread_id=tid, content="ship it", from_agent="agent-orch", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name == "P1 Orchestrator"


async def test_auto_enroll_still_fills_a_blank_name(db_manager, db_session):
    tenant = _tk("namefill")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agent(db_session, tenant, "agent-worker")
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(
        subject="naming", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-worker", tenant_key=tenant)
    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name is None

    await svc.post_to_thread(thread_id=tid, content="ship it", from_agent="agent-orch", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-worker")).display_name == "display-agent-worker"


async def test_declared_role_survives_a_later_auto_enroll(db_manager, db_session):
    tenant = _tk("role")
    await _seed(db_session, tenant)
    project_id = await _seed_project_with_agent(db_session, tenant, "agent-worker")
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="roles", creator_id="agent-orch", project_id=project_id, tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-worker", role="implementer", tenant_key=tenant)

    await svc.post_to_thread(thread_id=tid, content="ship it", from_agent="agent-orch", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-worker")).role == "implementer"




async def test_post_on_standalone_thread_registers_the_poster(db_manager, db_session):
    tenant = _tk("standalone")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="standalone", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.post_to_thread(thread_id=tid, content="hello", from_agent="lane-3-worker", tenant_key=tenant)

    row = await _participant(db_session, tenant, tid, "lane-3-worker")
    assert row is not None, "a poster on a standalone thread must be registered"
    assert row.participant_type == "agent"
    assert row.display_name


async def test_direct_message_registers_the_poster(db_manager, db_session):
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
    tenant = _tk("selfexcl")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="excl", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-beta", tenant_key=tenant)

    result = await svc.post_to_thread(thread_id=tid, content="ping", from_agent="agent-alpha", tenant_key=tenant)

    assert "agent-alpha" not in result["recipients"]
    assert "agent-beta" in result["recipients"]




async def test_agent_post_is_stamped_from_kind_agent(db_manager, db_session):
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
    assert msg.from_agent_id == uuid_shaped_agent


async def test_as_user_post_is_stamped_from_kind_user(db_manager, db_session):
    tenant = _tk("kinduser")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="kind", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    result = await svc.post_to_thread(
        thread_id=tid, content="I am the operator", user_id="user-123", as_user=True, tenant_key=tenant
    )

    msg = await _message(db_session, tenant, result["message_id"])
    assert msg.from_kind == "user"


async def test_from_kind_is_exposed_on_the_read_path(db_manager, db_session):
    tenant = _tk("kindread")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="kind", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.post_to_thread(thread_id=tid, content="hi", from_agent="agent-alpha", tenant_key=tenant)

    history = await svc.get_thread_history(thread_id=tid, tenant_key=tenant)
    assert history["messages"][0]["from_kind"] == "agent"




async def test_harness_is_stamped_from_the_detected_token(db_manager, db_session):
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
    tenant = _tk("generic")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="harness", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.post_to_thread(thread_id=tid, content="no clientInfo here", from_agent="agent-alpha", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-alpha")).harness == "generic"


async def test_a_later_detected_harness_updates_the_row(db_manager, db_session):
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
    tenant = _tk("seen")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="seen", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.post_to_thread(thread_id=tid, content="here", from_agent="agent-alpha", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-alpha")).last_seen_at is not None


async def test_last_seen_advances_on_read(db_manager, db_session):
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
    tenant = _tk("seenlurk")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="seen", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]

    await svc.get_thread_history(thread_id=tid, as_participant="agent-lurker", tenant_key=tenant)

    assert await _participant(db_session, tenant, tid, "agent-lurker") is None


async def test_baton_poll_advances_last_seen_across_threads(db_manager, db_session):
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
    tenant = _tk("harnessdowngrade")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="harness", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(
        thread_id=tid, participant_id="agent-alpha", detected_harness="claude-code", tenant_key=tenant
    )

    await svc.post_to_thread(thread_id=tid, content="still me", from_agent="agent-alpha", tenant_key=tenant)

    assert (await _participant(db_session, tenant, tid, "agent-alpha")).harness == "claude-code"


async def test_a_genuine_reconnect_from_another_harness_still_updates(db_manager, db_session):
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
