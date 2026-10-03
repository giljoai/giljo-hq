# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Iterable
from unittest.mock import patch

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
            f"No configuration route ending in {path_suffix!r} with method "
            f"{method!r}. The sweep taxonomy is out of date."
        )
    if len(matches) > 1:
        raise AssertionError(
            f"Ambiguous route lookup for {method} {path_suffix!r}: "
            f"{[r.path for r in matches]}. Tighten the suffix in the inventory."
        )
    return matches[0]



_CE_MODE_INVENTORY: list[tuple[str, str, str, str]] = [
    ("/api/v1/config", "GET", "/", "reads server-global config.yaml (full system-configuration dump)"),
    ("/api/v1/config", "GET", "/database", "reads .env DB_HOST/PORT/USER/NAME/PASSWORD"),
    ("/api/v1/config", "GET", "/network-info", "reports the host IP(s) + port the server actually responds on"),
    ("/api/v1/config", "GET", "/health/database", "pings server-global DB connection"),
]


def _import_configuration_router():
    from api.endpoints import configuration

    return configuration.router


def _router_for_prefix(mount_prefix: str):
    if mount_prefix == "/api/v1/config":
        return _import_configuration_router()
    if mount_prefix == "/api/v1/settings":
        from api.endpoints import settings

        return settings.router
    raise AssertionError(f"No router mapping for mount_prefix {mount_prefix!r}; update _router_for_prefix.")




@pytest.mark.parametrize(
    ("mount_prefix", "method", "path_suffix", "reason"),
    _CE_MODE_INVENTORY,
    ids=[f"{method} {mount_prefix}{suffix}" for (mount_prefix, method, suffix, _r) in _CE_MODE_INVENTORY],
)
def test_server_level_endpoint_depends_on_require_ce_mode(
    mount_prefix: str, method: str, path_suffix: str, reason: str
):
    from giljo_mcp.auth.dependencies import require_ce_mode

    router = _router_for_prefix(mount_prefix)
    route = _find_route(router, method, path_suffix)

    full = mount_prefix.rstrip("/") + route.path
    assert _route_has_dependency(route, require_ce_mode), (
        f"{method} {full} is SERVER-LEVEL ({reason}) but its dependency chain "
        "does NOT include require_ce_mode. This endpoint is reachable in "
        "demo/SaaS modes -- a violation of the two-orthogonal-axes invariant. "
        "Add ``_ce: None = Depends(require_ce_mode)`` to the handler signature."
    )




@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode_value",
    ["demo", "saas", "saas-production", "saas-staging", "production", "CE"],
    ids=lambda v: f"mode={v!r}",
)
async def test_require_ce_mode_raises_404_when_not_ce(mode_value: str):
    from giljo_mcp.auth.dependencies import require_ce_mode

    with patch("api.app_state.GILJO_MODE", mode_value), pytest.raises(HTTPException) as exc:
        await require_ce_mode()
    assert exc.value.status_code == 404, (
        f"require_ce_mode() returned status {exc.value.status_code} for mode "
        f"{mode_value!r}; expected 404 to hide route existence in non-CE modes."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode_value", ["ce", ""], ids=lambda v: f"mode={v!r}")
async def test_require_ce_mode_passes_when_ce(mode_value: str):
    from giljo_mcp.auth.dependencies import require_ce_mode

    with patch("api.app_state.GILJO_MODE", mode_value):
        result = await require_ce_mode()
    assert result is None




@pytest.mark.parametrize(
    ("method", "path_suffix"),
    [
        ("GET", "/frontend"),
    ],
    ids=str,
)
def test_tenant_scoped_configuration_endpoint_is_not_ce_gated(method: str, path_suffix: str):
    from giljo_mcp.auth.dependencies import require_ce_mode

    router = _import_configuration_router()
    route = _find_route(router, method, path_suffix)
    assert not _route_has_dependency(route, require_ce_mode), (
        f"{method} /api/v1/config{path_suffix} is tenant-scoped (lane-(a)) and "
        "MUST NOT depend on require_ce_mode -- doing so breaks demo/SaaS admins."
    )


@pytest.mark.parametrize(
    ("method", "path_suffix"),
    [
        ("GET", "/system/agent-silence-threshold"),
        ("PUT", "/system/agent-silence-threshold"),
    ],
    ids=str,
)
def test_agent_silence_threshold_endpoint_is_not_ce_gated(method: str, path_suffix: str):
    from api.endpoints import settings
    from giljo_mcp.auth.dependencies import require_ce_mode

    route = _find_route(settings.router, method, path_suffix)
    assert not _route_has_dependency(route, require_ce_mode), (
        f"{method} /api/v1/settings{path_suffix} must NOT depend on require_ce_mode -- "
        "it is reachable in both CE and SaaS (FE-9241 edition branch inside the handler)."
    )
