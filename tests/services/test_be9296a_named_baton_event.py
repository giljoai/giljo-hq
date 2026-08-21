# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9296a — a baton hand-off says WHO handed it over.

The operator's bell could only say "<thread> — waiting on you", which is the least
useful half of the sentence: they already know which thread they are being pulled
into, and not which agent is blocked on them. ``broadcast_thread_message`` has
carried ``from_display_name`` + ``from_kind`` since BE-9289a; ``broadcast_thread_update``
did not, so two transports that should have matched did not.

The identity is resolved SERVER-SIDE from the participant directory, never taken as
self-declared display text — the same rule BE-9289a established for post authorship.

Parallel-safe: rollback-isolated ``db_session``, fresh tenant per test, no
module-level mutable state.
"""

from __future__ import annotations

import uuid

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


def _tk(suffix: str) -> str:
    return f"tk_be9296a_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _thread(svc: CommThreadService, tenant: str) -> str:
    created = await svc.create_thread(subject="handover", creator_id="em", tenant_key=tenant)
    thread_id = created["thread_id"]
    await svc.join_thread(thread_id=thread_id, participant_id="em", display_name="P1 Orchestrator", tenant_key=tenant)
    await svc.join_thread(thread_id=thread_id, participant_id="worker-1", display_name="Worker", tenant_key=tenant)
    return thread_id


# ---------------------------------------------------------------------------
# The service resolves the hander's identity
# ---------------------------------------------------------------------------


async def test_pass_baton_returns_the_handers_registered_display_name(db_manager, db_session):
    """The bell's whole purpose: name the agent, not the thread."""
    tenant = _tk("named")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="worker-1", from_agent="em", tenant_key=tenant)

    assert result["from_display_name"] == "P1 Orchestrator"
    assert result["from_kind"] == "agent"


async def test_the_name_comes_from_the_directory_not_from_the_caller(db_manager, db_session):
    """Identity is server-resolved, never self-declared text (the BE-9289a rule).

    The caller supplies an ID; the NAME is looked up. Otherwise the alert would
    render whatever string a caller chose to send.
    """
    tenant = _tk("resolved")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="worker-1", from_agent="em", tenant_key=tenant)

    # "em" is the id; "P1 Orchestrator" is what the directory holds for it.
    assert result["from_display_name"] != "em"
    assert result["from_display_name"] == "P1 Orchestrator"


async def test_an_anonymous_handover_carries_no_name_rather_than_a_made_up_one(db_manager, db_session):
    """Omitting from_agent must preserve the exact pre-BE-9296a payload."""
    tenant = _tk("anon")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="worker-1", tenant_key=tenant)

    assert result["from_display_name"] is None
    assert result["from_kind"] is None
    assert result["next_action_owner"] == "worker-1"


async def test_an_unregistered_hander_falls_back_to_its_slug(db_manager, db_session):
    """An ad-hoc lane id is legitimate, so tolerate it — it is a name, not a route."""
    tenant = _tk("slug")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="worker-1", from_agent="lane-7", tenant_key=tenant)

    assert result["from_display_name"] == "lane-7"
    assert result["from_kind"] == "agent"


async def test_resolving_the_hander_does_not_enrol_them_as_a_participant(db_manager, db_session):
    """A hand-off must not silently mint a directory row for a non-participant.

    Registration belongs to posting (writing a message IS participation), not to
    moving the baton — otherwise every stray hand-off grows the roster and the
    liveness view fills with entries that never acted.
    """
    tenant = _tk("noenrol")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    before = (await svc.list_participants(thread_id=thread_id, tenant_key=tenant))["count"]
    await svc.pass_baton(thread_id=thread_id, to="worker-1", from_agent="never-joined", tenant_key=tenant)
    after = await svc.list_participants(thread_id=thread_id, tenant_key=tenant)

    assert after["count"] == before
    assert "never-joined" not in {p["participant_id"] for p in after["participants"]}


async def test_a_refused_handover_still_carries_no_identity(db_manager, db_session):
    """BE-9292a: a refused hand-off moved nothing, so it must announce nothing."""
    tenant = _tk("refused")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="nobody-here", from_agent="em", tenant_key=tenant)

    assert result.get("success") is False
    assert "from_display_name" not in result


# ---------------------------------------------------------------------------
# The WS payload
# ---------------------------------------------------------------------------


async def test_thread_update_carries_the_hander_and_stays_additive():
    """The new fields must not disturb the payload every other caller sends."""
    from api.endpoints._comm_ws import broadcast_thread_update

    sent: list[dict] = []

    class _Manager:
        async def broadcast_event_to_tenant(self, tenant_key, event):
            sent.append(event)

    await broadcast_thread_update(
        _Manager(),
        "tk_x",
        thread_id="t1",
        chat_id="CHT-0001",
        status="open",
        next_action_owner="user-1",
        update_type="baton",
        from_display_name="P1 Orchestrator",
        from_kind="agent",
    )
    assert sent[0]["data"]["from_display_name"] == "P1 Orchestrator"
    assert sent[0]["data"]["from_kind"] == "agent"

    sent.clear()
    # A status/rename/read update omits them and gets nulls — the shape the client's
    # skip-null patch already ignores, so those events are unchanged.
    await broadcast_thread_update(
        _Manager(),
        "tk_x",
        thread_id="t1",
        chat_id="CHT-0001",
        status="resolved",
        next_action_owner=None,
        update_type="status",
    )
    assert sent[0]["data"]["from_display_name"] is None
    assert sent[0]["data"]["from_kind"] is None


def test_both_hub_transports_now_agree_on_identity_fields():
    """The gap this closes: two transports that should have matched did not."""
    import inspect

    from api.endpoints._comm_ws import broadcast_thread_message, broadcast_thread_update

    message_params = set(inspect.signature(broadcast_thread_message).parameters)
    update_params = set(inspect.signature(broadcast_thread_update).parameters)

    assert {"from_display_name", "from_kind"} <= message_params
    assert {"from_display_name", "from_kind"} <= update_params


@pytest.mark.parametrize("missing", ["from_display_name", "from_kind"])
def test_identity_fields_are_optional_on_the_update_transport(missing):
    """Defaulted, so no existing caller had to change."""
    import inspect

    from api.endpoints._comm_ws import broadcast_thread_update

    assert inspect.signature(broadcast_thread_update).parameters[missing].default is None
