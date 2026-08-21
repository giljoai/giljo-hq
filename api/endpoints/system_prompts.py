# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Admin-only system prompt management endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from giljo_mcp.auth.dependencies import require_admin
from giljo_mcp.models import User


router = APIRouter()
logger = logging.getLogger(__name__)

_PRODUCT_ID_DESCRIPTION = (
    "Optional product UUID. Supplied -> the request targets that product's rung of the "
    "override ladder; omitted -> the tenant-wide rung (the pre-BE-9385d behavior)."
)


class OrchestratorPromptResponse(BaseModel):
    content: str = Field(..., description="Full orchestrator prompt content")
    is_override: bool = Field(..., description="True when an admin override is active")
    updated_at: datetime | None = Field(None, description="Override timestamp (if applicable)")
    updated_by: str | None = Field(None, description="Identifier for the admin who last updated the prompt")
    # BE-9385d: which rung of the product -> tenant -> seed ladder answered. The editor
    # needs this to say "inherited from your tenant-wide override" rather than showing
    # inherited content as though this product owned it.
    scope: str = Field("default", description="Which rung answered: product | tenant | default")
    # FE-9408: the editor cannot warn about what it cannot see. `scope` says which rung
    # WON; these say what is standing BEHIND it. A tenant-wide override governs every
    # product without one of its own, and pre-Aug-2026 saves could only be tenant-wide,
    # so a legacy row is invisible on a product screen without this.
    tenant_override_exists: bool = Field(
        default=False, description="True when a tenant-wide override row exists, regardless of which rung won"
    )
    tenant_override_updated_at: str | None = Field(
        None, description="ISO 8601 timestamp of the tenant-wide override row; null when there is none"
    )
    # The effective built-in seed. Saving text identical to it is not a no-op -- it pins
    # the account to today's text and detaches it from later seed improvements -- so the
    # editor needs the comparison value to warn before that happens.
    default_content: str = Field("", description="The effective built-in default prompt text")


class OrchestratorPromptUpdateRequest(BaseModel):
    content: str = Field(..., description="Replacement prompt content")
    product_id: str | None = Field(None, description=_PRODUCT_ID_DESCRIPTION)


def _require_tenant(current_user: User) -> str:
    """Extract tenant_key from authed user or 400. SEC-0005b: never fall back to NULL."""
    tenant_key = getattr(current_user, "tenant_key", None)
    if not tenant_key or not str(tenant_key).strip():
        raise HTTPException(
            status_code=400,
            detail="Authenticated user is missing tenant_key; cannot scope orchestrator prompt.",
        )
    return str(tenant_key)


def _to_response(
    prompt,
    *,
    tenant_row: dict | None = None,
    default_content: str = "",
) -> OrchestratorPromptResponse:
    """Map a ``PromptRecord`` onto the wire shape (BE-9385d: one mapping, three routes).

    FE-9408: ``tenant_row`` is the tenant-wide override row read independently of the
    ladder (it may exist while a product rung wins), and ``default_content`` the
    packaged seed. Both keyword-only with defaults, so the mapper still answers for a
    caller that has neither.
    """
    tenant_updated_at = (tenant_row or {}).get("updated_at")
    return OrchestratorPromptResponse(
        content=prompt.content,
        is_override=prompt.is_override,
        updated_at=prompt.updated_at,
        updated_by=prompt.updated_by,
        # getattr keeps this tolerant of a PromptRecord built before `scope` existed
        # (test doubles, pickled fixtures) rather than 500-ing on a missing attribute.
        scope=getattr(prompt, "scope", "default"),
        tenant_override_exists=tenant_row is not None,
        tenant_override_updated_at=tenant_updated_at.isoformat() if tenant_updated_at else None,
        default_content=default_content,
    )


async def _provenance_extras(service, tenant_key: str) -> dict:
    """The FE-9408 editor extras, shared by all three routes."""
    return {
        "tenant_row": await service.read_tenant_override_row(tenant_key=tenant_key),
        "default_content": service.default_orchestrator_content(),
    }


# TENANT-LEVEL
@router.get("/orchestrator-prompt", response_model=OrchestratorPromptResponse)
async def get_orchestrator_prompt(
    product_id: Annotated[str | None, Query(description=_PRODUCT_ID_DESCRIPTION)] = None,
    current_user: User = Depends(require_admin),
):
    """Return the orchestrator prompt resolved on the product -> tenant -> seed ladder."""
    # Lazy import to avoid circular dependency
    from api.app_state import state

    service = state.system_prompt_service
    if not service:
        raise HTTPException(status_code=503, detail="System prompt service not available")

    tenant_key = _require_tenant(current_user)
    try:
        prompt = await service.get_orchestrator_prompt(tenant_key=tenant_key, product_id=product_id)
    except ValueError as exc:
        # A malformed product_id is the caller's mistake, not a server fault -- 422
        # rather than the 500 an unhandled ValueError would produce.
        logger.warning("Orchestrator prompt read rejected: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(prompt, **await _provenance_extras(service, tenant_key))


# TENANT-LEVEL
@router.put("/orchestrator-prompt", response_model=OrchestratorPromptResponse)
async def update_orchestrator_prompt(
    payload: OrchestratorPromptUpdateRequest, current_user: User = Depends(require_admin)
):
    """Persist an admin override at one rung: this product's, or tenant-wide."""
    # Lazy import to avoid circular dependency
    from api.app_state import state

    service = state.system_prompt_service
    if not service:
        raise HTTPException(status_code=503, detail="System prompt service not available")

    tenant_key = _require_tenant(current_user)

    try:
        prompt = await service.update_orchestrator_prompt(
            tenant_key=tenant_key,
            content=payload.content,
            updated_by=current_user.email or current_user.username or current_user.id,
            product_id=payload.product_id,
        )
    except ValueError as exc:
        logger.warning("System prompt update validation failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid prompt content.") from exc
    except RuntimeError as exc:
        logger.exception("System prompt service error")
        raise HTTPException(status_code=503, detail="System prompt service temporarily unavailable.") from exc

    return _to_response(prompt, **await _provenance_extras(service, tenant_key))


# TENANT-LEVEL
@router.post("/orchestrator-prompt/reset", response_model=OrchestratorPromptResponse)
async def reset_orchestrator_prompt(
    product_id: Annotated[str | None, Query(description=_PRODUCT_ID_DESCRIPTION)] = None,
    current_user: User = Depends(require_admin),
):
    """Remove the override at one rung and return whatever the ladder now resolves.

    With ``product_id`` this clears that product's override so it inherits the
    tenant-wide one again; without it, it clears the tenant-wide override and leaves
    per-product overrides standing.
    """
    # Lazy import to avoid circular dependency
    from api.app_state import state

    service = state.system_prompt_service
    if not service:
        raise HTTPException(status_code=503, detail="System prompt service not available")

    tenant_key = _require_tenant(current_user)
    try:
        prompt = await service.reset_orchestrator_prompt(tenant_key=tenant_key, product_id=product_id)
    except ValueError as exc:
        logger.warning("Orchestrator prompt reset rejected: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(prompt, **await _provenance_extras(service, tenant_key))
