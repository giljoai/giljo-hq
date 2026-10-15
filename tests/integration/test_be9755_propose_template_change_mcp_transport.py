# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate, Product
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

TOOL = "propose_template_change"


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(result.content[0].text)


def _error_text(result) -> str:
    return "\n".join(getattr(block, "text", "") or "" for block in result.content)


async def _seed(db_session, tenant_key: str) -> dict:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(id=str(uuid.uuid4()), name=f"Shop {suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(product)
    await db_session.flush()
    first = AgentTemplate(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"implementer-{suffix}",
        role="implementer",
        system_instructions="bootstrap",
        user_instructions="Original implementer text.",
    )
    second = AgentTemplate(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"tester-{suffix}",
        role="tester",
        system_instructions="bootstrap",
        user_instructions="Original tester text.",
    )
    db_session.add_all([first, second])
    await db_session.commit()
    return {
        "product": _Ref(product.id, product.name),
        "first": _Ref(first.id, first.name),
        "second": _Ref(second.id, second.name),
    }


class _Ref:
    def __init__(self, id_: str, name: str):
        self.id = id_
        self.name = name


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )

    switch = _TenantSwitch(TenantManager.generate_tenant_key())
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), switch
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _propose(new_client, **args) -> dict:
    async with new_client() as session:
        result = await session.call_tool(TOOL, args)
    assert result.is_error is False, _error_text(result)
    return _payload(result)


async def _slots(db_session, tenant_key: str) -> list:
    from giljo_mcp.models.template_proposals import TemplateProposal

    db_session.expire_all()
    with tenant_session_context(db_session, tenant_key):
        rows = await db_session.execute(select(TemplateProposal).where(TemplateProposal.tenant_key == tenant_key))
        found = list(rows.scalars().all())
        for row in found:
            db_session.expunge(row)
    return found


async def _live_text(db_session, tenant_key: str, template_id: str) -> str:
    db_session.expire_all()
    stmt = select(AgentTemplate.user_instructions).where(
        AgentTemplate.id == template_id, AgentTemplate.tenant_key == tenant_key
    )
    with tenant_session_context(db_session, tenant_key):
        return (await db_session.execute(stmt)).scalar_one()


async def test_propose_fills_the_slot_and_leaves_the_live_template_unchanged(mcp_client, db_session):
    new_client, switch = mcp_client
    seed = await _seed(db_session, switch.value)
    first = seed["first"]

    payload = await _propose(
        new_client,
        target_kind="agent_template",
        template_id_or_name=first.id,
        proposed_text="Proposed implementer text.",
        reason="Mention the new test command.",
    )

    assert payload["proposal_id"]
    assert payload["replaced"] is None
    tell = payload["tell_the_user"]
    assert first.name in tell
    assert "Tools > Agents" in tell
    assert first.id not in tell and switch.value not in tell, "tell_the_user must carry no internal ids"

    assert await _live_text(db_session, switch.value, first.id) == "Original implementer text."
    slots = await _slots(db_session, switch.value)
    assert [(s.template_id, s.proposed_text) for s in slots] == [(first.id, "Proposed implementer text.")]
    assert slots[0].id == payload["proposal_id"]


async def test_second_propose_on_same_template_replaces_and_names_the_first(mcp_client, db_session):
    new_client, switch = mcp_client
    seed = await _seed(db_session, switch.value)
    first = seed["first"]

    earlier = await _propose(
        new_client,
        target_kind="agent_template",
        template_id_or_name=first.name,
        proposed_text="Draft one.",
        reason="First idea.",
    )
    later = await _propose(
        new_client,
        target_kind="agent_template",
        template_id_or_name=first.name,
        proposed_text="Draft two.",
        reason="Better idea.",
    )

    assert later["replaced"] is not None
    assert later["replaced"]["reason"] == "First idea."
    assert later["replaced"]["saved_at"]
    assert later["proposal_id"] != earlier["proposal_id"]
    assert "replaces" in later["tell_the_user"]
    assert "First idea." in later["tell_the_user"]
    assert later["tell_the_user"].endswith("First idea."), later["tell_the_user"]

    slots = await _slots(db_session, switch.value)
    assert len(slots) == 1
    assert slots[0].proposed_text == "Draft two."
    assert slots[0].replaced_note and "First idea." in slots[0].replaced_note
    assert await _live_text(db_session, switch.value, first.id) == "Original implementer text."


