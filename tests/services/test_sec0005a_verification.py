# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.endpoints.users import list_users
from giljo_mcp.exceptions import ResourceNotFoundError
from tests.helpers.route_surface import iter_effective_routes




@pytest.mark.asyncio
async def test_list_users_endpoint_rejects_null_tenant_key():
    admin_with_null_tenant = SimpleNamespace(
        id=str(uuid4()),
        username="ghost_admin",
        tenant_key=None,
        role="admin",
    )
    user_service = SimpleNamespace(list_users=AsyncMock(return_value=[]))

    with pytest.raises(HTTPException) as exc_info:
        await list_users(current_user=admin_with_null_tenant, user_service=user_service)

    assert exc_info.value.status_code == 400
    user_service.list_users.assert_not_called()


@pytest.mark.asyncio
async def test_list_users_endpoint_rejects_empty_string_tenant_key():
    admin_with_empty_tenant = SimpleNamespace(
        id=str(uuid4()),
        username="ghost_admin",
        tenant_key="",
        role="admin",
    )
    user_service = SimpleNamespace(list_users=AsyncMock(return_value=[]))

    with pytest.raises(HTTPException) as exc_info:
        await list_users(current_user=admin_with_empty_tenant, user_service=user_service)

    assert exc_info.value.status_code == 400
    user_service.list_users.assert_not_called()


@pytest.mark.asyncio
async def test_list_users_endpoint_passes_admin_tenant_key_to_service():
    admin = SimpleNamespace(
        id=str(uuid4()),
        username="real_admin",
        tenant_key="tenant_a",
        role="admin",
    )
    user_service = SimpleNamespace(list_users=AsyncMock(return_value=[]))

    result = await list_users(current_user=admin, user_service=user_service)

    assert result == []
    user_service.list_users.assert_awaited_once_with(tenant_key="tenant_a")




@pytest.mark.asyncio
async def test_get_user_repository_query_uses_service_tenant_key():
    import logging

    from giljo_mcp.services.user_service import UserService

    mock_repo = AsyncMock()
    mock_repo.get_user_by_id = AsyncMock(return_value=None)
    service = UserService.__new__(UserService)
    service.db_manager = AsyncMock()
    service.tenant_key = "tenant_a"
    service._repo = mock_repo
    service._logger = logging.getLogger("test")

    fake_session = AsyncMock()
    fake_session.info = {}
    with pytest.raises(ResourceNotFoundError):
        await service._get_user_impl(fake_session, "foreign-user-uuid")

    mock_repo.get_user_by_id.assert_awaited_once_with(fake_session, "foreign-user-uuid", "tenant_a", False)




def _has_ce_mode_dependency(route) -> bool:
    from giljo_mcp.auth.dependencies import require_ce_mode

    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False

    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        if getattr(dep, "call", None) is require_ce_mode:
            return True
        stack.extend(getattr(dep, "dependencies", []) or [])
    return False


def _find_routes(router, path_suffix: str, methods: set[str] | None = None):
    matches = []
    for route in iter_effective_routes(router.routes):
        route_path = getattr(route, "path", "")
        if not route_path.endswith(path_suffix):
            continue
        route_methods = set(getattr(route, "methods", set()) or set())
        if methods and not methods.issubset(route_methods):
            continue
        matches.append(route)
    return matches


def test_frontend_configuration_endpoint_is_not_ce_gated():
    from api.endpoints.configuration import router

    routes = _find_routes(router, "/frontend", methods={"GET"})
    assert routes, "GET /configuration/frontend route not found"
    for r in routes:
        assert not _has_ce_mode_dependency(r), f"Route {r.methods} {r.path} must NOT depend on require_ce_mode"


@pytest.mark.parametrize(
    ("path_suffix", "method"),
    [
        ("/database", "GET"),
        ("/ssl", "GET"),
        ("/ssl", "POST"),
        ("/ssl/cert/upload", "POST"),
        ("/ssl/cert/reference", "POST"),
        ("/health/database", "GET"),
    ],
)
def test_server_level_configuration_endpoints_are_ce_gated(path_suffix, method):
    from api.endpoints.configuration import router

    routes = _find_routes(router, path_suffix, methods={method})
    assert routes, f"{method} ...{path_suffix} route not found in configuration router"

    gated = [r for r in routes if _has_ce_mode_dependency(r)]
    assert gated, f"{method} ...{path_suffix} must depend on require_ce_mode (server-level endpoints are CE-only)"




@pytest.mark.asyncio
async def test_require_ce_mode_blocks_saas_production():
    from giljo_mcp.auth.dependencies import require_ce_mode

    with patch("api.app_state.GILJO_MODE", "saas-production"), pytest.raises(HTTPException) as exc_info:
        await require_ce_mode()
    assert exc_info.value.status_code == 404
