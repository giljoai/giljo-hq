# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.routing import Match, Mount

from api.app import _install_spa_fallback


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_API = REPO_ROOT / "frontend" / "src" / "services" / "agentsApi.js"

_API_CALL = re.compile(r"apiClient\.(get|post|put|patch|delete)\(\s*[`'\"]([^`'\"]+)[`'\"]")
_TEMPLATE_PARAM = re.compile(r"\$\{[^}]+\}")


def frontend_calls(source: str) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    for method, path in _API_CALL.findall(source):
        params = _TEMPLATE_PARAM.findall(path)
        concrete = path
        for index, param in enumerate(params, start=1):
            concrete = concrete.replace(param, f"x{index}", 1)
        calls.append((method.upper(), concrete))
    return calls


def first_full_match(app, method: str, path: str):
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "headers": [], "query_string": b""}
    for route in app.router.routes:
        match, _child = route.matches(scope)
        if match == Match.FULL:
            return route
    return None


@pytest.fixture(scope="module")
def spa_app(tmp_path_factory):
    import api.app as app_module

    saved_mode, saved_config = app_module.GILJO_MODE, app_module.state.config
    app_module.GILJO_MODE = ""
    app_module.state.config = None
    try:
        app = app_module.create_app()
    finally:
        app_module.GILJO_MODE = saved_mode
        app_module.state.config = saved_config

    dist = tmp_path_factory.mktemp("dist")
    (dist / "index.html").write_text("<!doctype html><title>giljo-spa</title>")
    _install_spa_fallback(app, dist)
    assert isinstance(app.router.routes[-1], Mount), "the SPA mount must be the last route"
    return app


def test_agents_api_file_has_calls():
    calls = frontend_calls(AGENTS_API.read_text(encoding="utf-8"))
    assert ("POST", "/api/v1/templates/x1/reset") in calls or ("POST", "/api/v1/templates/x1/reset/") in calls
    assert len(calls) >= 15


@pytest.mark.parametrize(("method", "path"), frontend_calls(AGENTS_API.read_text(encoding="utf-8")))
def test_frontend_template_path_resolves_to_an_api_route_under_the_spa_mount(spa_app, method, path):
    route = first_full_match(spa_app, method, path)
    assert route is not None, f"{method} {path}: nothing matches"
    assert not isinstance(route, Mount), (
        f"{method} {path} is answered by the SPA static mount ({route.name!r}), not by an API route. "
        "In single-port mode that is a 404/405 from StaticFiles. Make the frontend path match the "
        "route exactly (usually: drop the trailing slash in frontend/src/services/agentsApi.js)."
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/v1/templates/x1/reset/"), ("GET", "/api/v1/templates/x1/history/")],
)
def test_a_trailing_slash_on_a_slashless_route_is_swallowed_by_the_mount(spa_app, method, path):
    route = first_full_match(spa_app, method, path)
    assert isinstance(route, Mount) and route.name == "static"
    assert not isinstance(first_full_match(spa_app, method, path.rstrip("/")), Mount)
