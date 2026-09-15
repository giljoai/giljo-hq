# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.domain.task_status import TASK_STATUS_META, TaskStatus
from giljo_mcp.models import User

from .schemas import TaskStatusResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=list[TaskStatusResponse])
async def list_task_statuses(
    current_user: User = Depends(get_current_active_user),
) -> list[TaskStatusResponse]:
    """Return the canonical task-status metadata in declaration order."""

    del current_user

    return [
        TaskStatusResponse(
            value=member.value,
            label=TASK_STATUS_META[member].label,
            color_token=TASK_STATUS_META[member].color_token,
            is_lifecycle_finished=TASK_STATUS_META[member].is_lifecycle_finished,
        )
        for member in TaskStatus
    ]
