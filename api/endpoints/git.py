# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.websocket import WebSocketDependency, get_websocket_dependency
from api.endpoints.dependencies import get_user_service
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.services.user_service import UserService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()

_GIT_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "use_in_prompts": False,
}


class GitToggleRequest(BaseModel):
    """Request to toggle Git integration."""

    enabled: bool


class GitSettingsRequest(BaseModel):
    """Request to update Git advanced settings.

    BE-9148: ``include_commit_history``/``branch_strategy`` were retired (never
    consumed). A client still POSTing them is tolerated — Pydantic ignores the
    unknown fields and the request succeeds unchanged.
    """

    use_in_prompts: bool


class GitToggleResponse(BaseModel):
    """Response from toggling Git integration."""

    success: bool
    enabled: bool
    message: str
    settings: dict[str, Any]


@router.post("/toggle", response_model=GitToggleResponse)
async def toggle_git_integration(
    request: GitToggleRequest,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    ws_dep: WebSocketDependency = Depends(get_websocket_dependency),
    user_service: UserService = Depends(get_user_service),
) -> GitToggleResponse:
    """
    Toggle Git integration at the system level.

    Stores in database Settings table (category='integrations').
    When disabling, cascades to bulk-disable git_history in user_field_priorities.
    """
    tenant_key = current_user.tenant_key
    service = SettingsService(db, tenant_key)

    integrations = await service.get_settings("integrations")
    git_settings = integrations.get("git_integration", dict(_GIT_DEFAULTS))

    git_settings["enabled"] = request.enabled
    git_settings["use_in_prompts"] = request.enabled

    integrations["git_integration"] = git_settings
    await service.update_settings("integrations", integrations)

    if not request.enabled:
        disabled_count = await user_service.bulk_disable_field_priority("git_history")
        if disabled_count > 0:
            logger.info(
                "Cascade: disabled git_history for %d user(s) in tenant %s",
                disabled_count,
                sanitize(tenant_key),
            )

    logger.info("Git integration toggled to %s by user %s", sanitize(request.enabled), sanitize(current_user.username))

    try:
        await ws_dep.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type="product:git:settings:changed",
            data={"enabled": request.enabled, "settings": git_settings},
        )
        logger.info("[WEBSOCKET] Broadcasted git integration change to tenant %s", sanitize(tenant_key))
    except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
        logger.warning("[WEBSOCKET] Failed to broadcast git integration update: %s", sanitize(str(ws_error)))

    return GitToggleResponse(
        success=True,
        enabled=request.enabled,
        message=f"Git integration {'enabled' if request.enabled else 'disabled'} successfully",
        settings=git_settings,
    )


@router.post("/settings", response_model=GitToggleResponse)
async def update_git_settings(
    request: GitSettingsRequest,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> GitToggleResponse:
    """
    Update Git advanced settings at the system level.
    """
    tenant_key = current_user.tenant_key
    service = SettingsService(db, tenant_key)

    integrations = await service.get_settings("integrations")
    git_settings = integrations.get("git_integration", dict(_GIT_DEFAULTS))

    git_settings["use_in_prompts"] = request.use_in_prompts

    integrations["git_integration"] = git_settings
    await service.update_settings("integrations", integrations)

    logger.info("Git settings updated by user %s", sanitize(current_user.username))

    return GitToggleResponse(
        success=True,
        enabled=git_settings.get("enabled", False),
        message="Git settings updated successfully",
        settings=git_settings,
    )


@router.get("/settings")
async def get_git_settings(
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Get current Git integration settings from database.
    """
    tenant_key = current_user.tenant_key
    service = SettingsService(db, tenant_key)

    integrations = await service.get_settings("integrations")
    return integrations.get("git_integration", dict(_GIT_DEFAULTS))
