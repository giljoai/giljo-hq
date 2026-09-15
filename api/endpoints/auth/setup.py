# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User

from .models import SetupStateUpdate


router = APIRouter()


@router.patch("/me/setup-state", tags=["auth"])
async def update_setup_state(
    payload: SetupStateUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Update current user's setup wizard state (Handover 0855a)."""
    from giljo_mcp.schemas.jsonb_validators import validate_setup_selected_tools

    if payload.setup_selected_tools is not None:
        current_user.setup_selected_tools = validate_setup_selected_tools(payload.setup_selected_tools)
    if payload.setup_step_completed is not None:
        current_user.setup_step_completed = payload.setup_step_completed
    if payload.setup_complete is not None:
        current_user.setup_complete = payload.setup_complete
    if payload.learning_complete is not None:
        current_user.learning_complete = payload.learning_complete
    if payload.learning_beat is not None:
        current_user.learning_beat = payload.learning_beat
    if payload.router_choice is not None:
        current_user.router_choice = payload.router_choice
    await db.commit()
    await db.refresh(current_user)
    return {
        "setup_complete": current_user.setup_complete,
        "setup_selected_tools": current_user.setup_selected_tools,
        "setup_step_completed": current_user.setup_step_completed,
        "learning_complete": current_user.learning_complete,
        "learning_beat": current_user.learning_beat,
        "router_choice": current_user.router_choice,
    }
