# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9296a — the DURABLE record of a hand-off to the operator.

FE-9289c already drops a bell entry when a baton lands on the operator, but it is
built from the live WebSocket event and stored client-side. A hand-off that arrived
while the dashboard was closed was therefore never seen at all, and one seen on the
laptop did not exist on the phone: the agent did everything right and the request
still evaporated. This is the server row that survives a reload and reaches a second
browser.

Two properties carry the weight and both are tested here: it fires ONLY for a
hand-off to the human (an agent-to-agent baton is coordination, not an interruption),
and it is written only AFTER the baton commits.

Parallel-safe: rollback-isolated ``db_session``, fresh tenant per test, no
module-level mutable state.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.notifications import Notification
from giljo_mcp.schemas.jsonb_notification_payloads import NOTIFICATION_PAYLOAD_VALIDATORS
from giljo_mcp.services.comm_handover_notification import NOTIFICATION_TYPE, handover_dedupe_key
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


def _tk(suffix: str) -> str:
    return f"tk_be9296a_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> str:
    """Seed taxonomy + the tenant's single human. Returns the operator's id."""
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        # display_name is a derived property (full_name -> first/last -> username),
        # so the fixture sets the column that feeds it rather than the property.
        operator = User(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            username=f"op_{uuid.uuid4().hex[:8]}",
            email=f"op_{uuid.uuid4().hex[:8]}@example.test",
            password_hash="x",
            full_name="Sam Rivera",
            is_active=True,
        )
        db_session.add(operator)
        await db_session.flush()
    return operator.id


async def _thread(svc: CommThreadService, tenant: str) -> str:
    created = await svc.create_thread(subject="handover", creator_id="em", tenant_key=tenant)
    thread_id = created["thread_id"]
    await svc.join_thread(thread_id=thread_id, participant_id="em", display_name="P1 Orchestrator", tenant_key=tenant)
    await svc.join_thread(thread_id=thread_id, participant_id="worker-1", display_name="Worker", tenant_key=tenant)
    return thread_id


