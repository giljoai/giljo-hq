# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    import api.app as _app_module

    app.include_router(products.router)
    app.include_router(vision_documents.router, prefix="/api/vision-documents", tags=["vision-documents"])
    app.include_router(projects.router)
    app.include_router(taxonomy_types.router)
    app.include_router(project_statuses.router)
    app.include_router(task_statuses.router)
    app.include_router(downloads.router, tags=["downloads"])
    if _app_module.GILJO_MODE in ("", "ce"):
        app.include_router(downloads.log_router, tags=["downloads"])
    app.include_router(comm_threads.router, prefix="/api/v1/threads", tags=["comm-threads"])
    app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
    app.include_router(roadmap.router, prefix="/api/v1/roadmap", tags=["roadmap"])
    app.include_router(sequence_runs.router, prefix="/api/v1/sequence-runs", tags=["sequence-runs"])
    app.include_router(approvals.router, prefix="/api/approvals", tags=["approvals"])
    app.include_router(agent_jobs.router)
    app.include_router(agent_jobs.jobs_router)
    app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["prompts"])
    app.include_router(master_prompt.router, prefix="/api/v1/prompts", tags=["prompts"])
    app.include_router(configuration.router, prefix="/api/v1/config", tags=["configuration"])
    app.include_router(system_prompts.router, prefix="/api/v1/system", tags=["system"])
    app.include_router(statistics.router, prefix="/api/v1/stats", tags=["statistics"])
    app.include_router(templates.router)
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(auth_pin_recovery.router, prefix="/api/auth", tags=["auth"])
    app.include_router(connect.router, prefix="/api/connect", tags=["connect"])
    app.include_router(oauth.router, prefix="/api/oauth", tags=["oauth"])
    app.include_router(oauth_revoke.router, prefix="/api/oauth", tags=["oauth"])
    if _app_module.GILJO_MODE in ("", "ce"):
        app.include_router(oauth_register.router, prefix="/api/oauth", tags=["oauth"])
        oauth.register_edition_registration_endpoint("/api/oauth/register")
    app.include_router(oauth_well_known.well_known_router, tags=["oauth"])
    app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
    app.include_router(user_settings.router, prefix="/api/v1/user", tags=["user-settings"])
    app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
    app.include_router(tenant_data.router, prefix="/api/v1/account", tags=["tenant-data"])
    app.include_router(database_setup.router, prefix="/api/setup/database", tags=["database-setup"])
    app.include_router(setup_security.router, prefix="/api/setup", tags=["setup-security"])
    app.include_router(serena.router, prefix="/api/serena", tags=["serena"])
    app.include_router(git.router, prefix="/api/git", tags=["git"])
    app.include_router(version.router, prefix="/api/version", tags=["version"])
    app.include_router(notifications.router)


    app.include_router(slash_commands.router, prefix="/api", tags=["slash-commands"])

    app.include_router(org_crud.router, prefix="/api/organizations", tags=["organizations"])
    app.include_router(org_members.router, prefix="/api/organizations", tags=["organization-members"])
    app.include_router(org_members.transfer_router, prefix="/api/organizations", tags=["organization-transfer"])

    if _app_module.GILJO_MODE == "saas":
        _saas_endpoints_dir = Path(__file__).parent.parent / "saas_endpoints"
        if _saas_endpoints_dir.is_dir():
            try:
                from api.saas_endpoints import register_saas_routes

                register_saas_routes(app)
                logger.info("SaaS endpoint routes registered")
            except ImportError:
                logger.info("SaaS endpoints directory exists but no routes registered")
