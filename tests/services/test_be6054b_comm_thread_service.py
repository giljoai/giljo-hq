# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.auth import User
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.models.tasks import Message, MessageAcknowledgment
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.product_service import ProductAmbiguousError
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
    assert thread["next_action_owner"] == "agent-alpha"
    history = await svc.get_thread_history(thread_id=thread["thread_id"], tenant_key=tenant)
    assert history["thread"]["chat_id"] == thread["chat_id"]


async def test_post_to_thread_is_side_effect_free(db_manager, db_session):
    tenant = _tk("sef")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="standalone", creator_id="agent-alpha", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="agent-beta", tenant_key=tenant)

    result = await svc.post_to_thread(thread_id=tid, content="ping", from_agent="agent-alpha", tenant_key=tenant)
    assert "agent-beta" in result["recipients"]
    assert "agent-alpha" not in result["recipients"]

    with tenant_session_context(db_session, tenant):
        msg = (await db_session.execute(select(Message).where(Message.id == result["message_id"]))).scalar_one()
        assert msg.project_id is None
        assert msg.thread_id == tid
        assert msg.status == "pending"
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
        thread_id=thread["thread_id"], content="operator here", user_id=user.id, as_user=True, tenant_key=tenant
    )
    assert result["from_display_name"] == "operator_jane"


async def test_from_agent_wins_over_user_id(db_manager, db_session):
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
        user_id=user.id,
        tenant_key=tenant,
    )
    assert result["from_agent_id"] == "implementer"
    assert result["from_display_name"] == "implementer"
    assert result["from_agent_id"] != user.id


async def test_from_agent_length_cap_raises_validation(db_manager, db_session):
    tenant = _tk("cap")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="a", tenant_key=tenant)
    with pytest.raises(ValidationError):
        await svc.post_to_thread(thread_id=thread["thread_id"], content="x", from_agent="a" * 65, tenant_key=tenant)


async def test_from_agent_resolves_display_name_from_participant(db_manager, db_session):
    tenant = _tk("resolve")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="hub badge", creator_id="orchestrator", tenant_key=tenant)
    tid = thread["thread_id"]
    agent_uuid = "aeaeb3eb-ea5c-4c1a-9b1a-000000000001"
    await svc.join_thread(thread_id=tid, participant_id=agent_uuid, display_name="orchestrator", tenant_key=tenant)

    result = await svc.post_to_thread(thread_id=tid, content="status update", from_agent=agent_uuid, tenant_key=tenant)

    assert result["from_display_name"] == "orchestrator"
    assert result["from_agent_id"] == agent_uuid

    with tenant_session_context(db_session, tenant):
        msg = (await db_session.execute(select(Message).where(Message.id == result["message_id"]))).scalar_one()
        assert msg.from_display_name == "orchestrator"
        assert msg.from_agent_id == agent_uuid


async def test_from_agent_falls_back_when_not_a_participant(db_manager, db_session):
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




async def test_be9037_from_agent_control_chars_are_stripped(db_manager, db_session):
    tenant = _tk("be9037_strip")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="BE-9037", tenant_key=tenant)
    result = await svc.post_to_thread(
        thread_id=thread["thread_id"], content="hi", from_agent="BE-9037\u200b\x00\ufeff", tenant_key=tenant
    )
    assert result["from_agent_id"] == "BE-9037"


async def test_be9037_all_garbage_from_agent_is_rejected(db_manager, db_session):
    tenant = _tk("be9037_garbage")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="a", tenant_key=tenant)
    with pytest.raises(ValidationError):
        await svc.post_to_thread(
            thread_id=thread["thread_id"], content="x", from_agent="\u200b\x00\ufeff", tenant_key=tenant
        )


async def test_be9379_user_attribution_is_explicit_never_the_omission_default(db_manager, db_session):
    tenant = _tk("be9379_explicit")
    await _seed(db_session, tenant)
    user = User(tenant_key=tenant, username="operator_kim")
    db_session.add(user)
    await db_session.flush()
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="a", tenant_key=tenant)

    with pytest.raises(ValidationError, match="from_agent"):
        await svc.post_to_thread(thread_id=thread["thread_id"], content="hi", user_id=user.id, tenant_key=tenant)

    as_user = await svc.post_to_thread(
        thread_id=thread["thread_id"], content="me", user_id=user.id, as_user=True, tenant_key=tenant
    )
    assert as_user["attribution_warning"] is None
    assert as_user["from_agent_id"] == user.id
    assert as_user["from_kind"] == "user"

    supplied = await svc.post_to_thread(
        thread_id=thread["thread_id"], content="yo", from_agent="tester", user_id=user.id, tenant_key=tenant
    )
    assert supplied["attribution_warning"] is None
    assert supplied["from_agent_id"] == "tester"

    with pytest.raises(ValidationError):
        await svc.post_to_thread(
            thread_id=thread["thread_id"],
            content="both",
            from_agent="tester",
            user_id=user.id,
            as_user=True,
            tenant_key=tenant,
        )


async def test_be9037_ad_hoc_lane_id_posts_and_batons(db_manager, db_session):
    tenant = _tk("be9037_lane")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="op", creator_id="BE-9037", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="SEC-3001b", tenant_key=tenant)

    result = await svc.post_to_thread(thread_id=tid, content="status", from_agent="BE-9037", tenant_key=tenant)
    assert result["from_agent_id"] == "BE-9037"
    assert "SEC-3001b" in result["recipients"]
    assert "BE-9037" not in result["recipients"]

    mine = await svc.get_my_turn(agent_id="BE-9037", tenant_key=tenant)
    assert tid in {t["thread_id"] for t in mine["threads"]}
    handoff = await svc.pass_baton(thread_id=tid, to="SEC-3001b", tenant_key=tenant)
    assert handoff["next_action_owner"] == "SEC-3001b"




