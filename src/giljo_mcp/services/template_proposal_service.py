# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import AgentTemplate, Product
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.template_proposals import TemplateProposal
from giljo_mcp.services._session_helpers import tenant_scoped_session
from giljo_mcp.services.template_write_paths import require_own_product
from giljo_mcp.system_prompts.service import MAX_PROMPT_BYTES, SystemPromptService
from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES


TARGET_AGENT_TEMPLATE = "agent_template"
TARGET_ORCHESTRATOR_ADDITIONS = "orchestrator_additions"
TARGET_KINDS = (TARGET_AGENT_TEMPLATE, TARGET_ORCHESTRATOR_ADDITIONS)
RUNG_PRODUCT = "product"
RUNG_TENANT = "tenant"
RUNGS = (RUNG_PRODUCT, RUNG_TENANT)

TEMPLATE_TEXT_MAX_BYTES = 50 * 1024
ADDITIONS_TEXT_MAX_BYTES = MAX_PROMPT_BYTES
REASON_MAX_CHARS = 500
PROPOSED_BY_MAX_CHARS = 100
TEMPLATE_REF_MAX_CHARS = 100

REVIEW_HINT = "Review it in Tools > Agents and press Apply or Reject."


class ProposalRefusedError(ValidationError):

    def __init__(self, message: str, *, field: str, constraint: str):
        super().__init__(message)
        self.field = field
        self.constraint = constraint


class _InstructionsUpdate(BaseModel):
    """The one field Apply changes on an agent template, in the editor's request shape."""

    user_instructions: str


def check_proposal_arguments(
    *, target_kind: str, proposed_text: str, reason: str, template_id_or_name: str, product_id: str, rung: str
) -> None:
    if target_kind not in TARGET_KINDS:
        raise ProposalRefusedError(
            f"target_kind must be one of {', '.join(TARGET_KINDS)}.", field="target_kind", constraint="invalid_choice"
        )
    if not (proposed_text or "").strip():
        raise ProposalRefusedError("proposed_text cannot be empty.", field="proposed_text", constraint="non_empty")
    if not (reason or "").strip():
        raise ProposalRefusedError("reason cannot be empty.", field="reason", constraint="non_empty")
    if len(reason) > REASON_MAX_CHARS:
        raise ProposalRefusedError(
            f"reason must be at most {REASON_MAX_CHARS} characters.", field="reason", constraint="string_too_long"
        )
    if target_kind == TARGET_AGENT_TEMPLATE:
        _check_template_arguments(template_id_or_name, rung)
        limit = TEMPLATE_TEXT_MAX_BYTES
    else:
        _check_additions_arguments(template_id_or_name, product_id, rung)
        limit = ADDITIONS_TEXT_MAX_BYTES
    if len(proposed_text.encode("utf-8")) > limit:
        raise ProposalRefusedError(
            f"proposed_text exceeds the {limit // 1024}KB limit the editor allows.",
            field="proposed_text",
            constraint="too_large",
        )


def _check_template_arguments(template_id_or_name: str, rung: str) -> None:
    if not (template_id_or_name or "").strip():
        raise ProposalRefusedError(
            "Name the agent template: pass template_id_or_name.", field="template_id_or_name", constraint="non_empty"
        )
    if len(template_id_or_name) > TEMPLATE_REF_MAX_CHARS:
        raise ProposalRefusedError(
            f"template_id_or_name must be at most {TEMPLATE_REF_MAX_CHARS} characters.",
            field="template_id_or_name",
            constraint="string_too_long",
        )
    if rung:
        raise ProposalRefusedError(
            "rung applies only to orchestrator_additions; omit it.", field="rung", constraint="not_applicable"
        )


def _check_additions_arguments(template_id_or_name: str, product_id: str, rung: str) -> None:
    if template_id_or_name:
        raise ProposalRefusedError(
            "template_id_or_name applies only to agent_template; omit it.",
            field="template_id_or_name",
            constraint="not_applicable",
        )
    if rung == RUNG_TENANT:
        raise ProposalRefusedError(
            "Orchestrator prompt additions are set per product, not for the whole account. "
            "Use rung='product' with that product's product_id.",
            field="rung",
            constraint="invalid_choice",
        )
    if rung != RUNG_PRODUCT:
        raise ProposalRefusedError(
            f"rung is required for orchestrator_additions: {RUNG_PRODUCT}.",
            field="rung",
            constraint="invalid_choice",
        )
    if not product_id:
        raise ProposalRefusedError("The product rung needs product_id.", field="product_id", constraint="non_empty")


def _slot_key(target_kind: str, template_id: str | None, product_id: str | None) -> str:
    if target_kind == TARGET_AGENT_TEMPLATE:
        return f"{TARGET_AGENT_TEMPLATE}:{template_id}"
    return f"{TARGET_ORCHESTRATOR_ADDITIONS}:{RUNG_PRODUCT}:{product_id}"


def replaced_sentence(saved_at: datetime, reason: str) -> str:
    reason = (reason or "").strip()
    end = "" if reason.endswith((".", "!", "?")) else "."
    return f" It replaces the waiting proposal saved {saved_at:%Y-%m-%d}, whose reason was: {reason}{end}"


