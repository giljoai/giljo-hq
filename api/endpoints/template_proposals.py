# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.endpoints._boundary_types import IdPath
from giljo_mcp.auth.dependencies import get_current_active_user, require_admin
from giljo_mcp.exceptions import AuthorizationError, ResourceNotFoundError, TemplateNotFoundError
from giljo_mcp.models import User
from giljo_mcp.services.template_proposal_service import TARGET_AGENT_TEMPLATE, TemplateProposalService
from giljo_mcp.services.template_service import TemplateService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

router = APIRouter()


class TemplateProposalItem(BaseModel):
    """One waiting proposal, with the text it would replace."""

    id: str
    target_kind: Literal["agent_template", "orchestrator_additions"]
    template_id: str | None = Field(None, description="The agent template, for an agent_template proposal")
    template_name: str | None = None
    product_id: str | None = Field(None, description="The template's product, or the product rung")
    product_name: str | None = None
    rung: Literal["product", "tenant"] | None = Field(None, description="Which additions rung, for additions")
    current_text: str = Field(..., description="The text in use now")
    proposed_text: str = Field(..., description="The full text the agent proposes")
    reason: str
    proposed_by: str | None = None
    created_at: str | None = None
    replaced_note: str | None = Field(None, description="Set when this proposal replaced an older one")


class TemplateProposalList(BaseModel):
    """Every proposal waiting for you."""

    count: int
    proposals: list[TemplateProposalItem]


class TemplateProposalCount(BaseModel):
    """How many proposals are waiting for you."""

    count: int


class TemplateProposalApplied(BaseModel):
    """The proposal was applied and its slot cleared."""

    applied: bool = True
    target_kind: Literal["agent_template", "orchestrator_additions"]
    template_id: str | None = None
    rung: Literal["product", "tenant"] | None = None
    applied_by: str


class TemplateProposalRejected(BaseModel):
    """The proposal was discarded; the template is unchanged."""

    rejected: bool = True


def _service() -> TemplateProposalService:
    from api.app_state import state

    return TemplateProposalService(state.db_manager, system_prompt_service=state.system_prompt_service)


def _is_admin(user: User) -> bool:
    return user.role == "admin"


async def _reviewable(service: TemplateProposalService, user: User, proposal_id: str):
    try:
        proposal = await service.get(tenant_key=user.tenant_key, proposal_id=proposal_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Proposal not found") from exc
    if proposal.target_kind != TARGET_AGENT_TEMPLATE:
        await require_admin(user)
    return proposal


@router.get("", response_model=TemplateProposalList)
async def list_template_proposals(current_user: User = Depends(get_current_active_user)) -> TemplateProposalList:
    """List the template changes agents have proposed, each with its current and proposed text."""
    proposals = await _service().list_proposals(
        tenant_key=current_user.tenant_key, include_additions=_is_admin(current_user)
    )
    return TemplateProposalList(count=len(proposals), proposals=proposals)


@router.get("/count", response_model=TemplateProposalCount)
async def count_template_proposals(current_user: User = Depends(get_current_active_user)) -> TemplateProposalCount:
    """Return how many proposed template changes are waiting for you."""
    count = await _service().count(tenant_key=current_user.tenant_key, include_additions=_is_admin(current_user))
    return TemplateProposalCount(count=count)


@router.post("/{proposal_id}/apply", response_model=TemplateProposalApplied, response_model_exclude_none=True)
async def apply_template_proposal(
    proposal_id: IdPath, current_user: User = Depends(get_current_active_user)
) -> TemplateProposalApplied:
    """Apply a proposed change: the template or prompt takes the proposed text, and the proposal is cleared."""
    from api.app_state import state

    service = _service()
    await _reviewable(service, current_user, proposal_id)
    template_service = TemplateService(db_manager=state.db_manager, tenant_manager=state.tenant_manager)
    try:
        result = await service.apply(
            tenant_key=current_user.tenant_key,
            proposal_id=proposal_id,
            username=current_user.username,
            template_service=template_service,
        )
    except (ResourceNotFoundError, TemplateNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Proposal not found") from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid prompt content.") from exc

    logger.info("Applied template proposal %s", sanitize(proposal_id))
    return TemplateProposalApplied(**result)


@router.post("/{proposal_id}/reject", response_model=TemplateProposalRejected)
async def reject_template_proposal(
    proposal_id: IdPath, current_user: User = Depends(get_current_active_user)
) -> TemplateProposalRejected:
    """Reject a proposed change: the proposal is discarded and nothing else changes."""
    service = _service()
    await _reviewable(service, current_user, proposal_id)
    try:
        await service.reject(tenant_key=current_user.tenant_key, proposal_id=proposal_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Proposal not found") from exc
    return TemplateProposalRejected()