async def _seed_product(db_session, tenant: str, *, is_active: bool = True, is_default: bool = False) -> str:
    with tenant_session_context(db_session, tenant):
        product = Product(
            tenant_key=tenant,
            name=f"FE-9530 create_thread product {tenant}",
            description="seeded",
            is_active=is_active,
            is_default=is_default,
        )
        db_session.add(product)
        await db_session.flush()
    return product.id


async def _seed_sequence_run(db_session, tenant: str) -> str:
    with tenant_session_context(db_session, tenant):
        run = SequenceRun(
            tenant_key=tenant,
            project_ids=[],
            resolved_order=[],
            execution_mode="multi_terminal",
        )
        db_session.add(run)
        await db_session.flush()
    return run.id


async def test_create_thread_on_a_zero_product_tenant_stays_product_less(db_manager, db_session):
    tenant = _tk("fe9530_noproduct")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="first ever thread", creator_id="agent-a", tenant_key=tenant)

    assert thread["product_id"] is None


async def test_create_thread_with_a_single_product_resolves_silently(db_manager, db_session):
    tenant = _tk("fe9530_oneproduct")
    await _seed(db_session, tenant)
    product_id = await _seed_product(db_session, tenant, is_active=True)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="sole product", creator_id="agent-a", tenant_key=tenant)

    assert thread["product_id"] == product_id


async def test_create_thread_with_multiple_products_and_none_named_is_ambiguous(db_manager, db_session):
    tenant = _tk("fe9530_ambiguous")
    await _seed(db_session, tenant)
    await _seed_product(db_session, tenant, is_active=True)
    await _seed_product(db_session, tenant, is_active=True)
    svc = _service(db_manager, db_session)

    with pytest.raises(ProductAmbiguousError):
        await svc.create_thread(subject="which one", creator_id="agent-a", tenant_key=tenant)


async def test_chain_conductor_create_is_exempt_from_mandatory_resolution(db_manager, db_session):
    tenant = _tk("fe9530_conductor")
    await _seed(db_session, tenant)
    await _seed_product(db_session, tenant, is_active=True)
    await _seed_product(db_session, tenant, is_active=True)
    run_id = await _seed_sequence_run(db_session, tenant)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="Chain: hub", sequence_run_id=run_id, tenant_key=tenant)

    assert thread["product_id"] is None
    assert thread["sequence_run_id"] == run_id


async def test_create_thread_with_explicit_product_id_is_never_overridden(db_manager, db_session):
    tenant = _tk("fe9530_explicit")
    await _seed(db_session, tenant)
    product_a = await _seed_product(db_session, tenant, is_active=True)
    product_b = await _seed_product(db_session, tenant, is_active=True)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="explicit", creator_id="agent-a", product_id=product_b, tenant_key=tenant)

    assert thread["product_id"] == product_b
    assert thread["product_id"] != product_a


async def test_create_thread_with_project_id_derives_product_from_the_project(db_manager, db_session):
    tenant = _tk("fe9530_derive")
    await _seed(db_session, tenant)
    project_product = await _seed_product(db_session, tenant, is_active=False)
    decoy_product = await _seed_product(db_session, tenant, is_active=True, is_default=True)
    with tenant_session_context(db_session, tenant):
        project = Project(
            name="FE-9530 derive project",
            description="d",
            mission="m",
            status="active",
            tenant_key=tenant,
            product_id=project_product,
            series_number=1,
            execution_mode="claude_code_cli",
        )
        db_session.add(project)
        await db_session.flush()
        project_id = project.id
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="bound", creator_id="agent-a", project_id=project_id, tenant_key=tenant)

    assert thread["product_id"] == project_product
    assert thread["product_id"] != decoy_product




async def _seed_sequence_run_with_head_project(db_session, tenant: str, head_project_id: str) -> str:
    with tenant_session_context(db_session, tenant):
        run = SequenceRun(
            tenant_key=tenant,
            project_ids=[head_project_id],
            resolved_order=[head_project_id],
            execution_mode="multi_terminal",
        )
        db_session.add(run)
        await db_session.flush()
    return run.id


async def test_chain_conductor_create_derives_product_from_the_runs_head_project(db_manager, db_session):
    tenant = _tk("be9537_head_project")
    await _seed(db_session, tenant)
    head_product = await _seed_product(db_session, tenant, is_active=True)
    decoy_product = await _seed_product(db_session, tenant, is_active=True, is_default=True)
    with tenant_session_context(db_session, tenant):
        head_project = Project(
            name="BE-9537 head project",
            description="d",
            mission="m",
            status="active",
            tenant_key=tenant,
            product_id=head_product,
            series_number=1,
            execution_mode="claude_code_cli",
        )
        db_session.add(head_project)
        await db_session.flush()
        head_project_id = head_project.id
    run_id = await _seed_sequence_run_with_head_project(db_session, tenant, head_project_id)
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="Chain: hub", sequence_run_id=run_id, tenant_key=tenant)

    assert thread["product_id"] == head_product
    assert thread["product_id"] != decoy_product
    assert thread["sequence_run_id"] == run_id


async def test_chain_conductor_create_stays_untagged_when_head_project_is_unresolvable(db_manager, db_session):
    tenant = _tk("be9537_purged_head")
    await _seed(db_session, tenant)
    await _seed_product(db_session, tenant, is_active=True)
    run_id = await _seed_sequence_run_with_head_project(db_session, tenant, "nonexistent-purged-project-id")
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="Chain: hub", sequence_run_id=run_id, tenant_key=tenant)

    assert thread["product_id"] is None
    assert thread["sequence_run_id"] == run_id
