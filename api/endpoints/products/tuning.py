# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.auth import User
from giljo_mcp.services.product_tuning_service import ProductTuningService

from .dependencies import get_db_manager


logger = logging.getLogger(__name__)
router = APIRouter()




class GeneratePromptRequest(BaseModel):
    sections: list[str] = Field(..., description="Section keys to include in tuning prompt")


class GeneratePromptResponse(BaseModel):
    prompt: str
    sections_included: list[str]
    lookback_depth: int | None = None
    git_enabled: bool


class EligibleSectionsResponse(BaseModel):
    sections: list[str]




def _validate_product_id(product_id: str) -> None:
    try:
        UUID(product_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Invalid product_id format") from e


async def _get_tuning_service(current_user: User, db_manager) -> ProductTuningService:
    from api.app_state import state

    ws_manager = getattr(state, "websocket_manager", None)
    return ProductTuningService(
        db_manager=db_manager,
        tenant_key=current_user.tenant_key,
        websocket_manager=ws_manager,
    )




@router.get("/{product_id}/tuning/sections")
async def get_eligible_sections(
    product_id: str,
    current_user: User = Depends(get_current_active_user),
    db_manager=Depends(get_db_manager),
) -> EligibleSectionsResponse:
    """Get sections eligible for tuning based on user's context toggle settings."""
    _validate_product_id(product_id)

    try:
        service = await _get_tuning_service(current_user, db_manager)
        sections = await service.get_eligible_sections(product_id, current_user.id)
        return EligibleSectionsResponse(sections=sections)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail="Product not found.") from e


@router.post("/{product_id}/tuning/generate-prompt")
async def generate_tuning_prompt(
    product_id: str,
    request: GeneratePromptRequest,
    current_user: User = Depends(get_current_active_user),
    db_manager=Depends(get_db_manager),
) -> GeneratePromptResponse:
    """
    Generate a tuning comparison prompt for selected sections.

    The prompt includes current product context and recent 360 memory entries
    at the user's configured depth. User copies this to their CLI tool.
    """
    _validate_product_id(product_id)

    try:
        service = await _get_tuning_service(current_user, db_manager)
        result = await service.assemble_tuning_prompt(
            product_id=product_id,
            user_id=current_user.id,
            sections=request.sections,
        )
        return GeneratePromptResponse(**result)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail="Product not found.") from e
    except ValidationError as e:
        raise HTTPException(status_code=400, detail="Invalid tuning request.") from e
