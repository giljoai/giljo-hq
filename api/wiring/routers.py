# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Router wiring extracted from api/app.py.

Behavior-preserving (BE-6042b): ``register_routers(app)`` includes every router
with the exact same prefixes, tags, and registration order as the original
module-level ``_register_routers``. Order matters — the SPA static mount in
``create_app`` is registered last so API routes win.

BE-6060c: /mcp is no longer wired here. The top-level ``McpDispatcher``
(api/mcp_dispatcher.py, installed above the FastAPI middleware onion in
api/app.py) intercepts ``/mcp`` and ``/mcp/`` BEFORE FastAPI sees them and
forwards them straight to the MCP ASGI app, unbuffered and with no 307
trailing-slash redirect. The response-buffering bridge route that used to live
here (a plain FastAPI route, deliberately not a Mount to dodge the 307 trap)
was deleted — the dispatcher handles both the redirect-avoidance and the
streaming the bridge could not.

The SaaS gate reads ``GILJO_MODE`` from the ``api.app`` module namespace at call
time so existing tests patching ``api.app.GILJO_MODE`` keep driving the
conditional.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

from api.endpoints import (
    agent_jobs,
    approvals,
    auth,
    auth_pin_recovery,
    comm_threads,
    configuration,
    connect,
    database_setup,
    downloads,
    git,
    master_prompt,
    notifications,
    oauth,
    oauth_register,
    oauth_revoke,
    oauth_well_known,
    products,
    project_statuses,
    projects,
    prompts,
    roadmap,
    sequence_runs,
    serena,
    settings,
    setup_security,
    slash_commands,
    statistics,
    system_prompts,
    task_statuses,
    tasks,
    taxonomy_types,
    templates,
    tenant_data,
    user_settings,
    users,
    version,
    vision_documents,
)
from api.endpoints.organizations import crud as org_crud
from api.endpoints.organizations import members as org_members


logger = logging.getLogger("api.app")


