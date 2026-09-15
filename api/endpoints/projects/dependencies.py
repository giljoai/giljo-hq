# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import Depends

from api.dependencies import get_tenant_key
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


async def get_project_service(
    tenant_key: str = Depends(get_tenant_key),
    current_user: User = Depends(get_current_active_user),
) -> ProjectService:
    from api.app_state import state

    if tenant_key != current_user.tenant_key:
        TenantManager.set_current_tenant(current_user.tenant_key)

    return ProjectService(
        db_manager=state.db_manager,
        tenant_manager=state.tenant_manager,
        websocket_manager=state.websocket_manager,
    )
