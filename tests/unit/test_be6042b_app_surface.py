# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-6042b characterization test — locks the wired surface of ``api/app.py``.

This suite is the behavior lock for the mechanical wiring split of
``api/app.py`` into an ``api/wiring/`` subpackage. It runs GREEN against the
unmodified assembler FIRST, then unchanged against the split package. It
asserts the things a behavior-preserving extraction must keep byte-for-byte
identical:

- The FULL route table: the set of ``(path, frozenset(methods))`` over
  ``app.routes`` is EXACTLY preserved (catches a dropped, duplicated, renamed,
  or reordered router — the one real failure mode of a wiring split).
- The ordered middleware class stack is EXACTLY preserved (middleware order is
  security-load-bearing: CORS first, metrics last).
- The startup/lifespan callable + the global exception-handler wiring are
  present.
- The load-bearing public symbols that other modules import from ``api.app``
  (``_register_routers``, ``_configure_middleware``, ``_warm_up``, ``lifespan``,
  ``create_app``, ``app``) remain importable from ``api.app`` after the split.

The baselines below were snapshotted from the UNMODIFIED ``api/app.py`` (257
routes, 7 middleware) on branch feature/be-6042-backend-splits. They are frozen
on purpose: re-deriving them from the same ``app`` object the test inspects
would make the assertions tautological and unable to catch a regression.

