# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from tests.helpers.route_surface import iter_effective_routes




def _walk_dependants(dependant) -> Iterable:
    stack = [dependant]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(getattr(node, "dependencies", []) or [])


def _route_has_dependency(route, target_callable) -> bool:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    return any(getattr(node, "call", None) is target_callable for node in _walk_dependants(dependant))


def _find_route(router, method: str, path_suffix: str):
    exact, suffixed = [], []
    for route in iter_effective_routes(router.routes):
        route_path = getattr(route, "path", "")
        route_methods = set(getattr(route, "methods", set()) or set())
        if method.upper() not in route_methods:
            continue
        if route_path == path_suffix:
            exact.append(route)
        elif route_path.endswith(path_suffix):
            suffixed.append(route)
    matches = exact or suffixed
    if not matches:
        raise AssertionError(
            f"No route found ending in {path_suffix!r} with method {method!r} "
            f"on router {router}. The sweep taxonomy is out of date or the "
            "router was demounted."
        )
    if len(matches) > 1:
        raise AssertionError(
            f"Ambiguous route lookup for method={method} suffix={path_suffix!r}: "
            f"{[r.path for r in matches]}. Tighten the suffix in the test inventory."
        )
    return matches[0]


def _full_path(prefix: str, route) -> str:
    return prefix.rstrip("/") + route.path



_TENANT_LEVEL_INVENTORY: list[tuple[str, str, str, str, str]] = [
    ("system_prompts", "/api/v1/system", "GET", "/orchestrator-prompt", "in_handler"),
    ("system_prompts", "/api/v1/system", "PUT", "/orchestrator-prompt", "in_handler"),
    ("system_prompts", "/api/v1/system", "POST", "/orchestrator-prompt/reset", "in_handler"),
    ("users", "/api/v1/users", "GET", "/", "in_handler"),
    ("users", "/api/v1/users", "POST", "/", "service_injected"),
    ("users", "/api/v1/users", "DELETE", "/{user_id}", "service_injected"),
    ("users", "/api/v1/users", "PUT", "/{user_id}/role", "service_injected"),
    ("users", "/api/v1/users", "POST", "/{user_id}/force-logout", "service_injected"),
    ("user_settings", "/api/v1/user", "GET", "/settings/cookie-domains", "service_injected"),
    ("user_settings", "/api/v1/user", "POST", "/settings/cookie-domains", "service_injected"),
    ("user_settings", "/api/v1/user", "DELETE", "/settings/cookie-domains", "service_injected"),
    ("user_settings", "/api/v1/user", "GET", "/settings/headless-launch", "service_injected"),
    ("user_settings", "/api/v1/user", "PUT", "/settings/headless-launch", "service_injected"),
    ("settings", "/api/v1/settings", "PUT", "/general", "service_injected"),
    ("settings", "/api/v1/settings", "PUT", "/system/agent-silence-threshold", "service_injected"),
    ("settings", "/api/v1/settings", "PUT", "/system/agent-checkin-cadence", "service_injected"),
    ("settings", "/api/v1/settings", "PUT", "/execution-mode-default", "service_injected"),
    ("settings", "/api/v1/settings", "PUT", "/handover-template", "service_injected"),
    ("settings", "/api/v1/settings", "POST", "/handover-template/reset", "service_injected"),
]


_PER_USER_TENANCY_INVENTORY: list[tuple[str, str, str, str]] = [
    ("auth", "/api/auth", "POST", "/register"),
]




def _import_router(module_attr: str):
    import importlib

    module = importlib.import_module(f"api.endpoints.{module_attr}")
    return module.router


