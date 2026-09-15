# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
from giljo_mcp.services.settings_service import SettingsService


logger = logging.getLogger(__name__)
router = APIRouter()


class SerenaToggleRequest(BaseModel):
    """Request model for Serena toggle"""

    use_in_prompts: bool


@router.get("/settings")
async def get_serena_settings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get simplified Serena MCP settings.

    Returns only use_in_prompts toggle (advanced settings removed in Handover 0277).
    """
    service = SettingsService(db, current_user.tenant_key)
    integrations = await service.get_settings("integrations")
    serena = integrations.get("serena_mcp", {})

    return {"use_in_prompts": bool(serena.get("use_in_prompts", False))}


@router.post("/toggle")
async def toggle_serena(
    request: SerenaToggleRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Toggle Serena MCP on/off.

    Accepts only use_in_prompts boolean (advanced settings removed in Handover 0277).
    """
    service = SettingsService(db, current_user.tenant_key)
    integrations = await service.get_settings("integrations")

    serena = integrations.get("serena_mcp", {})
    serena["use_in_prompts"] = request.use_in_prompts
    integrations["serena_mcp"] = serena

    await service.update_settings("integrations", integrations)

    logger.info("Serena prompts %s", "enabled" if request.use_in_prompts else "disabled")

    return {
        "success": True,
        "enabled": request.use_in_prompts,
        "use_in_prompts": request.use_in_prompts,
        "message": f"Serena prompts {'enabled' if request.use_in_prompts else 'disabled'}",
    }


@router.get("/status")
async def get_serena_status(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get current Serena prompt toggle status (legacy endpoint)."""
    service = SettingsService(db, current_user.tenant_key)
    integrations = await service.get_settings("integrations")
    enabled = integrations.get("serena_mcp", {}).get("use_in_prompts", False)

    return {"enabled": enabled, "message": f"Serena prompts {'enabled' if enabled else 'disabled'}"}
