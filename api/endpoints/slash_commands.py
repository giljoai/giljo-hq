# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.slash_commands import get_slash_command


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slash", tags=["slash-commands"])


class SlashCommandRequest(BaseModel):
    """Request model for slash command execution"""

    command: str
    project_id: str | None = None
    arguments: dict[str, Any] = {}


class SlashCommandResponse(BaseModel):
    """Response model for slash command execution"""

    success: bool
    message: str
    launch_prompt: str | None = None
    memory_entry_id: str | None = None
    context_reset: bool | None = None
    error: str | None = None
    details: str | None = None


@router.post("/execute", response_model=SlashCommandResponse)
async def execute_slash_command(request: SlashCommandRequest, current_user: User = Depends(get_current_active_user)):
    """
    Execute a slash command via HTTP

    Args:
        request: SlashCommandRequest containing command name, tenant, and arguments

    Returns:
        SlashCommandResponse with success status and result data

    Raises:
        HTTPException: 404 if command not found
    """
    handler = get_slash_command(request.command)

    if not handler:
        raise HTTPException(status_code=404, detail=f"Slash command /{request.command} not found")

    from api.app_state import state

    async with state.db_manager.get_session_async() as session:
        result = await handler(
            db_session=session,
            tenant_key=current_user.tenant_key,
            project_id=request.project_id,
            **request.arguments,
        )

    return SlashCommandResponse(**result)