@pytest.mark.parametrize(
    ("module_attr", "mount_prefix", "method", "path_suffix", "gate_kind"),
    _TENANT_LEVEL_INVENTORY,
    ids=[
        f"{m}:{method} {mount_prefix}{path_suffix}"
        for (m, mount_prefix, method, path_suffix, _) in _TENANT_LEVEL_INVENTORY
    ],
)
def test_tenant_level_endpoint_has_tenant_gate(
    module_attr: str, mount_prefix: str, method: str, path_suffix: str, gate_kind: str
):
    from api.dependencies import get_tenant_key
    from giljo_mcp.auth.dependencies import get_current_active_user, require_admin

    router = _import_router(module_attr)
    route = _find_route(router, method, path_suffix)

    full = _full_path(mount_prefix, route)
    assert full.startswith(mount_prefix), f"Mount prefix mismatch for {method} {path_suffix}: full path is {full!r}"

    has_auth = _route_has_dependency(route, require_admin) or _route_has_dependency(route, get_current_active_user)
    assert has_auth, (
        f"{method} {full} is admin-gated in the sweep taxonomy but its dependency "
        "chain has neither require_admin nor get_current_active_user. This is a "
        "bucket-(c) BROKEN endpoint per SEC-0005c -- add the auth gate."
    )

    if gate_kind == "service_injected":
        wires_get_tenant_key = _route_has_dependency(route, get_tenant_key)
        wires_require_admin = _route_has_dependency(route, require_admin)
        assert wires_get_tenant_key or wires_require_admin, (
            f"{method} {full} is declared service_injected but has neither "
            "Depends(get_tenant_key) nor Depends(require_admin) in its chain. "
            "The tenant cannot be resolved -- this is a bucket-(c) regression."
        )
    elif gate_kind == "in_handler":
        wires_require_admin = _route_has_dependency(route, require_admin)
        wires_active_user = _route_has_dependency(route, get_current_active_user)
        assert wires_require_admin or wires_active_user, (
            f"{method} {full} is declared in_handler but no auth dependency "
            "is wired -- the handler cannot read current_user.tenant_key safely."
        )
    else:  # pragma: no cover -- inventory typo guard
        raise AssertionError(f"Unknown gate_kind {gate_kind!r} for {method} {full}")