The route baselines were since bumped from 257 -> 259 to admit the two
intentional, Patrik-approved Roadmap routes (FE-6022a): ``GET /api/v1/roadmap``
and ``PATCH /api/v1/roadmap/reorder``, then 259 -> 260 for the FE-6022c-polish
remove route ``DELETE /api/v1/roadmap/items/{item_id}``. The middleware stack is
unchanged.
"""

from __future__ import annotations

import inspect

import pytest

from tests.helpers.route_surface import iter_effective_routes, route_signatures


# ---------------------------------------------------------------------------
# Frozen baselines (snapshotted from the unmodified app.py — DO NOT regenerate
# from the live app object; that would defeat the characterization).
# ---------------------------------------------------------------------------

# The ordered middleware class stack as reported by ``app.user_middleware``.
# Order is reverse-of-execution (last added executes first): CORS is added last
# so it executes first to answer OPTIONS preflight; APIMetrics is added first so
# it executes last (needs tenant_key set by AuthMiddleware).
EXPECTED_MIDDLEWARE_ORDER = (
    "CORSMiddleware",
    "CSRFProtectionMiddleware",
    "InputValidationMiddleware",
    "SecurityHeadersMiddleware",
    "RateLimitMiddleware",
    "AuthMiddleware",
    "APIMetricsMiddleware",
)

# A representative, load-bearing slice of the route table that MUST survive the
# split verbatim. These are not the full 257 — the full set is asserted for
# set-equality against a same-process snapshot in
# ``test_route_table_has_no_duplicate_signatures`` and pinned by count below.
EXPECTED_ROUTE_SIGNATURES = frozenset(
    {
        ("/health", frozenset({"GET"})),
        ("/api/system/status", frozenset({"GET"})),
        ("/ws/{client_id}", frozenset()),  # WebSocketRoute has no .methods
        ("/docs", frozenset({"GET", "HEAD"})),
        ("/openapi.json", frozenset({"GET", "HEAD"})),
    }
)

# Total registered route count (CE mode, no frontend dist present in the test
# tree). A wiring split must not change this; bumped 257 -> 259 for the two
# intentional Roadmap routes (FE-6022a), then 259 -> 260 for the FE-6022c-polish
# remove route (DELETE /api/v1/roadmap/items/{item_id}), then 260 -> 259 for
# INF-3012 deletion of the broken /api/network/detect-ip endpoint, then 259 ->
# 257 for BE-6073 (m14) deletion of the two dead message endpoints
# (GET /api/v1/messages/agent/{agent_name}, POST /api/v1/messages/{message_id}/complete),
# then 257 -> 255 for BE-6060c moving /mcp + /mcp/ off the FastAPI route table onto the
# top-level McpDispatcher (api/mcp_dispatcher.py) above the middleware onion.
# then 255 -> 263 for FE-6054ef Agent Message Hub UI REST bridge
# (8 /api/v1/threads routes over the existing CommThreadService).
# then 263 -> 264 for BE-6115b Mission Control multi-project roster read
# (GET /api/agent-jobs/mission-control/roster).
# then 264 -> 265 for FE-6130 Hub thread soft-delete
# (DELETE /api/v1/threads/{thread_id}).
# then 265 -> 276 for the trash/recover + sequential-runner surface that landed
# across #118-#128 without bumping this guard (INF-6132): BE-6131a sequence-runs
# (3 routes) + BE-6130b/FE-6138 tasks/threads/vision-documents deleted+restore
# (8 routes). All legitimately-shipped endpoints; baseline brought back in sync.
# then 276 -> 277 for BE-6137 AgentTemplate soft-delete/recover: the new restore
# endpoint POST /api/v1/templates/{template_id}/restore (TSK-6145 renamed the
# verb from /recover to /restore for trash-surface consistency; count unchanged).
# then 277 -> 279 for BE-6165e chain lifecycle endpoints: the durable-election
# read-back GET /api/v1/sequence-runs and the release verb
# POST /api/v1/sequence-runs/{run_id}/release.
# then 279 -> 281 for BE-6165d chain prompt endpoints: the two conductor
# kickoff-prompt reads GET /api/v1/prompts/chain-staging/{run_id} and
# GET /api/v1/prompts/chain-implementation/{run_id}.
# then 281 -> 282 for FE-6171 chain member-remove: the granular-removal verb
# DELETE /api/v1/sequence-runs/{run_id}/members/{project_id}.
# then 284 -> 285 for BE-6235 CE OAuth DCR: CE now mounts (and advertises) its own
# Dynamic Client Registration endpoint POST /api/oauth/register. (The prior 282 ->
# 284 step landed without bumping this guard; baseline brought back in sync here.)
# then 285 -> 287 for INF-6236 bring-your-own-cert HTTPS UX: the two re-homed cert
# routes POST /api/v1/config/ssl/cert/upload and POST /api/v1/config/ssl/cert/reference.
# then 287 -> 288 for FE-6239 Network settings UX: GET /api/v1/config/network-info
# (reports the real responding Host IP(s) + Port for the simplified Network tab).
# then 288 -> 289 for SEC-6011 forced-logout: POST /api/v1/users/{user_id}/force-logout
# (admin-scoped; bumps the target user's token_revocation_epoch to invalidate all
# their outstanding access tokens at once).
# then 289 -> 288 for BE-8000g item 3: dead-code removal of the Mission Control
# roster route (GET /api/agent-jobs/mission-control/roster) -- Mission Control
# was retired by FE-6174c and the route had no remaining caller.
# then 288 -> 284 for BE-9000a: deletion of the dead MCP-installer endpoint
# file (api/endpoints/mcp_installer.py, 4 routes with no remaining caller).
# then 284 -> 266 for BE-9000b: deletion of 18 dead routes with no remaining
# caller across statistics.py (6), configuration.py (8, incl. PATCH / whose
# handler was inoperative -- ConfigManager has no set()), settings.py (4,
# superseded by configuration.py's network-info/ssl).
# then 266 -> 262 for BE-9012d: deletion of the bus REST layer
# (api/endpoints/messages.py hard-removed, 4 routes: GET/POST /api/v1/messages/,
# POST /api/v1/messages/send, POST /api/v1/messages/broadcast) -- zero remaining
# frontend consumer (the Hub replaced it).
# then 262 -> 264 for BE-9084 Headless-vs-HITL toggle: the account-wide toggle
# read/write pair GET/PUT /api/v1/user/settings/headless-launch.
# then 264 -> 265 for BE-9098 chain review-badge persistence: the durable per-member
# review-ack write POST /api/v1/sequence-runs/{run_id}/members/{project_id}/review.
# then 265 -> 263 for BE-9103: removed the dead legacy product-level git-integration
# GET+POST (/api/v1/products/{product_id}/git-integration); the canonical toggle is
# /api/git/toggle (settings integrations.git_integration).
# then 263 -> 244 for BE-9143: retired 19 registered-but-dead REST routes with no
# remaining caller (verify-each-then-delete): ai_tools /supported +
# /config-generator/{tool} (+/markdown); notifications /check-skills-version;
# network /adapters; claude_export /export/claude-code; projects.completion
# /can-close + /generate-closeout + /closeout (GET) + /close-out; agent_jobs
# /{id}/complete + /{id}/error + /{id}/progress + /pending + /{id}/mission (GET) +
# /workflow/{id} + /{id}/executions + /{id}/clear-silent + /jobs/{id}/health.
# then 244 -> 245 for FE-9203 "Add default agents": the additive default-template
# import verb POST /api/v1/templates/import-defaults.
# then 245 -> 246 for FE-9274 "Connect configured-state": the additive read-only
# GET /api/connect/credential-status endpoint.
# then 246 -> 247 for BE-9289b "thread API for Quiet Cards": the additive
# PATCH /api/v1/threads/{thread_id} — the operator's rename + set-status verb. A
# thread could previously only be named at CREATE time, and status moved only as a
# side effect of an agent posting.
EXPECTED_ROUTE_COUNT = 247

# FULL frozen route-signature set — the STRICT set-equality lock. Snapshotted
# from the UNMODIFIED 1,237-line api/app.py (git HEAD~1, the BE-6042a pilot) and
# verified set-equal to the post-split assembler. ``test_full_route_signature_set_equality``
# asserts the live app produces EXACTLY this set: any dropped, added, renamed,
# shadowed, or method-shifted route fails — the one real failure mode of a
# wiring split. This is the authoritative behavior lock; the count + representative
# checks below are redundant fast guards.
EXPECTED_FULL_ROUTE_SIGNATURES = frozenset(
    {
        ("", frozenset()),
        ("/.well-known/mcp-server-info", frozenset({"GET"})),
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
        ("/api/agent-jobs/{job_id}/simple-handover", frozenset({"POST"})),
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
        ("/api/connect/credential-status", frozenset({"GET"})),
        ("/api/download/agent-templates.zip", frozenset({"GET"})),
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
        ("/api/setup/database/setup", frozenset({"POST"})),
        ("/api/setup/database/test-connection", frozenset({"POST"})),
        ("/api/setup/database/verify", frozenset({"GET"})),
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
        # BE-9103: legacy product-level /git-integration (GET+POST) removed — the
        # canonical toggle is /api/git/toggle (settings integrations.git_integration).
        ("/api/v1/products/{product_id}/memory-entries", frozenset({"GET"})),
        ("/api/v1/products/{product_id}/purge", frozenset({"DELETE"})),
        ("/api/v1/products/{product_id}/restore", frozenset({"POST"})),
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
        ("/api/v1/prompts/chain-staging/{run_id}", frozenset({"GET"})),
        ("/api/v1/prompts/implementation/{project_id}", frozenset({"GET"})),
        ("/api/v1/prompts/orchestrator/{tool}", frozenset({"GET"})),
        ("/api/v1/prompts/prompts/orchestrator-thin", frozenset({"POST"})),
        ("/api/v1/prompts/staging/{project_id}", frozenset({"GET"})),
        ("/api/v1/prompts/termination/{project_id}", frozenset({"GET"})),
        ("/api/v1/roadmap", frozenset({"GET"})),
        ("/api/v1/roadmap/items/{item_id}", frozenset({"DELETE"})),
        ("/api/v1/roadmap/reorder", frozenset({"PATCH"})),
        ("/api/v1/sequence-runs", frozenset({"GET"})),
        ("/api/v1/sequence-runs", frozenset({"POST"})),
        ("/api/v1/sequence-runs/{run_id}", frozenset({"GET"})),
        ("/api/v1/sequence-runs/{run_id}", frozenset({"PATCH"})),
        ("/api/v1/sequence-runs/{run_id}/deactivate", frozenset({"POST"})),
        ("/api/v1/sequence-runs/{run_id}/members/{project_id}", frozenset({"DELETE"})),
        ("/api/v1/sequence-runs/{run_id}/members/{project_id}/review", frozenset({"POST"})),
        ("/api/v1/sequence-runs/{run_id}/release", frozenset({"POST"})),
        ("/api/v1/settings/database", frozenset({"GET"})),
        ("/api/v1/settings/general", frozenset({"GET"})),
        ("/api/v1/settings/general", frozenset({"PUT"})),
        ("/api/v1/settings/system/agent-silence-threshold", frozenset({"GET"})),
        ("/api/v1/settings/system/agent-silence-threshold", frozenset({"PUT"})),
        ("/api/v1/stats/call-counts", frozenset({"GET"})),
        ("/api/v1/stats/dashboard", frozenset({"GET"})),
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
        ("/api/v1/templates/{template_id}/history", frozenset({"GET"})),
        ("/api/v1/templates/{template_id}/preview/", frozenset({"POST"})),
        ("/api/v1/templates/{template_id}/reset", frozenset({"POST"})),
        ("/api/v1/templates/{template_id}/reset-system", frozenset({"POST"})),
        ("/api/v1/templates/{template_id}/restore", frozenset({"POST"})),
        ("/api/v1/templates/{template_id}/restore/{archive_id}", frozenset({"POST"})),
        ("/api/v1/threads", frozenset({"GET"})),
        ("/api/v1/threads", frozenset({"POST"})),
        ("/api/v1/threads/deleted", frozenset({"GET"})),
        ("/api/v1/threads/my-turn", frozenset({"GET"})),
        ("/api/v1/threads/search", frozenset({"GET"})),
        ("/api/v1/threads/{thread_id}", frozenset({"GET"})),
        ("/api/v1/threads/{thread_id}", frozenset({"DELETE"})),
        ("/api/v1/threads/{thread_id}", frozenset({"PATCH"})),  # BE-9289b: rename + status
        ("/api/v1/threads/{thread_id}/baton", frozenset({"POST"})),
        ("/api/v1/threads/{thread_id}/participants", frozenset({"GET"})),
        ("/api/v1/threads/{thread_id}/post", frozenset({"POST"})),
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

# Symbols other modules / tests import directly from ``api.app``. The split must
# keep every one of these resolvable from the ``api.app`` namespace.
LOAD_BEARING_PUBLIC_SYMBOLS = (
    "app",
    "create_app",
    "lifespan",
    "_register_routers",
    "_configure_middleware",
    "_warm_up",
)


def _route_signatures(app) -> set[tuple[str, frozenset]]:
    """Build the (path, frozenset(methods)) signature set over app.routes.

    Flattens fastapi 0.137 ``_IncludedRouter`` wrappers (see
    ``tests/helpers/route_surface``) so the signature set equals the pre-0.137
    flat-``app.routes`` set the frozen baseline was captured from.
    """
    return route_signatures(app.routes)


@pytest.fixture(scope="module")
def app():
    """A FRESHLY built CE FastAPI app (BE-6087 de-flake).

    This characterization must NOT inspect the process-global ``api.app.app``
    singleton. Under pytest-xdist ``-n6`` a test sharing this worker can mutate
    that singleton's surface (toggling ``api.app.GILJO_MODE`` then re-registering
    routers, or otherwise adding routes), so a STRICT route-set-equality lock on
    shared mutable global state flakes non-deterministically depending on worker
    scheduling. We build our OWN app via the exported ``create_app()`` factory
    with ``GILJO_MODE`` pinned to CE, so the surface is deterministic regardless
    of any co-scheduled test. The frozen baselines below remain the authoritative,
    non-tautological comparison — they are hard-coded constants, not re-derived
    from this object.

    ``create_app()`` returns the inner FastAPI app (the ``/mcp`` routes live on
    the top-level ``McpDispatcher`` wrapper, not on this table — consistent with
    the frozen baseline, which carries no ``/mcp`` route)."""
    import api.app as app_module

    # _register_routers / _configure_middleware read ``api.app.GILJO_MODE`` at
    # call time (documented in api/app.py). Pin CE for the build, then restore so
    # this fixture leaves no global side effect for any other test on the worker.
    saved_mode = app_module.GILJO_MODE
    app_module.GILJO_MODE = ""
    # TSK-9002: create_app() also reads the shared ``state.config`` global to
    # decide whether to mount the single-port SPA fallback (api/app.py:
    # ``dist_dir = state.config.get_nested("paths.static", ...) if state.config
    # else "frontend/dist"``). A co-scheduled test that leaves ``state.config``
    # set to a MagicMock/stub (e.g. tests/api/conftest.py) makes ``dist_dir``
    # resolve to a bogus path, so the ``("", frozenset())`` static Mount silently
    # vanishes and the strict set-equality lock flakes. Pin it to None so the
    # SPA-mount decision uses the deterministic default ``frontend/dist`` path,
    # matching the frozen baseline, then restore.
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


def test_full_route_signature_set_equality(app):
    """STRICT behavior lock: the live route table MUST equal the frozen baseline
    set captured from the pre-split api/app.py. Symmetric-difference reporting
    surfaces exactly which routes were dropped or added so a regression is
    diagnosable, not just a bare count mismatch."""
    actual = _route_signatures(app)
    missing = EXPECTED_FULL_ROUTE_SIGNATURES - actual
    extra = actual - EXPECTED_FULL_ROUTE_SIGNATURES
    assert not missing, f"routes dropped by the split: {sorted(missing)}"
    assert not extra, f"routes added by the split: {sorted(extra)}"
    assert actual == EXPECTED_FULL_ROUTE_SIGNATURES


def test_route_table_has_no_duplicate_signatures(app):
    """Strict surface guard: a wiring split must not drop, duplicate, or shadow
    a route. Paths legitimately repeat across methods, so we compare on the full
    (method, path, name) tuple — a true duplicate (same handler registered
    twice) collapses the set and fails the count check below."""
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
    """register_exception_handlers() wires global handlers — non-empty after build."""
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
    """The SaaS-loading tests patch ``api.app.GILJO_MODE`` and expect
    _register_routers / _configure_middleware to honor it. Guard that the symbol
    stays addressable on the api.app namespace after the split."""
    import api.app as app_module

    assert hasattr(app_module, "GILJO_MODE")


def test_characterization_uses_isolated_app_not_global_singleton(app):
    """BE-6087 de-flake regression: the surface lock MUST run against a freshly
    built ``create_app()`` instance, NOT the process-global ``api.app.app``
    singleton (a McpDispatcher) which a co-scheduled pytest-xdist test can mutate
    (GILJO_MODE toggle + router re-registration). A strict route-set-equality
    assertion on shared mutable global state flakes under ``-n6``. This guard
    fails if the ``app`` fixture is ever reverted to read the shared singleton."""
    import api.app as app_module

    assert app is not app_module.app, (
        "be6042b must characterize a fresh create_app() build, not the global "
        "api.app.app singleton (BE-6087) — reverting to the shared mutable global "
        "reintroduces the -n6 route-surface flake."
    )


def test_route_surface_hermetic_against_polluted_state_config(monkeypatch):
    """TSK-9002 de-flake regression: the route surface must be immune to a
    co-scheduled test leaving ``state.config`` set to a stub/MagicMock.

    ``create_app()`` gates the single-port SPA static ``Mount("/")`` on
    ``state.config`` — a leaked MagicMock resolves ``dist_dir`` to a bogus path,
    dropping the ``("", frozenset())`` route and breaking the strict
    set-equality lock. This test SIMULATES that pollution, then builds through
    the same ``state.config``-pinned path the ``app`` fixture uses, and asserts
    the static mount survives. It fails if the fixture stops isolating
    ``state.config``."""
    from unittest.mock import MagicMock

    import api.app as app_module

    monkeypatch.setattr(app_module, "GILJO_MODE", "")
    spa_mount = ("", frozenset())

    # Branch 1 — the BUG: a leaked MagicMock in state.config makes create_app()
    # resolve dist_dir to a bogus path, so the SPA static Mount silently drops.
    # This is exactly the -n6 route-surface flake (run showed
    # "routes dropped by the split: [('', frozenset())]").
    monkeypatch.setattr(app_module.state, "config", MagicMock())
    polluted = _route_signatures(app_module.create_app())
    assert spa_mount not in polluted, (
        "expected a polluted state.config to drop the SPA mount — if this "
        "assertion fails the flake mechanism changed and this guard is stale."
    )

    # Branch 2 — the FIX: pinning state.config to None (what the `app` fixture
    # now does) restores the deterministic default frontend/dist path, so the
    # mount is present and the frozen baseline matches.
    monkeypatch.setattr(app_module.state, "config", None)
    pinned = _route_signatures(app_module.create_app())
    assert spa_mount in pinned, (
        "the single-port SPA static Mount vanished even with state.config pinned "
        "to None — the be6042b `app` fixture must pin state.config for a "
        "deterministic route surface."
    )
