# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Service-layer tests for CommThreadService (BE-6054b).

Complements the MCP-boundary test (test_be6054b_comm_thread_mcp_boundary.py) by
exercising the service directly — in particular the LOAD-BEARING carve-out:
``post_to_thread`` is SIDE-EFFECT-FREE. It persists Message + message_recipients
ONLY; it must NOT acknowledge, bump counters, or auto-block completed agents the
way orchestration ``send_message`` does, and it must accept a NULL project_id.

Real DB (rollback-isolated ``db_session``), no mocks. Tenant context is
established with ``tenant_session_context`` as the MCP boundary would.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.auth import User
from giljo_mcp.models.tasks import Message, MessageAcknowledgment
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be6054b_{suffix}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def test_create_thread_registers_creator_and_baton(db_manager, db_session):
    tenant = _tk("create")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="kickoff", creator_id="agent-alpha", tenant_key=tenant)

    assert thread["chat_id"].startswith("CHT-")
    assert thread["next_action_owner"] == "agent-alpha"  # creator holds the baton
    # Creator is registered as a participant.
    history = await svc.get_thread_history(thread_id=thread["thread_id"], tenant_key=tenant)
    assert history["thread"]["chat_id"] == thread["chat_id"]


async def test_post_to_thread_is_side_effect_free(db_manager, db_session):
    """The carve-out: a thread post persists Message + recipients only — it does
    NOT acknowledge (status stays 'pending', no MessageAcknowledgment rows) and
    works on a STANDALONE thread (NULL project_id)."""
    tenant = _tk("sef")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="standalone", creator_id="agent-alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-beta", tenant_key=tenant)

    result = await svc.post_to_thread(thread_id=tid, content="ping", from_agent="agent-alpha", tenant_key=tenant)
    assert "agent-beta" in result["recipients"]
    assert "agent-alpha" not in result["recipients"]  # sender excluded from broadcast

    with tenant_session_context(db_session, tenant):
        msg = (await db_session.execute(select(Message).where(Message.id == result["message_id"]))).scalar_one()
        # Standalone: NULL project_id, thread anchored, NOT auto-acknowledged.
        assert msg.project_id is None
        assert msg.thread_id == tid
        assert msg.status == "pending"
        # SIDE-EFFECT-FREE: no acknowledgment rows were created.
        ack_count = (
            await db_session.execute(
                select(func.count(MessageAcknowledgment.id)).where(
                    MessageAcknowledgment.message_id == result["message_id"]
                )
            )
        ).scalar_one()
        assert ack_count == 0


async def test_username_injection_on_user_post(db_manager, db_session):
    tenant = _tk("user")
    await _seed(db_session, tenant)
    user = User(tenant_key=tenant, username="operator_jane")
    db_session.add(user)
    await db_session.flush()
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="ops", creator_id="agent-alpha", tenant_key=tenant)
    await svc.join_thread(thread_id=thread["thread_id"], participant_id="agent-alpha", tenant_key=tenant)
    result = await svc.post_to_thread(
        thread_id=thread["thread_id"], content="operator here", user_id=user.id, tenant_key=tenant
    )
    assert result["from_display_name"] == "operator_jane"


async def test_from_agent_wins_over_user_id(db_manager, db_session):
    """FE-6122 precedence flip: when BOTH user_id (always injected by the MCP
    wrapper) AND from_agent are present, the AGENT identity wins — the post is
    NOT collapsed to the human principal. The user-only path (no from_agent)
    still attributes to the user (test_username_injection_on_user_post)."""
    tenant = _tk("precedence")
    await _seed(db_session, tenant)
    user = User(tenant_key=tenant, username="operator_jane")
    db_session.add(user)
    await db_session.flush()
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="ident", creator_id="agent-alpha", tenant_key=tenant)
    result = await svc.post_to_thread(
        thread_id=thread["thread_id"],
        content="implementer reporting",
        from_agent="implementer",
        user_id=user.id,  # injected exactly as the real MCP path does
        tenant_key=tenant,
    )
    assert result["from_agent_id"] == "implementer"
    assert result["from_display_name"] == "implementer"
    assert result["from_agent_id"] != user.id


async def test_from_agent_length_cap_raises_validation(db_manager, db_session):
    """from_agent is agent-supplied input — the owning service length-caps it
    before the DB (defense in depth for non-MCP callers), not just the boundary."""
    tenant = _tk("cap")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="a", tenant_key=tenant)
    with pytest.raises(ValidationError):
        await svc.post_to_thread(thread_id=thread["thread_id"], content="x", from_agent="a" * 65, tenant_key=tenant)


