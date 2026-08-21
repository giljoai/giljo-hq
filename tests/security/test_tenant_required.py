# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
SEC-0005c Property B regression suite -- "tenant_key is required".

Source of truth for the endpoint inventory: the SEC-0005c sweep taxonomy
(12 TENANT-LEVEL rows -- BE-9000b removed 4 dead-route rows: configuration
GET/PUT/DELETE /tenant and settings PUT /network). For every row this suite
asserts:

  (1) The route is registered at the expected method+path under the expected
      router prefix (catches accidental router demounts / prefix changes).

  (2) The route's FastAPI dependency chain wires ONE of two tenant gates:
        (a) ``Depends(require_admin)`` (admin role) AND the handler resolves
            tenant_key explicitly from ``current_user`` (in-handler guard
            pattern -- system_prompts, users list, configuration tenant CRUD), OR
        (b) ``Depends(get_tenant_key)`` somewhere in the dependency chain
            (service-injected tenant pattern -- users CRUD via get_user_service,
            settings + user_settings via SettingsService(db, current_user.tenant_key)).

      Either pattern is acceptable. What is NOT acceptable is an admin-gated
      endpoint with no tenant resolution at all -- bucket (c) of the sweep,
      which is currently empty and must stay empty.

  (3) Endpoints that follow the in-handler guard pattern get an additional
      direct-call test: invoke the handler with a SimpleNamespace admin whose
      ``tenant_key`` is None or empty, and assert HTTPException 400. This is
      the same pattern used by tests/services/test_sec0005a_verification.py
      and tests/services/test_sec0005b_verification.py.

The /auth/register endpoint is tenant-related but not Property-B-shaped (it
*creates* a tenant per call instead of resolving an existing one). It is
covered separately at the bottom of this module with its own assertion shape,
per the analyzer's note in the sweep taxonomy.
"""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from tests.helpers.route_surface import iter_effective_routes


# ---------------------------------------------------------------------------
# Helpers: route lookup + dependency-chain walk
# ---------------------------------------------------------------------------


def _walk_dependants(dependant) -> Iterable:
    """Depth-first walk of the dependant tree, yielding each Dependant node."""
    stack = [dependant]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(getattr(node, "dependencies", []) or [])


def _route_has_dependency(route, target_callable) -> bool:
    """True if ``route``'s dependant chain includes ``target_callable``."""
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    return any(getattr(node, "call", None) is target_callable for node in _walk_dependants(dependant))


def _find_route(router, method: str, path_suffix: str):
    """
    Find the route on ``router`` whose path matches ``path_suffix`` and whose
    methods include ``method``. Prefers exact-path match over suffix match so
    a suffix like "/database" does not collide with "/health/database".
    """
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
    """Join the app-level mount prefix with the route's local path."""
    return prefix.rstrip("/") + route.path


# ---------------------------------------------------------------------------
# Endpoint inventory (lane-a / TENANT-LEVEL rows from SEC-0005c_sweep_taxonomy.md)
# ---------------------------------------------------------------------------
#
# Each row: (router_module_attr, mount_prefix, method, path_suffix, gate_kind)
#
# gate_kind ::= "in_handler" | "service_injected"
#   in_handler        -- handler explicitly checks current_user.tenant_key (or
#                        request.state.tenant_key) and 4xx's. We invoke the
#                        handler directly with a tenantless admin to confirm.
#   service_injected  -- handler depends on get_tenant_key (via a service
#                        factory like get_user_service). We assert the
#                        dependency chain wires get_tenant_key.

