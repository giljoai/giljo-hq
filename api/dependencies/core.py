# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import os

from fastapi import Request

from giljo_mcp.tenant import TenantManager


def _get_default_tenant_key() -> str:
    from api.app_state import state

    if hasattr(state, "config") and state.config and state.config.tenant.default_tenant_key:
        return state.config.tenant.default_tenant_key

    key = os.getenv("DEFAULT_TENANT_KEY")
    if key:
        return key

    raise RuntimeError(
        "No default tenant key configured. Set tenant.default_key in config.yaml or DEFAULT_TENANT_KEY in .env"
    )


async def get_tenant_key(request: Request) -> str:
    from fastapi import HTTPException

    from api.app_state import state

    if hasattr(state, "api_state") and hasattr(state.api_state, "config"):
        setup_mode = getattr(state.api_state.config, "setup_mode", False)
        if setup_mode:
            return _get_default_tenant_key()

    if request.method == "OPTIONS":
        return _get_default_tenant_key()

    tenant_key = getattr(request.state, "tenant_key", None)

    if tenant_key:
        if hasattr(state, "db_manager") and state.db_manager:
            TenantManager.set_current_tenant(tenant_key)
        return tenant_key

    tenant_key = TenantManager.get_current_tenant()
    if tenant_key:
        return tenant_key

    if os.environ.get("GILJO_MODE", "").strip().lower() == "saas":
        raise HTTPException(status_code=401, detail="Authentication required")

    default_tenant = _get_default_tenant_key()
    if hasattr(state, "db_manager") and state.db_manager:
        TenantManager.set_current_tenant(default_tenant)
    return default_tenant


async def get_db(request: Request):
    from api.app_state import state

    if not state.db_manager:
        raise RuntimeError("Database manager not initialized")

    tenant_key = getattr(request.state, "tenant_key", None)

    async with state.db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.info["request_path"] = request.url.path
        yield session
