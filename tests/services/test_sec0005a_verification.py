# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
SEC-0005a verification tests (tester agent).

Complements test_sec0005a_backend.py with the gaps called out in the tester
work order:

  - Task 2: null tenant_key guard at the list_users endpoint returns 400.
  - Task 3: cross-tenant get_user is blocked (admin in tenant_A cannot fetch
    a user from tenant_B via UserService bound to tenant_A).
  - Task 6: the tenant-scoped configuration endpoint (``/configuration/frontend``)
    has NO ``require_ce_mode`` gate, so it remains reachable in demo/SaaS modes.
    (BE-9000b removed the sibling ``/configuration/tenant`` GET/PUT/DELETE
    coverage here -- those routes were deleted as dead code.)

We also spot-check the wiring of ``require_ce_mode`` on the server-level
configuration endpoints so a future refactor that accidentally drops the
dependency is caught here, not in production.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.endpoints.users import list_users
from giljo_mcp.exceptions import ResourceNotFoundError
from tests.helpers.route_surface import iter_effective_routes


# ---------------------------------------------------------------------------
# Task 2: null tenant_key guard on list_users endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_endpoint_rejects_null_tenant_key():
    """list_users endpoint returns HTTP 400 when current_user.tenant_key is None."""
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
    # Service must NOT have been called -- the guard fires first.
    user_service.list_users.assert_not_called()


@pytest.mark.asyncio
async def test_list_users_endpoint_rejects_empty_string_tenant_key():
    """Empty string tenant_key is also treated as missing and rejected with 400."""
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
    """When tenant_key is set, the endpoint calls the service with that tenant_key."""
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


# ---------------------------------------------------------------------------
# Task 3: cross-tenant get_user block (defense in depth at service layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_repository_query_uses_service_tenant_key():
    """
    Cross-tenant defense-in-depth: UserService._get_user_impl always passes
    self.tenant_key to the repository (and never include_all_tenants=True).
    A foreign user in tenant_B is therefore not reachable from a service
    bound to tenant_A -- the repository filter returns None and the service
    raises ResourceNotFoundError.

    Asserted via repository mock so this is deterministic in any DB env and
    still catches a regression where the service drops the tenant filter or
    flips include_all_tenants.
    """
    import logging

    from giljo_mcp.services.user_service import UserService

    mock_repo = AsyncMock()
    mock_repo.get_user_by_id = AsyncMock(return_value=None)  # foreign user invisible
    service = UserService.__new__(UserService)
    service.db_manager = AsyncMock()
    service.tenant_key = "tenant_a"
    service._repo = mock_repo
    service._logger = logging.getLogger("test")

    fake_session = AsyncMock()
    fake_session.info = {}  # tenant_session_context save/restore target
    with pytest.raises(ResourceNotFoundError):
        await service._get_user_impl(fake_session, "foreign-user-uuid")

    mock_repo.get_user_by_id.assert_awaited_once_with(fake_session, "foreign-user-uuid", "tenant_a", False)


# ---------------------------------------------------------------------------
# Task 6: wiring checks -- tenant endpoints are NOT gated, server endpoints ARE
# ---------------------------------------------------------------------------


def _has_ce_mode_dependency(route) -> bool:
    """Return True if the route's dependencies include require_ce_mode."""
    from giljo_mcp.auth.dependencies import require_ce_mode

    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False

    # dependant.dependencies is a list of sub-Dependants; each has a .call attribute.
    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        if getattr(dep, "call", None) is require_ce_mode:
            return True
        stack.extend(getattr(dep, "dependencies", []) or [])
    return False


def _find_routes(router, path_suffix: str, methods: set[str] | None = None):
    """Return routes whose path ends with path_suffix and (optionally) matches methods."""
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
    """GET /frontend is public-ish bootstrap info; never CE-gated."""
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
    """Server-level config endpoints must depend on require_ce_mode."""
    from api.endpoints.configuration import router

    routes = _find_routes(router, path_suffix, methods={method})
    # For "/" match we get many -- filter to the configuration router's own root
    # by requiring the dependant chain to belong to this router (already true).
    assert routes, f"{method} ...{path_suffix} route not found in configuration router"

    gated = [r for r in routes if _has_ce_mode_dependency(r)]
    assert gated, f"{method} ...{path_suffix} must depend on require_ce_mode (server-level endpoints are CE-only)"


# ---------------------------------------------------------------------------
# Mode-gate behavior (complements test_sec0005a_backend.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_ce_mode_blocks_saas_production():
    """Any non-ce value (saas-production etc.) must return 404."""
    from giljo_mcp.auth.dependencies import require_ce_mode

    with patch("api.app_state.GILJO_MODE", "saas-production"), pytest.raises(HTTPException) as exc_info:
        await require_ce_mode()
    assert exc_info.value.status_code == 404
