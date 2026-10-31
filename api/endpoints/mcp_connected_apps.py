# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request as StarletteRequest
from starlette.types import Scope

from api.endpoints.auth.session import _resolve_client_ip
from giljo_mcp.services import oauth_login_service


logger = logging.getLogger(__name__)


async def record_connected_app_use(scope: Scope, request: StarletteRequest, tenant_key: str) -> None:
    state_ = scope.get("state", {})
    family_id = state_.get("oauth_family_id")
    if not family_id:
        return
    from api.app_state import state as app_state

    try:
        async with app_state.db_manager.get_session_async(tenant_key=tenant_key) as db:
            await oauth_login_service.record_use(
                db,
                tenant_key=tenant_key,
                family_id=family_id,
                ip=_resolve_client_ip(request),
                user_agent=request.headers.get("user-agent"),
                mcp_client_name=state_.get("mcp_client_name"),
                mcp_client_version=state_.get("mcp_client_version"),
            )
            target = state_.get("mcp_tool_target")
            if target:
                await oauth_login_service.record_product_touch(
                    db,
                    tenant_key=tenant_key,
                    family_id=family_id,
                    product_id=target.get("product_id"),
                    project_id=target.get("project_id"),
                )
    except SQLAlchemyError:
        logger.warning("Connected-app use not recorded (non-blocking)", exc_info=True)