async def test_propose_on_a_different_template_leaves_the_first_untouched(mcp_client, db_session):
    new_client, switch = mcp_client
    seed = await _seed(db_session, switch.value)
    first, second = seed["first"], seed["second"]

    a = await _propose(
        new_client,
        target_kind="agent_template",
        template_id_or_name=first.id,
        proposed_text="Implementer draft.",
        reason="Implementer reason.",
    )
    b = await _propose(
        new_client,
        target_kind="agent_template",
        template_id_or_name=second.id,
        proposed_text="Tester draft.",
        reason="Tester reason.",
    )

    assert b["replaced"] is None
    slots = {s.template_id: s for s in await _slots(db_session, switch.value)}
    assert set(slots) == {first.id, second.id}
    assert slots[first.id].id == a["proposal_id"]
    assert slots[first.id].proposed_text == "Implementer draft."
    assert slots[second.id].proposed_text == "Tester draft."


async def test_additions_proposal_fills_the_products_slot(mcp_client, db_session):
    new_client, switch = mcp_client
    seed = await _seed(db_session, switch.value)
    product = seed["product"]

    proposed = await _propose(
        new_client,
        target_kind="orchestrator_additions",
        rung="product",
        product_id=product.id,
        proposed_text="Always run the linter.",
        reason="Lint misses.",
    )

    assert proposed["replaced"] is None
    assert product.name in proposed["tell_the_user"]
    [slot] = await _slots(db_session, switch.value)
    assert (slot.rung, slot.product_id) == ("product", product.id)


@pytest.mark.parametrize("product_id", ["", "present"])
async def test_the_account_wide_rung_is_refused_through_the_transport(mcp_client, db_session, product_id):
    new_client, switch = mcp_client
    seed = await _seed(db_session, switch.value)
    args = {
        "target_kind": "orchestrator_additions",
        "rung": "tenant",
        "proposed_text": "Prefer small PRs.",
        "reason": "Review load.",
    }
    if product_id:
        args["product_id"] = seed["product"].id

    async with new_client() as session:
        result = await session.call_tool(TOOL, args)

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"] == "VALIDATION_ERROR"
    assert payload["field"] == "rung"
    assert "per product" in payload["message"]
    assert await _slots(db_session, switch.value) == []


@pytest.mark.parametrize(
    ("args", "field"),
    [
        ({"target_kind": "agent_template", "proposed_text": "x", "reason": "   "}, "reason"),
        ({"target_kind": "agent_template", "proposed_text": "  ", "reason": "r"}, "proposed_text"),
        ({"target_kind": "agent_template", "proposed_text": "x", "reason": "r"}, "template_id_or_name"),
        ({"target_kind": "orchestrator_additions", "proposed_text": "x", "reason": "r"}, "rung"),
        (
            {"target_kind": "orchestrator_additions", "rung": "product", "proposed_text": "x", "reason": "r"},
            "product_id",
        ),
        ({"target_kind": "nonsense", "proposed_text": "x", "reason": "r"}, "target_kind"),
        ({"target_kind": "agent_template", "proposed_text": "x" * (50 * 1024 + 1), "reason": "r"}, "proposed_text"),
    ],
)
async def test_bad_arguments_are_refused_before_anything_is_written(mcp_client, db_session, args, field):
    new_client, switch = mcp_client
    seed = await _seed(db_session, switch.value)
    if field == "proposed_text" and len(args["proposed_text"]) > 10:
        args = {**args, "template_id_or_name": seed["first"].id}

    async with new_client() as session:
        result = await session.call_tool(TOOL, args)

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"] == "VALIDATION_ERROR"
    assert payload["field"] == field
    assert await _slots(db_session, switch.value) == []


async def test_another_tenants_template_and_product_are_refused(mcp_client, db_session):
    new_client, switch = mcp_client
    owner = switch.value
    seed = await _seed(db_session, owner)

    switch.value = TenantManager.generate_tenant_key()
    await _seed(db_session, switch.value)

    for args in (
        {"target_kind": "agent_template", "template_id_or_name": seed["first"].id},
        {"target_kind": "agent_template", "template_id_or_name": seed["first"].name},
        {"target_kind": "orchestrator_additions", "rung": "product", "product_id": seed["product"].id},
    ):
        async with new_client() as session:
            result = await session.call_tool(TOOL, {**args, "proposed_text": "steal", "reason": "r"})
        payload = _payload(result)
        assert payload.get("error") == "VALIDATION_ERROR", payload
        assert owner not in json.dumps(payload)

    assert await _slots(db_session, owner) == []
    assert await _slots(db_session, switch.value) == []
