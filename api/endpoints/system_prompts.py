# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from giljo_mcp.auth.dependencies import require_admin
from giljo_mcp.models import User
from giljo_mcp.system_prompts.service import ProductRequiredError


router = APIRouter()
logger = logging.getLogger(__name__)

_PRODUCT_ID_DESCRIPTION = "The product UUID whose orchestrator prompt the request reads or changes."


class OrchestratorPromptResponse(BaseModel):
    """The orchestrator prompt as served, plus what was saved to produce it."""

    content: str = Field(
        ...,
        description=(
            "The effective prompt every orchestrator receives: the built-in prompt plus your additions, "
            "or a saved full replacement"
        ),
    )
    is_override: bool = Field(..., description="True when an admin override is active")
    updated_at: datetime | None = Field(None, description="Override timestamp (if applicable)")
    updated_by: str | None = Field(None, description="Identifier for the admin who last updated the prompt")
    scope: str = Field("default", description="Where the prompt came from: product (saved on the product) | default")
    default_content: str = Field("", description="The effective built-in default prompt text")
    mode: Literal["additions", "replace"] | None = Field(
        None,
        description=(
            "How the saved prompt is applied: 'additions' (added on top of the built-in prompt), "
            "'replace' (an older saved prompt that replaces the built-in one), or null when nothing is saved"
        ),
    )
    additions: str | None = Field(None, description="Your saved additions, when mode is 'additions'")


class OrchestratorPromptUpdateRequest(BaseModel):
    """Save your additions to the built-in orchestrator prompt.

    Send ``additions`` to add your own instructions on top of the built-in prompt; the
    built-in part keeps receiving updates. ``content`` saves a full replacement instead
    and is kept for older clients. Send exactly one of the two.
    """

    additions: str | None = Field(None, description="Your instructions, added on top of the built-in prompt")
    content: str | None = Field(None, description="A full replacement prompt (older clients)")
    product_id: str | None = Field(None, description=_PRODUCT_ID_DESCRIPTION + " Required.")

    @model_validator(mode="after")
    def _exactly_one_body(self) -> OrchestratorPromptUpdateRequest:
        if (self.additions is None) == (self.content is None):
            raise ValueError("Send exactly one of 'additions' or 'content'.")
        return self


def _require_tenant(current_user: User) -> str:
    tenant_key = getattr(current_user, "tenant_key", None)
    if not tenant_key or not str(tenant_key).strip():
        raise HTTPException(
            status_code=400,
            detail="Authenticated user is missing tenant_key; cannot scope orchestrator prompt.",
        )
    return str(tenant_key)


def _to_response(prompt, *, default_content: str = "") -> OrchestratorPromptResponse:
    return OrchestratorPromptResponse(
        content=prompt.content,
        is_override=prompt.is_override,
        updated_at=prompt.updated_at,
        updated_by=prompt.updated_by,
        scope=getattr(prompt, "scope", "default"),
        default_content=default_content,
        mode=getattr(prompt, "mode", None),
        additions=getattr(prompt, "additions", None),
    )


def _extras(service) -> dict:
    return {"default_content": service.default_orchestrator_content()}


@router.get("/orchestrator-prompt", response_model=OrchestratorPromptResponse)
async def get_orchestrator_prompt(
    product_id: Annotated[str | None, Query(description=_PRODUCT_ID_DESCRIPTION)] = None,
    current_user: User = Depends(require_admin),
):
    """Return the orchestrator prompt that applies to a product: its own saved one, else the built-in one."""
    from api.app_state import state

    service = state.system_prompt_service
    if not service:
        raise HTTPException(status_code=503, detail="System prompt service not available")

    tenant_key = _require_tenant(current_user)
    try:
        prompt = await service.get_orchestrator_prompt(tenant_key=tenant_key, product_id=product_id)
    except ValueError as exc:
        logger.warning("Orchestrator prompt read rejected: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(prompt, **_extras(service))


@router.put("/orchestrator-prompt", response_model=OrchestratorPromptResponse)
async def update_orchestrator_prompt(
    payload: OrchestratorPromptUpdateRequest, current_user: User = Depends(require_admin)
):
    """Save the orchestrator prompt for one product.

    With ``additions``, your text is added on top of the built-in prompt. With
    ``content``, the text replaces the built-in prompt (kept for older clients).
    """
    from api.app_state import state

    service = state.system_prompt_service
    if not service:
        raise HTTPException(status_code=503, detail="System prompt service not available")

    tenant_key = _require_tenant(current_user)

    updated_by = current_user.email or current_user.username or current_user.id
    try:
        if payload.additions is not None:
            prompt = await service.update_orchestrator_additions(
                tenant_key=tenant_key,
                additions=payload.additions,
                updated_by=updated_by,
                product_id=payload.product_id,
            )
        else:
            prompt = await service.update_orchestrator_prompt(
                tenant_key=tenant_key,
                content=payload.content,
                updated_by=updated_by,
                product_id=payload.product_id,
            )
    except ProductRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("System prompt update validation failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid prompt content.") from exc
    except RuntimeError as exc:
        logger.exception("System prompt service error")
        raise HTTPException(status_code=503, detail="System prompt service temporarily unavailable.") from exc

    return _to_response(prompt, **_extras(service))


@router.post("/orchestrator-prompt/reset", response_model=OrchestratorPromptResponse)
async def reset_orchestrator_prompt(
    product_id: Annotated[str | None, Query(description=_PRODUCT_ID_DESCRIPTION)] = None,
    current_user: User = Depends(require_admin),
):
    """Clear a product's saved prompt and return what now applies (the built-in prompt).

    This clears that product's saved additions (or older full replacement). Other
    products' prompts are untouched. ``product_id`` is required.
    """
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
    return _to_response(prompt, **_extras(service))