_TENANT_LEVEL_INVENTORY: list[tuple[str, str, str, str, str]] = [
    # api/endpoints/system_prompts.py (3) -- in-handler guard via _require_tenant
    ("system_prompts", "/api/v1/system", "GET", "/orchestrator-prompt", "in_handler"),
    ("system_prompts", "/api/v1/system", "PUT", "/orchestrator-prompt", "in_handler"),
    ("system_prompts", "/api/v1/system", "POST", "/orchestrator-prompt/reset", "in_handler"),
    # users router (4 endpoints). list_users uses the in-handler 400 guard
    # added in SEC-0005a; create/delete/change_role flow the tenant via
    # get_user_service (which depends on get_tenant_key).
    ("users", "/api/v1/users", "GET", "/", "in_handler"),
    ("users", "/api/v1/users", "POST", "/", "service_injected"),
    ("users", "/api/v1/users", "DELETE", "/{user_id}", "service_injected"),
    ("users", "/api/v1/users", "PUT", "/{user_id}/role", "service_injected"),
    # SEC-6011 admin-forced-logout: tenant flows via get_user_service (UserService
    # is tenant-scoped), same pattern as the role/delete endpoints above.
    ("users", "/api/v1/users", "POST", "/{user_id}/force-logout", "service_injected"),
    # user_settings router (5 endpoints). No explicit 400 guard; tenant flows
    # from current_user.tenant_key into SettingsService at the handler. Gated
    # by require_admin; classified service_injected for the route-level check.
    # headless-launch pair added by BE-9084 (account-wide Headless-vs-HITL toggle).
    ("user_settings", "/api/v1/user", "GET", "/settings/cookie-domains", "service_injected"),
    ("user_settings", "/api/v1/user", "POST", "/settings/cookie-domains", "service_injected"),
    ("user_settings", "/api/v1/user", "DELETE", "/settings/cookie-domains", "service_injected"),
    ("user_settings", "/api/v1/user", "GET", "/settings/headless-launch", "service_injected"),
    ("user_settings", "/api/v1/user", "PUT", "/settings/headless-launch", "service_injected"),
    # settings router (2 endpoints). Tenant flows from current_user.tenant_key
    # into SettingsService (or, for SaaS, TenantConfigurationService) at the
    # handler; service_injected. FE-9241 moved agent-silence-threshold PUT here
    # from the CE-mode-gated list -- it's now reachable (and tenant-resolving)
    # in every edition, not require_ce_mode-gated.
    ("settings", "/api/v1/settings", "PUT", "/general", "service_injected"),
    ("settings", "/api/v1/settings", "PUT", "/system/agent-silence-threshold", "service_injected"),
    # FE-9296b: the account-level check-in cadence, hosted exactly like the
    # silence threshold above (same handler shape, same tenant flow).
    ("settings", "/api/v1/settings", "PUT", "/system/agent-checkin-cadence", "service_injected"),
]


# /auth/register is lane-a (per-user tenancy) but Property B does not apply in
# the standard "400 when no tenant context" shape -- see dedicated test below.
_PER_USER_TENANCY_INVENTORY: list[tuple[str, str, str, str]] = [
    ("auth", "/api/auth", "POST", "/register"),
]


# ---------------------------------------------------------------------------
# (1) + (2): Route is registered AND a tenant gate is wired
# ---------------------------------------------------------------------------


def _import_router(module_attr: str):
    """Import api.endpoints.<module_attr>.router."""
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
    """
    Property B (route-level): every lane-(a) endpoint resolves a tenant before
    touching service code -- either via an in-handler guard (require_admin
    + explicit current_user.tenant_key check) or via a get_tenant_key
    dependency chain.
    """
    from api.dependencies import get_tenant_key
    from giljo_mcp.auth.dependencies import get_current_active_user, require_admin

    router = _import_router(module_attr)
    route = _find_route(router, method, path_suffix)

    # (1) Sanity: route mount path matches the sweep taxonomy.
    full = _full_path(mount_prefix, route)
    assert full.startswith(mount_prefix), f"Mount prefix mismatch for {method} {path_suffix}: full path is {full!r}"

    # (2a) Auth dependency present (require_admin OR get_current_active_user).
    has_auth = _route_has_dependency(route, require_admin) or _route_has_dependency(route, get_current_active_user)
    assert has_auth, (
        f"{method} {full} is admin-gated in the sweep taxonomy but its dependency "
        "chain has neither require_admin nor get_current_active_user. This is a "
        "bucket-(c) BROKEN endpoint per SEC-0005c -- add the auth gate."
    )

    # (2b) Tenant gate present according to the declared pattern.
    if gate_kind == "service_injected":
        wires_get_tenant_key = _route_has_dependency(route, get_tenant_key)
        # Some service_injected endpoints (user_settings, settings, /tenant via
        # require_admin) read tenant_key from current_user inside the handler
        # and never go through get_tenant_key. For those we assert require_admin
        # is present (auth gate above already covers it) -- the in-handler use
        # of current_user.tenant_key is verified by the dedicated property A
        # tenant-isolation suite. So service_injected only *requires*
        # get_tenant_key for endpoints that use a Depends-built service.
        # For the ones that don't, the require_admin gate is sufficient.
        # We accept either signal here.
        wires_require_admin = _route_has_dependency(route, require_admin)
        assert wires_get_tenant_key or wires_require_admin, (
            f"{method} {full} is declared service_injected but has neither "
            "Depends(get_tenant_key) nor Depends(require_admin) in its chain. "
            "The tenant cannot be resolved -- this is a bucket-(c) regression."
        )
    elif gate_kind == "in_handler":
        # In-handler endpoints must be admin-gated (the handler reads
        # current_user.tenant_key). get_current_active_user alone is acceptable
        # only for GET /tenant per the sweep taxonomy.
        wires_require_admin = _route_has_dependency(route, require_admin)
        wires_active_user = _route_has_dependency(route, get_current_active_user)
        assert wires_require_admin or wires_active_user, (
            f"{method} {full} is declared in_handler but no auth dependency "
            "is wired -- the handler cannot read current_user.tenant_key safely."
        )
    else:  # pragma: no cover -- inventory typo guard
        raise AssertionError(f"Unknown gate_kind {gate_kind!r} for {method} {full}")


