# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.endpoints.dependencies import get_notification_service
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.models.notifications import Notification
from giljo_mcp.services.notification_service import NotificationService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    """A single notification row as rendered by the dashboard bell.

    ``user_id`` is ``None`` for tenant-scoped (broadcast) notifications.
    Lifecycle timestamps are ISO-8601 strings or ``None`` when unset.
    """

    id: str
    type: str
    severity: str
    title: str
    body: str | None
    payload: dict
    surface: str
    role_filter: str | None
    cta_label: str | None
    cta_route: str | None
    dismissible: bool
    read_at: str | None
    dismissed_at: str | None
    created_at: str | None

    @classmethod
    def from_orm_row(cls, row: Notification) -> "NotificationResponse":
        return cls(
            id=str(row.id),
            type=row.type,
            severity=row.severity,
            title=row.title,
            body=row.body,
            payload=row.payload or {},
            surface=row.surface,
            role_filter=row.role_filter,
            cta_label=row.cta_label,
            cta_route=row.cta_route,
            dismissible=row.dismissible,
            read_at=row.read_at.isoformat() if row.read_at else None,
            dismissed_at=row.dismissed_at.isoformat() if row.dismissed_at else None,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    include_dismissed: bool = Query(default=False),
    surface: str | None = Query(default=None, pattern="^(bell|banner|both)$"),
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_active_user),
) -> list[NotificationResponse]:
    """List the current user's notifications (newest-first), tenant-scoped.

    Excludes resolved notifications. Dismissed rows are excluded unless
    ``include_dismissed=true``. ``surface`` filters to a render surface
    (``bell`` or ``banner`` — each also returns ``both`` rows). Role-gated
    rows (``role_filter``) are excluded server-side for users lacking the role.
    """
    rows = await service.list_for_user(
        tenant_key=current_user.tenant_key,
        user_id=str(current_user.id),
        include_dismissed=include_dismissed,
        surface=surface,
    )
    return [NotificationResponse.from_orm_row(row) for row in rows]


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: str,
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_active_user),
) -> NotificationResponse:
    """Mark a notification as read for the current user (tenant-scoped)."""
    row = await service.mark_read(
        tenant_key=current_user.tenant_key,
        notification_id=notification_id,
        user_id=str(current_user.id),
    )
    return NotificationResponse.from_orm_row(row)


@router.patch("/{notification_id}/dismiss", response_model=NotificationResponse)
async def dismiss_notification(
    notification_id: str,
    service: NotificationService = Depends(get_notification_service),
    current_user: User = Depends(get_current_active_user),
) -> NotificationResponse:
    """Dismiss (hide) a notification for the current user (tenant-scoped)."""
    row = await service.mark_dismissed(
        tenant_key=current_user.tenant_key,
        notification_id=notification_id,
        user_id=str(current_user.id),
    )
    return NotificationResponse.from_orm_row(row)