async def _rows(db_session, tenant: str) -> list[Notification]:
    with tenant_session_context(db_session, tenant):
        result = await db_session.execute(
            select(Notification).where(Notification.tenant_key == tenant, Notification.type == NOTIFICATION_TYPE)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# The registry is closed — a new type needs a schema or the write is rejected
# ---------------------------------------------------------------------------


def test_the_payload_type_is_registered():
    """``NotificationService._validate_fields`` rejects unregistered types outright.

    Without this entry the emit would fail at the write boundary, silently (the
    emitter is best-effort), and the durable row would never appear.
    """
    assert NOTIFICATION_TYPE in NOTIFICATION_PAYLOAD_VALIDATORS


def test_the_payload_schema_forbids_unknown_keys():
    """extra='forbid' — this payload has a known shape, so drift must fail loudly."""
    model = NOTIFICATION_PAYLOAD_VALIDATORS[NOTIFICATION_TYPE]
    assert model.model_config.get("extra") == "forbid"
    ok = model(thread_id="t1", chat_id="CHT-0001", handed_by="P1 Orchestrator")
    assert ok.handed_by == "P1 Orchestrator"
    # handed_by is optional: an anonymous hand-off still gets a durable row.
    assert model(thread_id="t1", chat_id="CHT-0001").handed_by is None


def test_the_dedupe_key_is_per_thread():
    """One OPEN row per thread, so a bouncing baton leaves one entry, not a stack."""
    assert handover_dedupe_key("t1") == handover_dedupe_key("t1")
    assert handover_dedupe_key("t1") != handover_dedupe_key("t2")


# ---------------------------------------------------------------------------
# It fires for the operator, and only for the operator
# ---------------------------------------------------------------------------


async def test_a_baton_to_the_operator_writes_a_durable_row(db_manager, db_session):
    tenant = _tk("tooperator")
    operator_id = await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    await svc.pass_baton(thread_id=thread_id, to=operator_id, from_agent="em", tenant_key=tenant)

    rows = await _rows(db_session, tenant)
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == operator_id
    assert row.payload["thread_id"] == thread_id
    assert row.payload["handed_by"] == "P1 Orchestrator"
    # The body names the agent — the whole point of the mechanism.
    assert "P1 Orchestrator" in row.body


async def test_the_operator_alias_reaches_the_same_row(db_manager, db_session):
    """Agents hand over with the literal "user"; that must produce the row too.

    ``resolve_operator_alias`` expands it before the target is validated, so this is
    the path an agent actually takes — if it missed, the mechanism would work only
    for callers who already knew the operator's uuid, which is the discoverability
    problem BE-9365b existed to remove.
    """
    tenant = _tk("alias")
    operator_id = await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    await svc.pass_baton(thread_id=thread_id, to="user", from_agent="em", tenant_key=tenant)

    rows = await _rows(db_session, tenant)
    assert len(rows) == 1
    assert rows[0].user_id == operator_id


async def test_an_agent_to_agent_baton_writes_nothing(db_manager, db_session):
    """Coordination between agents must not interrupt the human."""
    tenant = _tk("agenttoagent")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    await svc.pass_baton(thread_id=thread_id, to="worker-1", from_agent="em", tenant_key=tenant)

    assert await _rows(db_session, tenant) == []


async def test_clearing_the_baton_writes_nothing(db_manager, db_session):
    """'none' obligates nobody, so there is nothing to tell the operator about."""
    tenant = _tk("none")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    await svc.pass_baton(thread_id=thread_id, to="none", from_agent="em", tenant_key=tenant)

    assert await _rows(db_session, tenant) == []


async def test_a_repeated_handover_does_not_stack_rows(db_manager, db_session):
    """A thread that bounces back and forth leaves ONE unread entry."""
    tenant = _tk("dedupe")
    operator_id = await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    for _ in range(3):
        await svc.pass_baton(thread_id=thread_id, to=operator_id, from_agent="em", tenant_key=tenant)
        await svc.pass_baton(thread_id=thread_id, to="worker-1", from_agent="em", tenant_key=tenant)

    assert len(await _rows(db_session, tenant)) == 1


async def test_the_atomic_post_with_baton_path_also_writes_the_row(db_manager, db_session):
    """The auto-pass is the DEFAULT hand-off, so it must produce the row too.

    Covering only the standalone ``pass_baton`` would leave the common path — a
    directed action-request that auto-passes — with no durable record. That is the
    BE-9292a lesson: the default path is the one that goes untested.
    """
    tenant = _tk("atomic")
    operator_id = await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.post_to_thread(
        thread_id=thread_id,
        content="need your call",
        from_agent="em",
        to_participant=operator_id,
        requires_action=True,
        pass_baton_to=operator_id,
        tenant_key=tenant,
    )
    assert result["baton_passed"] is True

    rows = await _rows(db_session, tenant)
    assert len(rows) == 1
    assert rows[0].payload["handed_by"] == "P1 Orchestrator"


async def test_an_anonymous_handover_still_writes_a_row(db_manager, db_session):
    """Not knowing WHO handed over is no reason to lose the hand-off entirely."""
    tenant = _tk("anonrow")
    operator_id = await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    await svc.pass_baton(thread_id=thread_id, to=operator_id, tenant_key=tenant)

    rows = await _rows(db_session, tenant)
    assert len(rows) == 1
    assert rows[0].payload["handed_by"] is None
    assert "waiting on you" in rows[0].body


async def test_a_refused_handover_writes_no_row(db_manager, db_session):
    """BE-9292a: nothing moved, so the operator must not be told anything did."""
    tenant = _tk("refusedrow")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="nobody-here", from_agent="em", tenant_key=tenant)

    assert result.get("success") is False
    assert await _rows(db_session, tenant) == []


async def test_a_failing_emit_never_unwinds_the_baton(db_manager, db_session, monkeypatch):
    """The baton is the load-bearing act; the bell is the nicety.

    A notification failure must leave the hand-off intact — the recipient still finds
    it via get_my_turn and the thread itself.

    The break is injected at ``NotificationService.create``, INSIDE the emitter's own
    try block, so this exercises the production guard. Patching the emitter function
    itself would jump over that guard and prove only that the test can raise.
    """
    tenant = _tk("emitfail")
    operator_id = await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("notification store down")

    monkeypatch.setattr(
        "giljo_mcp.services.notification_service.NotificationService.create",
        _boom,
    )

    result = await svc.pass_baton(thread_id=thread_id, to=operator_id, from_agent="em", tenant_key=tenant)

    # The hand-off stands, and the recipient can still find it.
    assert result["next_action_owner"] == operator_id
    turn = await svc.get_my_turn(agent_id=operator_id, tenant_key=tenant)
    assert thread_id in [t["thread_id"] for t in turn["threads"]]
    assert await _rows(db_session, tenant) == []