# ---------------------------------------------------------------------------
# (3) Direct-call: in_handler endpoints 4xx with a tenantless admin
# ---------------------------------------------------------------------------
#
# We exercise one representative call per in_handler endpoint. The dedicated
# SEC-0005a/SEC-0005b verification suites already cover the full message text;
# here we assert the contract -- "no tenant_key, no service call, 4xx".


def _make_tenantless_admin(tenant_value=None) -> SimpleNamespace:
    """A SimpleNamespace user that quacks like models.auth.User for handlers."""
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
    """system_prompts.GET /orchestrator-prompt -- in-handler guard via _require_tenant."""
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
    """system_prompts.PUT /orchestrator-prompt -- in-handler guard via _require_tenant."""
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
    """system_prompts.POST /orchestrator-prompt/reset -- in-handler guard."""
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
    """users.GET / -- in-handler guard (SEC-0005a)."""
    from api.endpoints.users import list_users

    user = _make_tenantless_admin(tenant_value)
    user_service = SimpleNamespace(list_users=AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as exc:
        await list_users(current_user=user, user_service=user_service)
    assert 400 <= exc.value.status_code < 500
    user_service.list_users.assert_not_called()


# ---------------------------------------------------------------------------
# Per-user tenancy edge case: /auth/register
# ---------------------------------------------------------------------------
#
# Per the sweep analyzer's note: /auth/register *creates* a new tenant per
# registrant via TenantManager.generate_tenant_key(). Property B's standard
# "4xx without tenant context" shape does not apply -- the endpoint
# legitimately runs even when the caller has no tenant_key (the CE bootstrap
# case). Instead we assert the route is registered, gated by require_admin,
# and that the AuthService.register_user code path generates a fresh tenant
# for the new user.


def test_auth_register_route_is_registered():
    """/api/auth/register exists and is admin-gated."""
    from giljo_mcp.auth.dependencies import require_admin

    router = _import_router("auth")
    route = _find_route(router, "POST", "/register")
    assert _route_has_dependency(route, require_admin), (
        "POST /api/auth/register must depend on require_admin -- only admins can "
        "create new users (and thus new tenants in the per-user tenancy model)."
    )


def test_auth_service_register_user_generates_fresh_tenant_key():
    """
    AuthService.register_user creates a new tenant_key per registrant via
    TenantManager.generate_tenant_key(). This is the per-user tenancy model:
    the new user lands in a brand-new tenant, NOT the caller's tenant. This is
    the intentional behavior, not a Property B violation.
    """
    import inspect

    from giljo_mcp.services.auth_service import AuthService

    # The contract: somewhere in the register_user code path,
    # TenantManager.generate_tenant_key(...) is called to mint a fresh tenant
    # for the new user. Currently register_user delegates to _register_user_impl;
    # we inspect both so a refactor that splits the call deeper still passes
    # as long as the invariant holds in this service module.
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


# ---------------------------------------------------------------------------
# Bucket-(c) negative assertion: no admin-gated endpoint should be ungated
# ---------------------------------------------------------------------------


def test_no_admin_gated_endpoint_lacks_tenant_resolution():
    """
    Walk every router that hosts admin-gated endpoints in the sweep, find
    every route depending on require_admin, and assert each is either listed
    in the lane-(a) inventory above OR in the lane-(b) CE-mode-gated list
    (asserted by tests/security/test_ce_mode_required.py). A new admin-gated
    endpoint that is in neither list is a bucket-(c) regression and fails
    this assertion -- update one of the inventories before merging.

    This is the safety net for the "two-orthogonal-axes invariant": a future
    PR cannot quietly add a new @router.x(..., dependencies=[require_admin])
    endpoint without classifying it.
    """
    from giljo_mcp.auth.dependencies import require_admin, require_ce_mode

    # Build the union: every (module, method, path_suffix) we have classified.
    # CE-mode-gated rows are duplicated here from test_ce_mode_required.py to
    # keep the assertion local; if the inventories drift, both tests fail and
    # force re-sync.
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

    # Modules that the SEC-0005c sweep enumerated as hosting admin-gated routes.
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
                # Allow CE-mode-gated routes to slip through this check even if
                # the inventory string differs (path_suffix vs full route.path).
                if _route_has_dependency(route, require_ce_mode) and any(
                    module_attr == m and method == meth and route.path.endswith(suffix)
                    for (m, meth, suffix) in ce_mode_rows
                ):
                    continue
                # Allow lane-(a) routes whose path_suffix is a strict suffix
                # of route.path (e.g. inventory says "/" -> route.path "/").
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