async def test_from_agent_resolves_display_name_from_participant(db_manager, db_session):
    """Bug fix: post_to_thread must resolve ``from_display_name`` from the
    poster's OWN comm_participants row (set at join_thread), not echo the raw
    ``from_agent`` UUID verbatim. Ground truth: a dogfood test-mirror thread showed
    every agent message stamped with the raw UUID instead of its friendly role."""
    tenant = _tk("resolve")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="hub badge", creator_id="orchestrator", tenant_key=tenant)
    tid = thread["thread_id"]
    agent_uuid = "aeaeb3eb-ea5c-4c1a-9b1a-000000000001"
    await svc.join_thread(thread_id=tid, participant_id=agent_uuid, display_name="orchestrator", tenant_key=tenant)

    result = await svc.post_to_thread(thread_id=tid, content="status update", from_agent=agent_uuid, tenant_key=tenant)

    # Stored value is the FRIENDLY name, not the raw UUID.
    assert result["from_display_name"] == "orchestrator"
    assert result["from_agent_id"] == agent_uuid  # addressing identity unchanged

    with tenant_session_context(db_session, tenant):
        msg = (await db_session.execute(select(Message).where(Message.id == result["message_id"]))).scalar_one()
        assert msg.from_display_name == "orchestrator"
        assert msg.from_agent_id == agent_uuid


async def test_from_agent_falls_back_when_not_a_participant(db_manager, db_session):
    """Fallback: a poster with no comm_participants row (or one with no recorded
    display_name) never crashes and never renders worse than the pre-fix behavior
    — it falls back to the raw from_agent value."""
    tenant = _tk("fallback")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="hub badge fallback", creator_id="orchestrator", tenant_key=tenant)
    result = await svc.post_to_thread(
        thread_id=thread["thread_id"], content="never joined", from_agent="ghost-agent", tenant_key=tenant
    )
    assert result["from_display_name"] == "ghost-agent"
    assert result["from_agent_id"] == "ghost-agent"


async def test_get_my_turn_and_pass_baton(db_manager, db_session):
    tenant = _tk("baton")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="agent-alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    # BE-9292a: the baton target must be reachable, so beta joins before receiving it.
    # What this test guards is unchanged — the baton moves and get_my_turn follows it.
    await svc.join_thread(thread_id=tid, participant_id="agent-beta", tenant_key=tenant)

    mine = await svc.get_my_turn(agent_id="agent-alpha", tenant_key=tenant)
    assert tid in {t["thread_id"] for t in mine["threads"]}

    handoff = await svc.pass_baton(thread_id=tid, to="agent-beta", tenant_key=tenant)
    assert handoff["next_action_owner"] == "agent-beta"

    beta = await svc.get_my_turn(agent_id="agent-beta", tenant_key=tenant)
    alpha = await svc.get_my_turn(agent_id="agent-alpha", tenant_key=tenant)
    assert tid in {t["thread_id"] for t in beta["threads"]}
    assert tid not in {t["thread_id"] for t in alpha["threads"]}


async def test_pass_baton_none_clears_owner(db_manager, db_session):
    tenant = _tk("clear")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="agent-alpha", tenant_key=tenant)
    res = await svc.pass_baton(thread_id=thread["thread_id"], to="none", tenant_key=tenant)
    assert res["next_action_owner"] is None


async def test_search_threads_by_subject_and_serial(db_manager, db_session):
    tenant = _tk("search")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="rollback playbook", creator_id="a", tenant_key=tenant)

    by_subject = await svc.search_threads(query="playbook", tenant_key=tenant)
    assert thread["thread_id"] in {t["thread_id"] for t in by_subject["threads"]}

    # CHT serial digits also resolve.
    serial_digits = thread["chat_id"].split("-")[1]
    by_serial = await svc.search_threads(query=serial_digits, tenant_key=tenant)
    assert thread["thread_id"] in {t["thread_id"] for t in by_serial["threads"]}


async def test_post_unknown_thread_raises_not_found(db_manager, db_session):
    tenant = _tk("nf")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    with pytest.raises(ResourceNotFoundError):
        await svc.post_to_thread(thread_id="does-not-exist", content="x", from_agent="a", tenant_key=tenant)


