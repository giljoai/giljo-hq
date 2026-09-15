# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import Depends

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.template_service import TemplateService


def get_template_service(
    current_user: User = Depends(get_current_active_user),
) -> TemplateService:
    from api.app_state import state

    return TemplateService(db_manager=state.db_manager, tenant_manager=state.tenant_manager)
