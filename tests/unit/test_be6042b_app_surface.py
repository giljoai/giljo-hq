# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect

import pytest

from tests.helpers.route_surface import iter_effective_routes, route_signatures



EXPECTED_MIDDLEWARE_ORDER = (
    "CORSMiddleware",
    "CSRFProtectionMiddleware",
    "InputValidationMiddleware",
    "SecurityHeadersMiddleware",
    "RateLimitMiddleware",
    "AuthMiddleware",
    "APIMetricsMiddleware",
)

EXPECTED_ROUTE_SIGNATURES = frozenset(
    {
        ("/health", frozenset({"GET"})),
        ("/api/system/status", frozenset({"GET"})),
        ("/ws/{client_id}", frozenset()),
        ("/docs", frozenset({"GET", "HEAD"})),
        ("/openapi.json", frozenset({"GET", "HEAD"})),
    }
)

EXPECTED_ROUTE_COUNT = 261

EXPECTED_FULL_ROUTE_SIGNATURES = frozenset(
    {
        ("", frozenset()),
        ("/.well-known/mcp-server-info", frozenset({"GET"})),
        ("/.well-known/openai-apps-challenge", frozenset({"GET"})),
        ("/.well-known/oauth-authorization-server", frozenset({"GET"})),
        ("/.well-known/oauth-protected-resource", frozenset({"GET"})),
        ("/.well-known/oauth-protected-resource/{resource_path:path}", frozenset({"GET"})),
        ("/.well-known/openid-configuration", frozenset({"GET"})),
        ("/api/agent-jobs/", frozenset({"GET"})),
        ("/api/agent-jobs/launch-project", frozenset({"POST"})),
        ("/api/agent-jobs/projects/{project_id}/launch-implementation", frozenset({"PATCH"})),
        ("/api/agent-jobs/spawn", frozenset({"POST"})),
        ("/api/agent-jobs/{job_id}", frozenset({"GET"})),
        ("/api/agent-jobs/{job_id}/messages", frozenset({"GET"})),
        ("/api/approvals/", frozenset({"GET"})),
        ("/api/approvals/{approval_id}/decide", frozenset({"POST"})),
        ("/api/auth/api-keys", frozenset({"GET"})),
        ("/api/auth/api-keys", frozenset({"POST"})),
        ("/api/auth/api-keys/active", frozenset({"GET"})),
        ("/api/auth/api-keys/{key_id}", frozenset({"DELETE"})),
        ("/api/auth/check-first-login", frozenset({"POST"})),
        ("/api/auth/complete-first-login", frozenset({"POST"})),
        ("/api/auth/create-first-admin", frozenset({"POST"})),
        ("/api/auth/login", frozenset({"POST"})),
        ("/api/auth/logout", frozenset({"POST"})),
        ("/api/auth/me", frozenset({"GET"})),
        ("/api/auth/me/setup-state", frozenset({"PATCH"})),
        ("/api/auth/refresh", frozenset({"POST"})),
        ("/api/auth/register", frozenset({"POST"})),
        ("/api/auth/verify-pin", frozenset({"POST"})),
        ("/api/auth/verify-pin-and-reset-password", frozenset({"POST"})),
        ("/api/connect/connections/{harness}", frozenset({"DELETE"})),
        ("/api/connect/credential-status", frozenset({"GET"})),
        ("/api/download/bootstrap-prompt", frozenset({"GET"})),
        ("/api/download/generate-token", frozenset({"POST"})),
        ("/api/download/install-script.{extension}", frozenset({"GET"})),
        ("/api/download/logs/archive/{filename}", frozenset({"GET"})),
        ("/api/download/logs/archives", frozenset({"GET"})),
        ("/api/download/logs/current", frozenset({"GET"})),
        ("/api/download/slash-commands.zip", frozenset({"GET"})),
        ("/api/download/temp/{token}/{filename}", frozenset({"GET"})),
        ("/api/git/settings", frozenset({"GET"})),
        ("/api/git/settings", frozenset({"POST"})),
        ("/api/git/toggle", frozenset({"POST"})),
        ("/api/jobs/{job_id}/mission", frozenset({"PATCH"})),
        ("/api/notifications", frozenset({"GET"})),
        ("/api/notifications/{notification_id}/dismiss", frozenset({"PATCH"})),
        ("/api/notifications/{notification_id}/read", frozenset({"PATCH"})),
        ("/api/oauth/.well-known/oauth-authorization-server", frozenset({"GET"})),
        ("/api/oauth/authorize", frozenset({"POST"})),
        ("/api/oauth/authorize/deny", frozenset({"POST"})),
        ("/api/oauth/refresh", frozenset({"POST"})),
        ("/api/oauth/register", frozenset({"POST"})),
        ("/api/oauth/revoke", frozenset({"POST"})),
        ("/api/oauth/token", frozenset({"POST"})),
        ("/api/organizations", frozenset({"GET"})),
        ("/api/organizations", frozenset({"POST"})),
        ("/api/organizations/{org_id}", frozenset({"DELETE"})),
        ("/api/organizations/{org_id}", frozenset({"GET"})),
        ("/api/organizations/{org_id}", frozenset({"PUT"})),
        ("/api/organizations/{org_id}/members", frozenset({"GET"})),
        ("/api/organizations/{org_id}/members", frozenset({"POST"})),
        ("/api/organizations/{org_id}/members/{user_id}", frozenset({"DELETE"})),
        ("/api/organizations/{org_id}/members/{user_id}", frozenset({"PUT"})),
        ("/api/organizations/{org_id}/transfer", frozenset({"POST"})),
        ("/api/serena/settings", frozenset({"GET"})),
        ("/api/serena/status", frozenset({"GET"})),
        ("/api/serena/toggle", frozenset({"POST"})),
        ("/api/setup/status", frozenset({"GET"})),
        ("/api/slash/execute", frozenset({"POST"})),
        ("/api/system/status", frozenset({"GET"})),
        ("/api/v1/account/export", frozenset({"POST"})),
        ("/api/v1/config/", frozenset({"GET"})),
        ("/api/v1/config/database", frozenset({"GET"})),
        ("/api/v1/config/frontend", frozenset({"GET"})),
        ("/api/v1/config/health/database", frozenset({"GET"})),
        ("/api/v1/config/network-info", frozenset({"GET"})),
        ("/api/v1/config/root-ca", frozenset({"GET"})),
        ("/api/v1/config/ssl", frozenset({"GET"})),
        ("/api/v1/config/ssl", frozenset({"POST"})),
        ("/api/v1/config/ssl/cert/reference", frozenset({"POST"})),
        ("/api/v1/config/ssl/cert/upload", frozenset({"POST"})),
        ("/api/v1/products/", frozenset({"GET"})),
        ("/api/v1/products/", frozenset({"POST"})),
        ("/api/v1/products/active/vision-stats", frozenset({"GET"})),
        ("/api/v1/products/deleted", frozenset({"GET"})),
        ("/api/v1/products/refresh-active", frozenset({"GET"})),
        ("/api/v1/products/{product_id}", frozenset({"DELETE"})),
        ("/api/v1/products/{product_id}", frozenset({"GET"})),
        ("/api/v1/products/{product_id}", frozenset({"PUT"})),
        ("/api/v1/products/{product_id}/activate", frozenset({"POST"})),
        ("/api/v1/products/{product_id}/agent-assignments", frozenset({"GET"})),
        ("/api/v1/products/{product_id}/agent-assignments/{template_id}", frozenset({"PUT"})),
        ("/api/v1/products/{product_id}/cascade-impact", frozenset({"GET"})),
        ("/api/v1/products/{product_id}/context_update_project", frozenset({"GET"})),
        ("/api/v1/products/{product_id}/deactivate", frozenset({"POST"})),
        ("/api/v1/products/{product_id}/memory-entries", frozenset({"GET"})),
        ("/api/v1/products/{product_id}/purge", frozenset({"DELETE"})),
        ("/api/v1/products/{product_id}/restore", frozenset({"POST"})),
        ("/api/v1/products/{product_id}/set-default", frozenset({"POST"})),
        ("/api/v1/products/{product_id}/tuning/generate-prompt", frozenset({"POST"})),
        ("/api/v1/products/{product_id}/tuning/sections", frozenset({"GET"})),
        ("/api/v1/products/{product_id}/vision", frozenset({"GET"})),
        ("/api/v1/products/{product_id}/vision", frozenset({"POST"})),
        ("/api/v1/products/{product_id}/vision-chunks", frozenset({"GET"})),
        ("/api/v1/products/{product_id}/vision/{doc_id}", frozenset({"DELETE"})),
        ("/api/v1/project-statuses/", frozenset({"GET"})),
        ("/api/v1/projects/", frozenset({"GET"})),
        ("/api/v1/projects/", frozenset({"POST"})),
        ("/api/v1/projects/active", frozenset({"GET"})),
        ("/api/v1/projects/available-series", frozenset({"GET"})),
        ("/api/v1/projects/check-series", frozenset({"GET"})),
        ("/api/v1/projects/deleted", frozenset({"DELETE"})),
        ("/api/v1/projects/deleted", frozenset({"GET"})),
        ("/api/v1/projects/next-series", frozenset({"GET"})),
        ("/api/v1/projects/used-subseries", frozenset({"GET"})),
        ("/api/v1/projects/{project_id}", frozenset({"DELETE"})),
        ("/api/v1/projects/{project_id}", frozenset({"GET"})),
        ("/api/v1/projects/{project_id}", frozenset({"PATCH"})),
        ("/api/v1/projects/{project_id}/activate", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/archive", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/cancel", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/cancel-staging", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/complete", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/continue-working", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/closeout-without-summary", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/deactivate", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/launch", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/orchestrator", frozenset({"GET"})),
        ("/api/v1/projects/{project_id}/purge", frozenset({"DELETE"})),
        ("/api/v1/projects/{project_id}/reset", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/restage", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/restore", frozenset({"POST"})),
        ("/api/v1/projects/{project_id}/review", frozenset({"GET"})),
        ("/api/v1/projects/{project_id}/summary", frozenset({"GET"})),
        ("/api/v1/projects/{project_id}/unstage", frozenset({"POST"})),
        ("/api/v1/prompts/agent/{agent_id}", frozenset({"GET"})),
        ("/api/v1/prompts/chain-implementation/{run_id}", frozenset({"GET"})),
        ("/api/v1/prompts/chain-member/{project_id}", frozenset({"GET"})),
        ("/api/v1/prompts/chain-staging/{run_id}", frozenset({"GET"})),
        ("/api/v1/prompts/implementation/{project_id}", frozenset({"GET"})),
        ("/api/v1/prompts/prompts/orchestrator-thin", frozenset({"POST"})),
        ("/api/v1/prompts/staging/{project_id}", frozenset({"GET"})),
        ("/api/v1/roadmap", frozenset({"GET"})),
        ("/api/v1/roadmap/items/{item_id}", frozenset({"DELETE"})),
        ("/api/v1/roadmap/reorder", frozenset({"PATCH"})),
        ("/api/v1/sequence-runs", frozenset({"GET"})),
        ("/api/v1/sequence-runs", frozenset({"POST"})),
        ("/api/v1/sequence-runs/{run_id}", frozenset({"GET"})),
        ("/api/v1/sequence-runs/{run_id}", frozenset({"PATCH"})),
        ("/api/v1/sequence-runs/{run_id}/deactivate", frozenset({"POST"})),
        ("/api/v1/sequence-runs/{run_id}/stop", frozenset({"POST"})),
        ("/api/v1/sequence-runs/{run_id}/members/{project_id}", frozenset({"DELETE"})),
        ("/api/v1/sequence-runs/{run_id}/members/{project_id}/review", frozenset({"POST"})),
        ("/api/v1/sequence-runs/{run_id}/release", frozenset({"POST"})),
        ("/api/v1/settings/database", frozenset({"GET"})),
        ("/api/v1/settings/execution-mode-default", frozenset({"GET"})),
        ("/api/v1/settings/execution-mode-default", frozenset({"PUT"})),
        ("/api/v1/settings/closeout-mode", frozenset({"PUT"})),
        ("/api/v1/settings/handover-template", frozenset({"GET"})),
        ("/api/v1/settings/handover-template", frozenset({"PUT"})),
        ("/api/v1/settings/handover-template/reset", frozenset({"POST"})),
        ("/api/v1/settings/general", frozenset({"GET"})),
        ("/api/v1/settings/general", frozenset({"PUT"})),
        ("/api/v1/settings/system/agent-checkin-cadence", frozenset({"GET"})),
        ("/api/v1/settings/system/agent-checkin-cadence", frozenset({"PUT"})),
        ("/api/v1/settings/system/agent-silence-threshold", frozenset({"GET"})),
        ("/api/v1/settings/system/agent-silence-threshold", frozenset({"PUT"})),
        ("/api/v1/stats/call-counts", frozenset({"GET"})),
        ("/api/v1/stats/dashboard", frozenset({"GET"})),
        ("/api/v1/stats/mcp-tool-calls", frozenset({"GET"})),
        ("/api/v1/stats/system", frozenset({"GET"})),
        ("/api/v1/system/orchestrator-prompt", frozenset({"GET"})),
        ("/api/v1/system/orchestrator-prompt", frozenset({"PUT"})),
        ("/api/v1/system/orchestrator-prompt/reset", frozenset({"POST"})),
        ("/api/v1/task-statuses/", frozenset({"GET"})),
        ("/api/v1/tasks/", frozenset({"GET"})),
        ("/api/v1/tasks/", frozenset({"POST"})),
        ("/api/v1/tasks/deleted", frozenset({"GET"})),
        ("/api/v1/tasks/deleted/", frozenset({"GET"})),
        ("/api/v1/tasks/summary", frozenset({"GET"})),
        ("/api/v1/tasks/summary/", frozenset({"GET"})),
        ("/api/v1/tasks/{task_id}", frozenset({"DELETE"})),
        ("/api/v1/tasks/{task_id}", frozenset({"PATCH"})),
        ("/api/v1/tasks/{task_id}/", frozenset({"DELETE"})),
        ("/api/v1/tasks/{task_id}/", frozenset({"GET"})),
        ("/api/v1/tasks/{task_id}/", frozenset({"PUT"})),
        ("/api/v1/tasks/{task_id}/convert", frozenset({"POST"})),
        ("/api/v1/tasks/{task_id}/convert/", frozenset({"POST"})),
        ("/api/v1/tasks/{task_id}/restore", frozenset({"POST"})),
        ("/api/v1/tasks/{task_id}/restore/", frozenset({"POST"})),
        ("/api/v1/tasks/{task_id}/status/", frozenset({"PATCH"})),
        ("/api/v1/taxonomy-types/", frozenset({"GET"})),
        ("/api/v1/taxonomy-types/", frozenset({"POST"})),
        ("/api/v1/taxonomy-types/{type_id}", frozenset({"DELETE"})),
        ("/api/v1/taxonomy-types/{type_id}", frozenset({"PUT"})),
        ("/api/v1/templates/", frozenset({"GET"})),
        ("/api/v1/templates/", frozenset({"POST"})),
        ("/api/v1/templates/import-defaults", frozenset({"POST"})),
        ("/api/v1/templates/stats/active-count", frozenset({"GET"})),
        ("/api/v1/templates/{template_id}", frozenset({"DELETE"})),
        ("/api/v1/templates/{template_id}", frozenset({"GET"})),
        ("/api/v1/templates/{template_id}", frozenset({"PUT"})),
        ("/api/v1/templates/{template_id}/profile.md", frozenset({"GET"})),
        ("/api/v1/templates/{template_id}/history", frozenset({"GET"})),
        ("/api/v1/templates/{template_id}/preview/", frozenset({"POST"})),
        ("/api/v1/templates/{template_id}/reset", frozenset({"POST"})),
        ("/api/v1/templates/reset-all", frozenset({"POST"})),
        ("/api/v1/templates/{template_id}/reset-system", frozenset({"POST"})),
        ("/api/v1/templates/{template_id}/restore", frozenset({"POST"})),
        ("/api/v1/templates/{template_id}/restore/{archive_id}", frozenset({"POST"})),
        ("/api/v1/threads", frozenset({"GET"})),
        ("/api/v1/threads", frozenset({"POST"})),
        ("/api/v1/threads/chain-hub", frozenset({"GET"})),
        ("/api/v1/threads/deleted", frozenset({"GET"})),
        ("/api/v1/threads/attention", frozenset({"GET"})),
        ("/api/v1/threads/my-turn", frozenset({"GET"})),
        ("/api/v1/threads/search", frozenset({"GET"})),
        ("/api/v1/threads/{thread_id}", frozenset({"GET"})),
        ("/api/v1/threads/{thread_id}", frozenset({"DELETE"})),
        ("/api/v1/threads/{thread_id}", frozenset({"PATCH"})),
        ("/api/v1/threads/{thread_id}/baton", frozenset({"POST"})),
        ("/api/v1/threads/{thread_id}/participants", frozenset({"GET"})),
        ("/api/v1/threads/{thread_id}/post", frozenset({"POST"})),
        ("/api/v1/threads/{thread_id}/read", frozenset({"POST"})),
        ("/api/v1/threads/{thread_id}/restore", frozenset({"POST"})),
        ("/api/v1/user/settings/cookie-domains", frozenset({"DELETE"})),
        ("/api/v1/user/settings/cookie-domains", frozenset({"GET"})),
        ("/api/v1/user/settings/cookie-domains", frozenset({"POST"})),
        ("/api/v1/user/settings/headless-launch", frozenset({"GET"})),
        ("/api/v1/user/settings/headless-launch", frozenset({"PUT"})),
        ("/api/v1/users/", frozenset({"GET"})),
        ("/api/v1/users/", frozenset({"POST"})),
        ("/api/v1/users/me/context/depth", frozenset({"GET"})),
        ("/api/v1/users/me/context/depth", frozenset({"PUT"})),
        ("/api/v1/users/me/field-priority", frozenset({"GET"})),
        ("/api/v1/users/me/field-priority", frozenset({"PUT"})),
        ("/api/v1/users/me/field-priority/reset", frozenset({"POST"})),
        ("/api/v1/users/me/settings/notification-preferences", frozenset({"GET"})),
        ("/api/v1/users/me/settings/notification-preferences", frozenset({"PUT"})),
        ("/api/v1/users/{user_id}", frozenset({"DELETE"})),
        ("/api/v1/users/{user_id}", frozenset({"GET"})),
        ("/api/v1/users/{user_id}", frozenset({"PUT"})),
        ("/api/v1/users/{user_id}/force-logout", frozenset({"POST"})),
        ("/api/v1/users/{user_id}/password", frozenset({"PUT"})),
        ("/api/v1/users/{user_id}/role", frozenset({"PUT"})),
        ("/api/version/latest", frozenset({"GET"})),
        ("/api/vision-documents/", frozenset({"POST"})),
        ("/api/vision-documents/product/{product_id}", frozenset({"GET"})),
        ("/api/vision-documents/product/{product_id}/deleted", frozenset({"GET"})),
        ("/api/vision-documents/products/{product_id}/regenerate-consolidated", frozenset({"POST"})),
        ("/api/vision-documents/{document_id}", frozenset({"DELETE"})),
        ("/api/vision-documents/{document_id}", frozenset({"GET"})),
        ("/api/vision-documents/{document_id}", frozenset({"PUT"})),
        ("/api/vision-documents/{document_id}/ai-summary/{level}", frozenset({"GET"})),
        ("/api/vision-documents/{document_id}/restore", frozenset({"POST"})),
        ("/docs", frozenset({"GET", "HEAD"})),
        ("/docs/oauth2-redirect", frozenset({"GET", "HEAD"})),
        ("/health", frozenset({"GET"})),
        ("/openapi.json", frozenset({"GET", "HEAD"})),
        ("/redoc", frozenset({"GET", "HEAD"})),
        ("/ws/{client_id}", frozenset()),
    }
)

LOAD_BEARING_PUBLIC_SYMBOLS = (
    "app",
    "create_app",
    "lifespan",
    "_register_routers",
    "_configure_middleware",
    "_warm_up",
)


def _route_signatures(app) -> set[tuple[str, frozenset]]:
    return route_signatures(app.routes)


@pytest.fixture(scope="module")
def app():
    import api.app as app_module

    saved_mode = app_module.GILJO_MODE
    app_module.GILJO_MODE = ""
    saved_config = app_module.state.config
    app_module.state.config = None
    try:
        return app_module.create_app()
    finally:
        app_module.GILJO_MODE = saved_mode
        app_module.state.config = saved_config


def test_middleware_order_exactly_preserved(app):
    actual = tuple(m.cls.__name__ for m in app.user_middleware)
    assert actual == EXPECTED_MIDDLEWARE_ORDER


def test_representative_route_signatures_present(app):
    sigs = _route_signatures(app)
    for expected in EXPECTED_ROUTE_SIGNATURES:
        assert expected in sigs, f"missing route signature: {expected}"


def test_route_count_exactly_preserved(app):
    real_routes = list(iter_effective_routes(app.routes))
    assert len(real_routes) == EXPECTED_ROUTE_COUNT


SEC_9700_REMOVED_ROUTE_SIGNATURES = frozenset(
    {
        ("/api/setup/database/test-connection", frozenset({"POST"})),
        ("/api/setup/database/setup", frozenset({"POST"})),
        ("/api/setup/database/verify", frozenset({"GET"})),
    }
)


def test_database_setup_routes_removed(app):
    sigs = _route_signatures(app)
    resurrected = SEC_9700_REMOVED_ROUTE_SIGNATURES & sigs
    assert not resurrected, (
        f"SEC-9700 removed these unauthenticated database-setup routes; they "
        f"came back without an explicit decision to re-open that surface: {sorted(resurrected)}"
    )


def test_full_route_signature_set_equality(app):
    actual = _route_signatures(app)
    missing = EXPECTED_FULL_ROUTE_SIGNATURES - actual
    extra = actual - EXPECTED_FULL_ROUTE_SIGNATURES
    assert not missing, f"routes dropped by the split: {sorted(missing)}"
    assert not extra, f"routes added by the split: {sorted(extra)}"
    assert actual == EXPECTED_FULL_ROUTE_SIGNATURES


def test_route_table_has_no_duplicate_signatures(app):
    triples = []
    for route in iter_effective_routes(app.routes):
        path = route.path
        methods = tuple(sorted(getattr(route, "methods", None) or ()))
        name = getattr(route, "name", "")
        triples.append((path, methods, name))
    assert len(triples) == len(set(triples)), "duplicate route registration detected"


def test_lifespan_is_wired_and_callable(app):
    from api.app import lifespan

    assert app.router.lifespan_context is not None
    assert callable(lifespan)


def test_global_exception_handlers_registered(app):
    assert len(app.exception_handlers) > 0


def test_load_bearing_public_symbols_importable():
    import api.app as app_module

    for name in LOAD_BEARING_PUBLIC_SYMBOLS:
        assert hasattr(app_module, name), f"api.app dropped public symbol: {name}"


def test_register_and_configure_are_callables():
    from api.app import _configure_middleware, _register_routers

    assert callable(_register_routers)
    assert callable(_configure_middleware)


def test_warm_up_is_coroutine_function():
    from api.app import _warm_up

    assert inspect.iscoroutinefunction(_warm_up)


def test_gilijo_mode_resolves_through_api_app_namespace():
    import api.app as app_module

    assert hasattr(app_module, "GILJO_MODE")


def test_characterization_uses_isolated_app_not_global_singleton(app):
    import api.app as app_module

    assert app is not app_module.app, (
        "be6042b must characterize a fresh create_app() build, not the global "
        "api.app.app singleton (BE-6087) — reverting to the shared mutable global "
        "reintroduces the -n6 route-surface flake."
    )


def test_route_surface_hermetic_against_polluted_state_config(monkeypatch):
    from unittest.mock import MagicMock

    import api.app as app_module

    monkeypatch.setattr(app_module, "GILJO_MODE", "")
    spa_mount = ("", frozenset())

    monkeypatch.setattr(app_module.state, "config", MagicMock())
    polluted = _route_signatures(app_module.create_app())
    assert spa_mount not in polluted, (
        "expected a polluted state.config to drop the SPA mount — if this "
        "assertion fails the flake mechanism changed and this guard is stale."
    )

    monkeypatch.setattr(app_module.state, "config", None)
    pinned = _route_signatures(app_module.create_app())
    assert spa_mount in pinned, (
        "the single-port SPA static Mount vanished even with state.config pinned "
        "to None — the be6042b `app` fixture must pin state.config for a "
        "deterministic route surface."
    )