def register_routers(app: FastAPI) -> None:
    """Register all API routers on the FastAPI application.

    Includes routers for projects, agents, tasks, configuration,
    MCP endpoints, organizations, and other feature modules.
    """
    # GILJO_MODE is resolved through the api.app namespace at call time so that
    # tests patching ``api.app.GILJO_MODE`` continue to drive the SaaS gate.
    import api.app as _app_module

    # Include routers
    # Handover 0046 Issue #4: Router prefix moved to router definition
    # Handover 0126: Modular products module (prefix and tags defined in module __init__.py)
    app.include_router(products.router)
    app.include_router(vision_documents.router, prefix="/api/vision-documents", tags=["vision-documents"])
    # Handover 0125: Modular projects module (prefix and tags defined in module __init__.py)
    app.include_router(projects.router)
    # Handover 0440a + Phase A (2026-05): Taxonomy types module (prefix and tags defined in module __init__.py)
    app.include_router(taxonomy_types.router)
    # BE-5039: Project status metadata module (frontend SSoT for badge labels/colors)
    app.include_router(project_statuses.router)
    # FE-5041: Task status metadata module (frontend SSoT for task badge labels/colors)
    app.include_router(task_statuses.router)
    app.include_router(downloads.router, tags=["downloads"])
    # Log-download endpoints are CE-only (self-hosted operators fetch their own
    # logs; SaaS/Demo never exposes log files). Gate at CALL time via the
    # api.app namespace so tests patching GILJO_MODE drive it — the prior
    # module-level import-time gate in downloads.py latched route membership to
    # whichever edition the module was first imported in (TSK-9125). CE is both
    # "" (default/unset) and "ce".
    if _app_module.GILJO_MODE in ("", "ce"):
        app.include_router(downloads.log_router, tags=["downloads"])
    # BE-6054ef: Agent Message Hub REST adapter
    app.include_router(comm_threads.router, prefix="/api/v1/threads", tags=["comm-threads"])
    app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
    # FE-6022a: Roadmapping Pane (one roadmap per active product)
    app.include_router(roadmap.router, prefix="/api/v1/roadmap", tags=["roadmap"])
    # BE-6131a: Sequential Multi-Project Runner — durable run/sequence record
    app.include_router(sequence_runs.router, prefix="/api/v1/sequence-runs", tags=["sequence-runs"])
    # BE-5059 Phase B: user_approvals decide endpoint
    app.include_router(approvals.router, prefix="/api/approvals", tags=["approvals"])
    # Handover 0124: Consolidated agent_jobs module (includes orchestration endpoints)
    app.include_router(agent_jobs.router)  # Prefix and tags defined in module __init__.py
    # Handover 0107: Job operations (cancel, force-fail, health) at /api/jobs prefix
    app.include_router(agent_jobs.jobs_router)  # Separate prefix for job operations
    app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["prompts"])  # Handover 0109
    # FE-9555: the board-level "Launch staged..." master prompt. Same prefix, own
    # module -- prompts.py carries a shrink-only size budget and may not grow.
    app.include_router(master_prompt.router, prefix="/api/v1/prompts", tags=["prompts"])
    app.include_router(configuration.router, prefix="/api/v1/config", tags=["configuration"])
    app.include_router(system_prompts.router, prefix="/api/v1/system", tags=["system"])
    app.include_router(statistics.router, prefix="/api/v1/stats", tags=["statistics"])
    # Handover 0126: Modular templates module (prefix and tags defined in module __init__.py)
    app.include_router(templates.router)
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(auth_pin_recovery.router, prefix="/api/auth", tags=["auth"])
    # FE-9274: Connect surface durable credential-status (read-only, tenant-scoped)
    app.include_router(connect.router, prefix="/api/connect", tags=["connect"])
    app.include_router(oauth.router, prefix="/api/oauth", tags=["oauth"])
    # API-0022: RFC 7009 /revoke split out to stay under the 800-line guardrail.
    app.include_router(oauth_revoke.router, prefix="/api/oauth", tags=["oauth"])
    # BE-6235: CE OAuth Dynamic Client Registration. CE-only — a self-hosted CE
    # server needs a registration_endpoint so OAuth harnesses (Claude Code et al.)
    # can auto-attach without a pre-known client_id; it returns the built-in public
    # client (no new table/migration). SaaS uses its own DCR endpoint
    # (saas_endpoints/oauth_register) and advertises that path instead, so this
    # router + advertisement are gated to CE to avoid colliding with it.
    if _app_module.GILJO_MODE in ("", "ce"):
        app.include_router(oauth_register.router, prefix="/api/oauth", tags=["oauth"])
        oauth.register_edition_registration_endpoint("/api/oauth/register")
    # Root-level well-known documents (RFC 8414 + RFC 9728). Spec-compliant
    # clients (Claude.ai, MCP CLI) probe `<host>/.well-known/...` per
    # API-0021a. Body of the AS-metadata mirror matches the /api/oauth/...
    # route exactly (same handler reused).
    app.include_router(oauth_well_known.well_known_router, tags=["oauth"])
    # Handover 0506: Fixed user endpoint path to /api/v1/users
    app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
    # v3: authenticated user-scoped settings
    app.include_router(user_settings.router, prefix="/api/v1/user", tags=["user-settings"])
    # Handover 0506: System settings endpoints (general, network, database, product-info, cookie-domain)
    app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
    # BE-5062: Tenant data export (CE: any user; SaaS: admin role required)
    app.include_router(tenant_data.router, prefix="/api/v1/account", tags=["tenant-data"])
    app.include_router(database_setup.router, prefix="/api/setup/database", tags=["database-setup"])
    app.include_router(setup_security.router, prefix="/api/setup", tags=["setup-security"])
    app.include_router(serena.router, prefix="/api/serena", tags=["serena"])
    app.include_router(git.router, prefix="/api/git", tags=["git"])
    app.include_router(version.router, prefix="/api/version", tags=["version"])
    # Skills version drift checks + future user-facing notifications
    app.include_router(notifications.router)

    # MCP SDK Streamable HTTP endpoint (Handover 0846 — replaces custom JSON-RPC 0032).
    # BE-6060c: served by the top-level McpDispatcher above the middleware onion, not a
    # FastAPI route here — see the module docstring above and api/mcp_dispatcher.py.

    # Slash command endpoints (Handover 0080a)
    app.include_router(slash_commands.router, prefix="/api", tags=["slash-commands"])

    # Organization endpoints (Handover 0424c)
    app.include_router(org_crud.router, prefix="/api/organizations", tags=["organizations"])
    app.include_router(org_members.router, prefix="/api/organizations", tags=["organization-members"])
    app.include_router(org_members.transfer_router, prefix="/api/organizations", tags=["organization-transfer"])

    # SaaS endpoint registration (conditional)
    # Follows Section F of docs/EDITION_ISOLATION_GUIDE.md:
    # directory existence check + GILJO_MODE gate + try-except ImportError
    if _app_module.GILJO_MODE == "saas":
        _saas_endpoints_dir = Path(__file__).parent.parent / "saas_endpoints"
        if _saas_endpoints_dir.is_dir():
            try:
                from api.saas_endpoints import register_saas_routes

                register_saas_routes(app)
                logger.info("SaaS endpoint routes registered")
            except ImportError:
                logger.info("SaaS endpoints directory exists but no routes registered")
