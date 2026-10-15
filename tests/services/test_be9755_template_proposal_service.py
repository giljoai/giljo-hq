# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from api.endpoints.templates.models import MAX_USER_INSTRUCTIONS_SIZE
from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import AgentTemplate, Configuration, Product
from giljo_mcp.models.template_proposals import TemplateProposal
from giljo_mcp.models.templates import TemplateArchive
from giljo_mcp.services.template_proposal_service import (
    TEMPLATE_TEXT_MAX_BYTES,
    ProposalRefusedError,
    TemplateProposalService,
)
from giljo_mcp.services.template_service import TemplateService
from giljo_mcp.system_prompts.service import SystemPromptService, product_orchestrator_config_key
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _seed(db_session, tenant_key: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    product_id = str(uuid.uuid4())
    db_session.add(Product(id=product_id, name=f"Shop {suffix}", tenant_key=tenant_key, is_active=True))
    await db_session.flush()
    ids = {"product": product_id}
    for key, role in (("first", "implementer"), ("second", "tester")):
        template_id = str(uuid.uuid4())
        db_session.add(
            AgentTemplate(
                id=template_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name=f"{role}-{suffix}",
                role=role,
                system_instructions="bootstrap",
                user_instructions=f"Original {role} text.",
            )
        )
        ids[key] = template_id
    await db_session.commit()
    return ids


def _service(db_manager, db_session) -> TemplateProposalService:
    return TemplateProposalService(db_manager, session=db_session)


async def _rows(db_session, tenant_key: str, model, *criteria) -> list:
    db_session.expire_all()
    with tenant_session_context(db_session, tenant_key):
        found = list((await db_session.execute(select(model).where(*criteria))).scalars().all())
        for row in found:
            db_session.expunge(row)
    return found


async def _propose_template(service, tenant_key, template_id, text="Proposed text.", reason="Because."):
    return await service.propose(
        tenant_key=tenant_key,
        target_kind="agent_template",
        template_id_or_name=template_id,
        proposed_text=text,
        reason=reason,
    )


async def test_template_cap_matches_the_editor_cap():
    assert TEMPLATE_TEXT_MAX_BYTES == MAX_USER_INSTRUCTIONS_SIZE


async def test_apply_template_writes_through_the_owning_writer_and_records_who(db_manager, db_session, monkeypatch):
    tenant = TenantManager.generate_tenant_key()
    ids = await _seed(db_session, tenant)
    service = _service(db_manager, db_session)
    proposal = await _propose_template(service, tenant, ids["first"], text="Applied text.")

    template_service = TemplateService(db_manager, TenantManager(), session=db_session)
    calls = []
    real_writer = template_service.update_template_from_request

    async def spy(*args, **kwargs):
        calls.append(args)
        return await real_writer(*args, **kwargs)

    monkeypatch.setattr(template_service, "update_template_from_request", spy)

    result = await service.apply(
        tenant_key=tenant, proposal_id=proposal["proposal_id"], username="alice", template_service=template_service
    )

    assert result == {
        "applied": True,
        "target_kind": "agent_template",
        "template_id": ids["first"],
        "applied_by": "alice",
    }
    assert len(calls) == 1
    [template] = await _rows(db_session, tenant, AgentTemplate, AgentTemplate.id == ids["first"])
    assert template.user_instructions == "Applied text."
    [archive] = await _rows(db_session, tenant, TemplateArchive, TemplateArchive.template_id == ids["first"])
    assert archive.archived_by == "alice"
    assert archive.user_instructions == "Original implementer text."
    assert await _rows(db_session, tenant, TemplateProposal, TemplateProposal.tenant_key == tenant) == []


async def test_apply_additions_writes_through_the_system_prompt_service(db_manager, db_session, monkeypatch):
    tenant = TenantManager.generate_tenant_key()
    ids = await _seed(db_session, tenant)
    prompts = SystemPromptService(db_manager)
    service = TemplateProposalService(db_manager, session=db_session, system_prompt_service=prompts)
    proposal = await service.propose(
        tenant_key=tenant,
        target_kind="orchestrator_additions",
        rung="product",
        product_id=ids["product"],
        proposed_text="Always lint.",
        reason="Lint misses.",
    )
    calls = []
    real_writer = prompts.update_orchestrator_additions

    async def spy(**kwargs):
        calls.append(kwargs)
        return await real_writer(**kwargs)

    monkeypatch.setattr(prompts, "update_orchestrator_additions", spy)

    result = await service.apply(
        tenant_key=tenant, proposal_id=proposal["proposal_id"], username="bob", template_service=None
    )

    assert result == {"applied": True, "target_kind": "orchestrator_additions", "rung": "product", "applied_by": "bob"}
    assert len(calls) == 1 and calls[0]["product_id"] == ids["product"]
    assert (
        await prompts.read_rung_additions(tenant_key=tenant, product_id=ids["product"], session=db_session)
        == "Always lint."
    )
    db_session.expire_all()
    stored = (
        await db_session.execute(
            select(Configuration.value).where(
                Configuration.tenant_key == tenant, Configuration.key == product_orchestrator_config_key(ids["product"])
            )
        )
    ).scalar_one()
    assert stored["updated_by"] == "bob"
    assert await _rows(db_session, tenant, TemplateProposal, TemplateProposal.tenant_key == tenant) == []


async def test_reject_clears_only_its_own_slot(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    ids = await _seed(db_session, tenant)
    service = _service(db_manager, db_session)
    first = await _propose_template(service, tenant, ids["first"])
    second = await _propose_template(service, tenant, ids["second"])

    await service.reject(tenant_key=tenant, proposal_id=first["proposal_id"])

    remaining = await _rows(db_session, tenant, TemplateProposal, TemplateProposal.tenant_key == tenant)
    assert [row.id for row in remaining] == [second["proposal_id"]]
    [template] = await _rows(db_session, tenant, AgentTemplate, AgentTemplate.id == ids["first"])
    assert template.user_instructions == "Original implementer text."


async def test_list_and_count_show_current_and_proposed_text(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    ids = await _seed(db_session, tenant)
    service = _service(db_manager, db_session)
    await _propose_template(service, tenant, ids["first"], text="New implementer text.")
    await service.propose(
        tenant_key=tenant,
        target_kind="orchestrator_additions",
        rung="product",
        product_id=ids["product"],
        proposed_text="Add.",
        reason="r",
    )

    members = await service.list_proposals(tenant_key=tenant, include_additions=False)
    admins = await service.list_proposals(tenant_key=tenant, include_additions=True)

    assert [p["target_kind"] for p in members] == ["agent_template"]
    assert members[0]["current_text"] == "Original implementer text."
    assert members[0]["proposed_text"] == "New implementer text."
    assert members[0]["product_name"].startswith("Shop ")
    assert sorted(p["target_kind"] for p in admins) == ["agent_template", "orchestrator_additions"]
    assert await service.count(tenant_key=tenant, include_additions=False) == 1
    assert await service.count(tenant_key=tenant, include_additions=True) == 2


async def test_another_tenant_cannot_read_apply_or_reject(db_manager, db_session):
    owner = TenantManager.generate_tenant_key()
    stranger = TenantManager.generate_tenant_key()
    ids = await _seed(db_session, owner)
    await _seed(db_session, stranger)
    service = _service(db_manager, db_session)
    proposal = await _propose_template(service, owner, ids["first"])

    assert await service.list_proposals(tenant_key=stranger, include_additions=True) == []
    assert await service.count(tenant_key=stranger, include_additions=True) == 0
    with pytest.raises(ResourceNotFoundError):
        await service.get(tenant_key=stranger, proposal_id=proposal["proposal_id"])
    with pytest.raises(ResourceNotFoundError):
        await service.reject(tenant_key=stranger, proposal_id=proposal["proposal_id"])
    with pytest.raises(ResourceNotFoundError):
        await service.apply(
            tenant_key=stranger,
            proposal_id=proposal["proposal_id"],
            username="mallory",
            template_service=TemplateService(db_manager, TenantManager(), session=db_session),
        )
    assert len(await _rows(db_session, owner, TemplateProposal, TemplateProposal.tenant_key == owner)) == 1


async def test_products_the_caller_does_not_own_are_refused(db_manager, db_session):
    owner = TenantManager.generate_tenant_key()
    stranger = TenantManager.generate_tenant_key()
    ids = await _seed(db_session, owner)
    stranger_ids = await _seed(db_session, stranger)
    service = _service(db_manager, db_session)

    with pytest.raises(ProposalRefusedError) as foreign_rung:
        await service.propose(
            tenant_key=stranger,
            target_kind="orchestrator_additions",
            rung="product",
            product_id=ids["product"],
            proposed_text="x",
            reason="r",
        )
    assert foreign_rung.value.field == "product_id"

    with pytest.raises(ProposalRefusedError) as wrong_product:
        await service.propose(
            tenant_key=owner,
            target_kind="agent_template",
            template_id_or_name=ids["first"],
            product_id=stranger_ids["product"],
            proposed_text="x",
            reason="r",
        )
    assert wrong_product.value.constraint == "not_found"


async def test_system_managed_template_is_refused(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    ids = await _seed(db_session, tenant)
    orchestrator_id = str(uuid.uuid4())
    db_session.add(
        AgentTemplate(
            id=orchestrator_id,
            tenant_key=tenant,
            product_id=ids["product"],
            name=f"orchestrator-{uuid.uuid4().hex[:6]}",
            role="orchestrator",
            system_instructions="bootstrap",
        )
    )
    await db_session.commit()

    with pytest.raises(ProposalRefusedError) as refused:
        await _propose_template(_service(db_manager, db_session), tenant, orchestrator_id)
    assert refused.value.constraint == "system_managed"


async def test_the_account_wide_rung_is_refused_and_writes_nothing(db_manager, db_session):
    tenant = TenantManager.generate_tenant_key()
    ids = await _seed(db_session, tenant)
    service = _service(db_manager, db_session)

    for product_id in ("", ids["product"]):
        with pytest.raises(ProposalRefusedError) as refused:
            await service.propose(
                tenant_key=tenant,
                target_kind="orchestrator_additions",
                rung="tenant",
                product_id=product_id,
                proposed_text="Add.",
                reason="r",
            )
        assert (refused.value.field, refused.value.constraint) == ("rung", "invalid_choice")

    assert await _rows(db_session, tenant, TemplateProposal, TemplateProposal.tenant_key == tenant) == []