def _make_tenantless_admin(tenant_value=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(uuid4()),
        username="ghost_admin",
        email="ghost@example.com",
        full_name="Ghost Admin",
        role="admin",
        tenant_key=tenant_value,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_value", [None, "", "   "])
async def test_get_orchestrator_prompt_4xx_without_tenant(tenant_value):
    from api.endpoints.system_prompts import get_orchestrator_prompt

    user = _make_tenantless_admin(tenant_value)
    with patch("api.app_state.state") as mock_state:
        mock_state.system_prompt_service = Mock()
        with pytest.raises(HTTPException) as exc:
            await get_orchestrator_prompt(current_user=user)
    assert 400 <= exc.value.status_code < 500


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_value", [None, "", "   "])
async def test_update_orchestrator_prompt_4xx_without_tenant(tenant_value):
    from api.endpoints.system_prompts import (
        OrchestratorPromptUpdateRequest,
        update_orchestrator_prompt,
    )

    user = _make_tenantless_admin(tenant_value)
    payload = OrchestratorPromptUpdateRequest(content="anything")
    with patch("api.app_state.state") as mock_state:
        mock_state.system_prompt_service = Mock()
        with pytest.raises(HTTPException) as exc:
            await update_orchestrator_prompt(payload=payload, current_user=user)
    assert 400 <= exc.value.status_code < 500


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_value", [None, "", "   "])
async def test_reset_orchestrator_prompt_4xx_without_tenant(tenant_value):
    from api.endpoints.system_prompts import reset_orchestrator_prompt

    user = _make_tenantless_admin(tenant_value)
    with patch("api.app_state.state") as mock_state:
        mock_state.system_prompt_service = Mock()
        with pytest.raises(HTTPException) as exc:
            await reset_orchestrator_prompt(current_user=user)
    assert 400 <= exc.value.status_code < 500


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_value", [None, ""])
async def test_list_users_4xx_without_tenant(tenant_value):
    from api.endpoints.users import list_users

    user = _make_tenantless_admin(tenant_value)
    user_service = SimpleNamespace(list_users=AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as exc:
        await list_users(current_user=user, user_service=user_service)
    assert 400 <= exc.value.status_code < 500
    user_service.list_users.assert_not_called()




def test_auth_register_route_is_registered():
    from giljo_mcp.auth.dependencies import require_admin

    router = _import_router("auth")
    route = _find_route(router, "POST", "/register")
    assert _route_has_dependency(route, require_admin), (
        "POST /api/auth/register must depend on require_admin -- only admins can "
        "create new users (and thus new tenants in the per-user tenancy model)."
    )


def test_auth_service_register_user_generates_fresh_tenant_key():
    import inspect

    from giljo_mcp.services.auth_service import AuthService

    candidate_methods = [
        getattr(AuthService, name) for name in ("register_user", "_register_user_impl") if hasattr(AuthService, name)
    ]
    combined_src = "\n".join(inspect.getsource(m) for m in candidate_methods)
    assert "generate_tenant_key" in combined_src, (
        "AuthService.register_user (and its _register_user_impl helper) no "
        "longer call TenantManager.generate_tenant_key. The per-user tenancy "
        "model is broken -- new registrants would inherit the caller's "
        "tenant. Re-classify /auth/register before merging."
    )




def test_no_admin_gated_endpoint_lacks_tenant_resolution():
    from giljo_mcp.auth.dependencies import require_admin, require_ce_mode

    ce_mode_rows = [
        ("configuration", "GET", "/database"),
        ("configuration", "GET", "/ssl"),
        ("configuration", "POST", "/ssl"),
        ("configuration", "POST", "/ssl/cert/upload"),
        ("configuration", "POST", "/ssl/cert/reference"),
        ("configuration", "GET", "/network-info"),
        ("configuration", "GET", "/health/database"),
    ]
    classified: set[tuple[str, str, str]] = set()
    for module_attr, _prefix, method, path_suffix, _gate in _TENANT_LEVEL_INVENTORY:
        classified.add((module_attr, method.upper(), path_suffix))
    for module_attr, _prefix, method, path_suffix in _PER_USER_TENANCY_INVENTORY:
        classified.add((module_attr, method.upper(), path_suffix))
    for module_attr, method, path_suffix in ce_mode_rows:
        classified.add((module_attr, method.upper(), path_suffix))

    sweep_modules = (
        "system_prompts",
        "users",
        "user_settings",
        "settings",
        "configuration",
        "auth",
    )

    unclassified: list[tuple[str, str, str]] = []
    for module_attr in sweep_modules:
        router = _import_router(module_attr)
        for route in iter_effective_routes(router.routes):
            if not _route_has_dependency(route, require_admin):
                continue
            methods = set(getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}
            for method in methods:
                key = (module_attr, method, route.path)
                if key in classified:
                    continue
                if _route_has_dependency(route, require_ce_mode) and any(
                    module_attr == m and method == meth and route.path.endswith(suffix)
                    for (m, meth, suffix) in ce_mode_rows
                ):
                    continue
                if any(
                    module_attr == m and method == meth and route.path.endswith(suffix)
                    for (m, _p, meth, suffix, _g) in _TENANT_LEVEL_INVENTORY
                ):
                    continue
                if any(
                    module_attr == m and method == meth and route.path.endswith(suffix)
                    for (m, _p, meth, suffix) in _PER_USER_TENANCY_INVENTORY
                ):
                    continue
                unclassified.append(key)

    assert not unclassified, (
        "Bucket-(c) regression: the following admin-gated endpoints are not "
        "classified in the SEC-0005c sweep taxonomy. Add them to either the "
        "lane-(a) inventory in this file or the lane-(b) inventory in "
        "test_ce_mode_required.py (and update the SEC-0005c sweep taxonomy):\n"
        + "\n".join(f"  - {m}: {meth} {path}" for (m, meth, path) in sorted(unclassified))
    )