async def test_post_empty_content_raises_validation(db_manager, db_session):
    tenant = _tk("empty")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="a", tenant_key=tenant)
    with pytest.raises(ValidationError):
        await svc.post_to_thread(thread_id=thread["thread_id"], content="  ", from_agent="a", tenant_key=tenant)


async def test_is_terminal_status_helper():
    assert CommThreadService.is_terminal_status("resolved") is True
    assert CommThreadService.is_terminal_status("closed") is True
    assert CommThreadService.is_terminal_status("open") is False
    assert CommThreadService.is_terminal_status(None) is False


# ── BE-9037 — harden from_agent at the write boundary ────────────────────────
#
# from_agent feeds the FUNCTIONAL identity field (from_agent_id: recipient
# self-exclusion, baton/get_my_turn matching). The hardening: sanitize (strip
# control/zero-width chars) + reject a supplied value that sanitizes to empty +
# surface (never silently stamp) an omitted from_agent — WITHOUT rewriting the
# slug to a UUID or hard-rejecting unknown slugs (ad-hoc lane ids are legitimate).


async def test_be9037_from_agent_control_chars_are_stripped(db_manager, db_session):
    """A from_agent carrying trailing control/zero-width chars is sanitized before
    the DB — the stored addressing key is the clean slug, no crash, no garbage."""
    tenant = _tk("be9037_strip")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="BE-9037", tenant_key=tenant)
    result = await svc.post_to_thread(
        thread_id=thread["thread_id"], content="hi", from_agent="BE-9037\u200b\x00\ufeff", tenant_key=tenant
    )
    assert result["from_agent_id"] == "BE-9037"  # control/zero-width stripped, slug preserved


async def test_be9037_all_garbage_from_agent_is_rejected(db_manager, db_session):
    """A from_agent that is ONLY control/zero-width chars sanitizes to empty and is
    rejected with a clean ValidationError (422) — never a blank identity written."""
    tenant = _tk("be9037_garbage")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="a", tenant_key=tenant)
    with pytest.raises(ValidationError):
        await svc.post_to_thread(
            thread_id=thread["thread_id"], content="x", from_agent="\u200b\x00\ufeff", tenant_key=tenant
        )


async def test_be9037_omitted_from_agent_surfaces_attribution_warning(db_manager, db_session):
    """TSK-0008 surface-don't-stamp: an omitted from_agent still attributes to the
    authenticated principal (unchanged) but the response carries an advisory. An
    agent that DID pass from_agent gets no warning."""
    tenant = _tk("be9037_warn")
    await _seed(db_session, tenant)
    user = User(tenant_key=tenant, username="operator_kim")
    db_session.add(user)
    await db_session.flush()
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="a", tenant_key=tenant)

    omitted = await svc.post_to_thread(thread_id=thread["thread_id"], content="hi", user_id=user.id, tenant_key=tenant)
    assert omitted["attribution_warning"] is not None
    assert omitted["from_agent_id"] == user.id  # attribution unchanged — surfaced, not blocked

    supplied = await svc.post_to_thread(
        thread_id=thread["thread_id"], content="yo", from_agent="tester", user_id=user.id, tenant_key=tenant
    )
    assert supplied["attribution_warning"] is None
    assert supplied["from_agent_id"] == "tester"


async def test_be9037_ad_hoc_lane_id_posts_and_batons(db_manager, db_session):
    """The tonight-critical guarantee: an ad-hoc lane id that is NOT a registered
    template (e.g. BE-9037) still posts, is stored verbatim as the addressing key,
    self-excludes from its own broadcast, and drives get_my_turn / pass_baton —
    sanitize-and-accept, never reject, never a UUID rewrite."""
    tenant = _tk("be9037_lane")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="op", creator_id="BE-9037", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="SEC-3001b", tenant_key=tenant)

    result = await svc.post_to_thread(thread_id=tid, content="status", from_agent="BE-9037", tenant_key=tenant)
    assert result["from_agent_id"] == "BE-9037"
    assert "SEC-3001b" in result["recipients"]
    assert "BE-9037" not in result["recipients"]  # slug self-exclusion intact

    mine = await svc.get_my_turn(agent_id="BE-9037", tenant_key=tenant)
    assert tid in {t["thread_id"] for t in mine["threads"]}
    handoff = await svc.pass_baton(thread_id=tid, to="SEC-3001b", tenant_key=tenant)
    assert handoff["next_action_owner"] == "SEC-3001b"
