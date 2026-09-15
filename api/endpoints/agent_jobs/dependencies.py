# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import Depends

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import User
from giljo_mcp.services.job_query_service import JobQueryService
from giljo_mcp.services.orchestration_service import OrchestrationService


logger = logging.getLogger(__name__)


async def get_db_manager() -> DatabaseManager:
    from api.app_state import state

    return state.db_manager


async def get_tenant_manager():
    from api.app_state import state

    return state.tenant_manager


async def get_orchestration_service(
    current_user: User = Depends(get_current_active_user),
) -> OrchestrationService:
    from api.app_state import state

    logger.debug(f"get_orchestration_service called for user {current_user.username}")
    logger.debug(f"state.db_manager is None: {state.db_manager is None}")
    logger.debug(f"state.tenant_manager is None: {state.tenant_manager is None}")

    return OrchestrationService(
        db_manager=state.db_manager,
        tenant_manager=state.tenant_manager,
        websocket_manager=state.websocket_manager,
    )


async def get_job_query_service() -> JobQueryService:
    from api.app_state import state

    return JobQueryService(
        db_manager=state.db_manager,
        tenant_manager=state.tenant_manager,
    )


async def get_workflow_status_service():
    from api.app_state import state
    from giljo_mcp.services.workflow_status_service import WorkflowStatusService

    return WorkflowStatusService(
        db_manager=state.db_manager,
        tenant_manager=state.tenant_manager,
    )
