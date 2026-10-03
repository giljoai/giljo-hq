# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.services.comm_baton_targets import HubTargetRefusedError
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




async def test_pass_baton_returns_the_handers_registered_display_name(db_manager, db_session):
    tenant = _tk("named")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="worker-1", from_agent="em", tenant_key=tenant)

    assert result["from_display_name"] == "P1 Orchestrator"
    assert result["from_kind"] == "agent"


async def test_the_name_comes_from_the_directory_not_from_the_caller(db_manager, db_session):
    tenant = _tk("resolved")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="worker-1", from_agent="em", tenant_key=tenant)

    assert result["from_display_name"] != "em"
    assert result["from_display_name"] == "P1 Orchestrator"


async def test_an_anonymous_handover_carries_no_name_rather_than_a_made_up_one(db_manager, db_session):
    tenant = _tk("anon")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="worker-1", tenant_key=tenant)

    assert result["from_display_name"] is None
    assert result["from_kind"] is None
    assert result["next_action_owner"] == "worker-1"


async def test_an_unregistered_hander_falls_back_to_its_slug(db_manager, db_session):
    tenant = _tk("slug")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    result = await svc.pass_baton(thread_id=thread_id, to="worker-1", from_agent="lane-7", tenant_key=tenant)

    assert result["from_display_name"] == "lane-7"
    assert result["from_kind"] == "agent"


async def test_resolving_the_hander_does_not_enrol_them_as_a_participant(db_manager, db_session):
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
    tenant = _tk("refused")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread_id = await _thread(svc, tenant)

    with pytest.raises(HubTargetRefusedError) as caught:
        await svc.pass_baton(thread_id=thread_id, to="nobody-here", from_agent="em", tenant_key=tenant)
    result = caught.value.as_refusal()

    assert result["success"] is False
    assert "from_display_name" not in result




async def test_thread_update_carries_the_hander_and_stays_additive():
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
    import inspect

    from api.endpoints._comm_ws import broadcast_thread_message, broadcast_thread_update

    message_params = set(inspect.signature(broadcast_thread_message).parameters)
    update_params = set(inspect.signature(broadcast_thread_update).parameters)

    assert {"from_display_name", "from_kind"} <= message_params
    assert {"from_display_name", "from_kind"} <= update_params


@pytest.mark.parametrize("missing", ["from_display_name", "from_kind"])
def test_identity_fields_are_optional_on_the_update_transport(missing):
    import inspect

    from api.endpoints._comm_ws import broadcast_thread_update

    assert inspect.signature(broadcast_thread_update).parameters[missing].default is None