def _replaced_note(saved_at: datetime, reason: str) -> str:
    return f"Replaced a proposal saved {saved_at:%Y-%m-%d %H:%M} UTC: {reason}"


class TemplateProposalService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        session: AsyncSession | None = None,
        system_prompt_service: SystemPromptService | None = None,
    ):
        self.db_manager = db_manager
        self._session = session
        self._system_prompts = system_prompt_service or SystemPromptService(db_manager)

    @asynccontextmanager
    async def _scope(self, tenant_key: str):
        async with tenant_scoped_session(self.db_manager, tenant_key, self._session) as session:
            yield session

    async def propose(
        self,
        *,
        tenant_key: str,
        target_kind: str,
        proposed_text: str,
        reason: str,
        template_id_or_name: str = "",
        product_id: str = "",
        rung: str = "",
        proposed_by: str | None = None,
    ) -> dict[str, Any]:
        check_proposal_arguments(
            target_kind=target_kind,
            proposed_text=proposed_text,
            reason=reason,
            template_id_or_name=template_id_or_name,
            product_id=product_id,
            rung=rung,
        )
        async with self._scope(tenant_key) as session:
            if target_kind == TARGET_AGENT_TEMPLATE:
                template = await self._resolve_template(session, tenant_key, template_id_or_name.strip(), product_id)
                template_id, slot_product, slot_rung = template.id, template.product_id, None
                subject = f"the {template.name} agent template"
            else:
                await self._require_product(session, tenant_key, product_id)
                template_id, slot_product, slot_rung = None, product_id, rung
                subject = "the orchestrator prompt additions"
            product_name = await self._product_name(session, tenant_key, slot_product)

            replaced = await self._fill_slot(
                session,
                tenant_key=tenant_key,
                values={
                    "target_kind": target_kind,
                    "slot_key": _slot_key(target_kind, template_id, slot_product),
                    "template_id": template_id,
                    "product_id": slot_product,
                    "rung": slot_rung,
                    "proposed_text": proposed_text,
                    "reason": reason.strip(),
                    "proposed_by": (proposed_by or "")[:PROPOSED_BY_MAX_CHARS] or None,
                },
            )
            proposal_id = replaced.pop("proposal_id")
            await session.commit()

        scope = f" for {product_name}" if product_name else " for your whole account"
        tell = f"Tell the user: I proposed a change to {subject}{scope}. {REVIEW_HINT}"
        if replaced["saved_at"] is not None:
            tell += replaced_sentence(replaced["saved_at"], replaced["reason"])
            replaced_out: dict[str, Any] | None = {
                "saved_at": replaced["saved_at"].isoformat(),
                "reason": replaced["reason"],
            }
        else:
            replaced_out = None
        return {"proposal_id": proposal_id, "replaced": replaced_out, "tell_the_user": tell}

    async def _fill_slot(self, session: AsyncSession, *, tenant_key: str, values: dict[str, Any]) -> dict[str, Any]:
        for _attempt in range(3):
            existing = (
                await session.execute(
                    select(TemplateProposal)
                    .where(TemplateProposal.tenant_key == tenant_key, TemplateProposal.slot_key == values["slot_key"])
                    .with_for_update()
                )
            ).scalar_one_or_none()
            new_id = generate_uuid()
            now = datetime.now(UTC)
            if existing is not None:
                saved_at, old_reason = existing.created_at, existing.reason
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.id = new_id
                existing.created_at = now
                existing.replaced_note = _replaced_note(saved_at, old_reason)
                await session.flush()
                return {"proposal_id": new_id, "saved_at": saved_at, "reason": old_reason}
            inserted = await session.execute(
                pg_insert(TemplateProposal)
                .values(id=new_id, tenant_key=tenant_key, created_at=now, replaced_note=None, **values)
                .on_conflict_do_nothing(constraint="uq_template_proposal_tenant_slot")
                .returning(TemplateProposal.id)
            )
            if inserted.scalar_one_or_none() is not None:
                return {"proposal_id": new_id, "saved_at": None, "reason": None}
        raise ValidationError("Another proposal for this target is being saved. Please try again.")

    async def _resolve_template(
        self, session: AsyncSession, tenant_key: str, ref: str, product_id: str
    ) -> AgentTemplate:
        live = select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key, AgentTemplate.deleted_at.is_(None))
        if product_id:
            live = live.where(AgentTemplate.product_id == product_id)
        template = (await session.execute(live.where(AgentTemplate.id == ref))).scalar_one_or_none()
        if template is None:
            matches = list((await session.execute(live.where(AgentTemplate.name == ref))).scalars().all())
            if len(matches) > 1:
                raise ProposalRefusedError(
                    f"Several agent templates are named '{ref}'. Pass its id, or product_id.",
                    field="template_id_or_name",
                    constraint="ambiguous",
                )
            template = matches[0] if matches else None
        if template is None:
            raise ProposalRefusedError(
                f"No agent template '{ref}' was found for this account.",
                field="template_id_or_name",
                constraint="not_found",
            )
        if template.role in SYSTEM_MANAGED_ROLES:
            raise ProposalRefusedError(
                f"'{template.name}' is managed by the system and cannot be changed. To change the orchestrator, "
                "propose orchestrator_additions instead.",
                field="template_id_or_name",
                constraint="system_managed",
            )
        if template.product_id:
            await self._require_product(session, tenant_key, template.product_id)
        return template

    @staticmethod
    async def _require_product(session: AsyncSession, tenant_key: str, product_id: str) -> None:
        try:
            await require_own_product(session, product_id, tenant_key)
        except ValidationError as exc:
            raise ProposalRefusedError(
                "No product with that id was found for this account.", field="product_id", constraint="not_found"
            ) from exc

    @staticmethod
    async def _product_name(session: AsyncSession, tenant_key: str, product_id: str | None) -> str | None:
        if not product_id:
            return None
        return (
            await session.execute(
                select(Product.name).where(Product.id == product_id, Product.tenant_key == tenant_key)
            )
        ).scalar_one_or_none()

    def _visible(self, tenant_key: str, include_additions: bool):
        stmt = (
            select(TemplateProposal, AgentTemplate, Product.name)
            .outerjoin(
                AgentTemplate,
                (AgentTemplate.id == TemplateProposal.template_id) & (AgentTemplate.tenant_key == tenant_key),
            )
            .outerjoin(Product, (Product.id == TemplateProposal.product_id) & (Product.tenant_key == tenant_key))
            .where(TemplateProposal.tenant_key == tenant_key)
            .where((TemplateProposal.template_id.is_(None)) | AgentTemplate.deleted_at.is_(None))
            .where(TemplateProposal.product_id.is_(None) | Product.deleted_at.is_(None))
        )
        if not include_additions:
            stmt = stmt.where(TemplateProposal.target_kind == TARGET_AGENT_TEMPLATE)
        return stmt

    async def list_proposals(self, *, tenant_key: str, include_additions: bool) -> list[dict[str, Any]]:
        async with self._scope(tenant_key) as session:
            rows = (
                await session.execute(
                    self._visible(tenant_key, include_additions).order_by(TemplateProposal.created_at.desc())
                )
            ).all()
            out = []
            for proposal, template, product_name in rows:
                if template is not None:
                    current = template.user_instructions or ""
                else:
                    current = await self._system_prompts.read_rung_additions(
                        tenant_key=tenant_key, product_id=proposal.product_id, session=session
                    )
                out.append(_to_dict(proposal, template, product_name, current or ""))
        return out

    async def count(self, *, tenant_key: str, include_additions: bool) -> int:
        async with self._scope(tenant_key) as session:
            visible = self._visible(tenant_key, include_additions).subquery()
            return (await session.execute(select(func.count()).select_from(visible))).scalar_one()

    async def get(self, *, tenant_key: str, proposal_id: str) -> TemplateProposal:
        async with self._scope(tenant_key) as session:
            return await self._get(session, tenant_key, proposal_id)

    @staticmethod
    async def _get(session: AsyncSession, tenant_key: str, proposal_id: str) -> TemplateProposal:
        proposal = (
            await session.execute(
                select(TemplateProposal).where(
                    TemplateProposal.id == proposal_id, TemplateProposal.tenant_key == tenant_key
                )
            )
        ).scalar_one_or_none()
        if proposal is None:
            raise ResourceNotFoundError("Proposal not found", context={"proposal_id": proposal_id})
        return proposal

    async def apply(self, *, tenant_key: str, proposal_id: str, username: str, template_service: Any) -> dict:
        async with self._scope(tenant_key) as session:
            proposal = await self._get(session, tenant_key, proposal_id)
            kind, template_id, rung, product_id = (
                proposal.target_kind,
                proposal.template_id,
                proposal.rung,
                proposal.product_id,
            )
            text = proposal.proposed_text
            await session.delete(proposal)
            if kind == TARGET_AGENT_TEMPLATE:
                await template_service.update_template_from_request(
                    session, template_id, _InstructionsUpdate(user_instructions=text), tenant_key, username
                )
                return {"applied": True, "target_kind": kind, "template_id": template_id, "applied_by": username}
            await self._system_prompts.update_orchestrator_additions(
                tenant_key=tenant_key,
                additions=text,
                updated_by=username,
                product_id=product_id,
                session=session,
            )
            await session.commit()
            return {"applied": True, "target_kind": kind, "rung": rung, "applied_by": username}

    async def reject(self, *, tenant_key: str, proposal_id: str) -> None:
        async with self._scope(tenant_key) as session:
            await session.delete(await self._get(session, tenant_key, proposal_id))
            await session.commit()


def _to_dict(
    proposal: TemplateProposal, template: AgentTemplate | None, product_name: str | None, current_text: str
) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "target_kind": proposal.target_kind,
        "template_id": proposal.template_id,
        "template_name": template.name if template is not None else None,
        "product_id": proposal.product_id,
        "product_name": product_name,
        "rung": proposal.rung,
        "current_text": current_text,
        "proposed_text": proposal.proposed_text,
        "reason": proposal.reason,
        "proposed_by": proposal.proposed_by,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "replaced_note": proposal.replaced_note,
    }
