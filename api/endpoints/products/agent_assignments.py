# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_tenant_key
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import User
from giljo_mcp.services.product_agent_assignment_service import (
    ProductAgentAssignmentService,
)
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()




class ToggleAssignmentRequest(BaseModel):
    """Request body for toggling an agent assignment."""

    is_active: bool = Field(..., description="Whether the template should be active for this product")


class AssignmentResponse(BaseModel):
    """Response for a single assignment."""

    id: str
    product_id: str
    template_id: str
    is_active: bool
    template_name: str | None = None
    template_role: str | None = None
    template_is_active: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AssignmentListResponse(BaseModel):
    """Response for listing assignments."""

    assignments: list[AssignmentResponse]
    count: int


class ToggleAssignmentResponse(BaseModel):
    """Response for toggling an assignment."""

    id: str
    product_id: str
    template_id: str
    is_active: bool




async def get_assignment_service(
    tenant_key: str = Depends(get_tenant_key),
) -> ProductAgentAssignmentService:
    from api.app_state import state

    return ProductAgentAssignmentService(
        db_manager=state.db_manager,
        tenant_key=tenant_key,
    )




@router.get(
    "/{product_id}/agent-assignments",
    response_model=AssignmentListResponse,
    summary="List agent assignments for a product",
)
async def list_agent_assignments(
    product_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ProductAgentAssignmentService = Depends(get_assignment_service),
) -> AssignmentListResponse:
    """
    List all agent template assignments for a product.

    Returns which templates are assigned and their active/inactive state.
    """
    try:
        assignments = await service.list_assignments(product_id)
        return AssignmentListResponse(
            assignments=[AssignmentResponse(**a) for a in assignments],
            count=len(assignments),
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except BaseGiljoError as e:
        logger.exception("Failed to list agent assignments for product %s", sanitize(product_id))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put(
    "/{product_id}/agent-assignments/{template_id}",
    response_model=ToggleAssignmentResponse,
    summary="Toggle agent assignment for a product",
)
async def toggle_agent_assignment(
    product_id: str,
    template_id: str,
    body: ToggleAssignmentRequest,
    current_user: User = Depends(get_current_active_user),
    service: ProductAgentAssignmentService = Depends(get_assignment_service),
) -> ToggleAssignmentResponse:
    """
    Switch an agent on or off for a product.

    Creates the assignment if it doesn't exist, or updates the is_active flag.
    Switching on is refused with 409 when the product already has its full
    complement of agent roles (BE-9610a: the context budget follows the switch
    that spends it).
    """
    try:
        result = await service.toggle_assignment(product_id, template_id, body.is_active)
        return ToggleAssignmentResponse(**result)
    except ProjectStateError as e:
        raise HTTPException(status_code=409, detail=e.message) from e
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except BaseGiljoError as e:
        logger.exception("Failed to toggle agent assignment")
        raise HTTPException(status_code=500, detail=str(e)) from e
