# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
from giljo_mcp.schemas.responses.onboarding import StartListResult
from giljo_mcp.services.start_list_service import get_start_list


router = APIRouter()


@router.get("/start-list", response_model=StartListResult, tags=["onboarding"])
async def get_onboarding_start_list(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> StartListResult:
    """Which of the six first steps your account has really done.

    Read-only and limited to the signed-in person's own account. The steps are: an AI tool
    connected, the skills installed, a product created, a project created, a project staged, and a first
    project built and closed. Each one is read from what has actually happened, so nothing
    can be ticked by hand.
    """
    return await get_start_list(db, current_user.tenant_key)
