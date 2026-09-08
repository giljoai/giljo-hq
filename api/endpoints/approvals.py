# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""HTTP surface for the user_approvals primitive (BE-5029 Phase B).

Edition Scope: CE. Both editions consume the same router; SaaS does not extend.
Single endpoint -- ``POST /api/approvals/{approval_id}/decide`` -- which routes
through ``UserApprovalService.mark_decided`` for the atomic
status-flip + agent-resume + WebSocket broadcast.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from api.endpoints.dependencies import (
    get_comm_thread_service,
    get_db_manager,
    get_tenant_manager,
    get_websocket_manager,
)
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.auth import User
from giljo_mcp.models.user_approval import VALID_USER_APPROVAL_STATUSES
from giljo_mcp.schemas.user_approval import ApprovalListResponse
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.user_approval_service import UserApprovalService
from giljo_mcp.tenant import TenantManager


router = APIRouter()


MAX_OPTION_ID_LENGTH = 100


class ApprovalDecideRequest(BaseModel):
    """Closed schema for ``POST /api/approvals/{id}/decide``.

    ``option_id`` MUST match one of the ids stored on the approval row.
    Service-layer validation produces 422; transport-layer validation here
    catches type/length/missing-field abuse before the service is called.
    """

    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(..., min_length=1, max_length=MAX_OPTION_ID_LENGTH)


class ApprovalDecideResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    status: str
    decided_option_id: str
    job_id: str
    project_id: str


async def get_user_approval_service(
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
    websocket_manager=Depends(get_websocket_manager),
    comm_thread_service: CommThreadService = Depends(get_comm_thread_service),
) -> UserApprovalService:
    return UserApprovalService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=websocket_manager,
        comm_thread_service=comm_thread_service,
    )


@router.get(
    "/",
    response_model=ApprovalListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_approvals(
    status_filter: str = Query("pending", alias="status", min_length=1, max_length=20),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_active_user),
    service: UserApprovalService = Depends(get_user_approval_service),
) -> ApprovalListResponse:
    """List approvals scoped to the authenticated user's tenant, by status.

    Tenant isolation is enforced at the repository layer; cross-tenant rows
    are unreachable.

    BE-9514: widened from a ``status='pending'``-only 422 to any
    ``VALID_USER_APPROVAL_STATUSES`` value. Decided approvals previously had
    NO read surface at all -- ``status='decided'`` is the only way to verify
    ``decided_via``/``decided_by_user_id`` end to end (the dashboard inbox
    still defaults to and mainly uses ``pending``).
    """
    if status_filter not in VALID_USER_APPROVAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "APPROVAL_STATUS_UNSUPPORTED",
                "message": f"status must be one of {sorted(VALID_USER_APPROVAL_STATUSES)}.",
                "requested_status": status_filter,
            },
        )
    try:
        items, total = await service.list_pending(
            tenant_key=current_user.tenant_key,
            limit=limit,
            offset=offset,
            status=status_filter,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "APPROVAL_LIST_VALIDATION_ERROR",
                "message": exc.message,
                **exc.context,
            },
        ) from exc

    return ApprovalListResponse(
        items=items,
        count=len(items),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{approval_id}/decide",
    response_model=ApprovalDecideResponse,
    status_code=status.HTTP_200_OK,
)
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecideRequest,
    current_user: User = Depends(get_current_active_user),
    service: UserApprovalService = Depends(get_user_approval_service),
) -> ApprovalDecideResponse:
    """Resolve a pending user_approval and resume the awaiting agent.

    Tenant isolation: ``mark_decided`` filters by ``current_user.tenant_key``.
    Cross-tenant attempts surface as 404 (no existence leak).
    """
    try:
        decided = await service.mark_decided(
            tenant_key=current_user.tenant_key,
            approval_id=approval_id,
            option_id=payload.option_id,
            user_id=str(current_user.id),
            decided_via="ui",
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "APPROVAL_NOT_FOUND",
                "message": exc.message,
                **exc.context,
            },
        ) from exc
    except ValidationError as exc:
        # Already-decided is the conflict case; option-not-in-options is 422.
        if "is not pending" in exc.message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "APPROVAL_ALREADY_DECIDED",
                    "message": exc.message,
                    **exc.context,
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "APPROVAL_OPTION_INVALID",
                "message": exc.message,
                **exc.context,
            },
        ) from exc

    return ApprovalDecideResponse(
        approval_id=decided.id,
        status=decided.status,
        decided_option_id=decided.decided_option_id,
        job_id=decided.job_id,
        project_id=decided.project_id,
    )
