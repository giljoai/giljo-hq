# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from fastapi import FastAPI

import api.app as app_module
from api.wiring.routers import register_routers
from tests.helpers.route_surface import iter_effective_routes


_LOG_PATHS = frozenset(
    {
        "/api/download/logs/current",
        "/api/download/logs/archives",
        "/api/download/logs/archive/{filename}",
    }
)


def _registered_paths(*, giljo_mode: str, monkeypatch) -> set[str]:
    monkeypatch.setattr(app_module, "GILJO_MODE", giljo_mode)
    app = FastAPI()
    register_routers(app)
    return {route.path for route in iter_effective_routes(app.routes)}


def test_log_routes_present_in_ce_and_absent_in_saas_same_process(monkeypatch):
    ce_paths = _registered_paths(giljo_mode="", monkeypatch=monkeypatch)
    assert ce_paths >= _LOG_PATHS, f"CE build missing log routes: {sorted(_LOG_PATHS - ce_paths)}"

    saas_paths = _registered_paths(giljo_mode="saas", monkeypatch=monkeypatch)
    leaked = _LOG_PATHS & saas_paths
    assert not leaked, f"SaaS build exposed CE-only log routes: {sorted(leaked)}"


def test_ce_string_and_empty_both_include_log_routes(monkeypatch):
    assert _registered_paths(giljo_mode="", monkeypatch=monkeypatch) >= _LOG_PATHS
    assert _registered_paths(giljo_mode="ce", monkeypatch=monkeypatch) >= _LOG_PATHS


def test_log_router_defined_unconditionally_at_import():
    from api.endpoints import downloads

    assert hasattr(downloads, "log_router"), "downloads.log_router must be defined unconditionally"
    log_router_paths = {route.path for route in downloads.log_router.routes}
    assert log_router_paths >= _LOG_PATHS, f"log_router missing routes: {sorted(_LOG_PATHS - log_router_paths)}"
