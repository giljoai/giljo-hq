# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-6132 soft-delete reaper (startup maintenance task).

Extracted from ``api/startup/background_tasks.py`` to keep that module under the
800-line guardrail. Completes the BE-6130b/BE-6137 trash/recover lifecycle by
hard-deleting soft-deleted rows past the recovery window, through each entity's
owning service. Wired into ``init_background_tasks`` at startup.
"""

import logging

from sqlalchemy import select

from giljo_mcp.database import DatabaseManager, tenant_isolation_bypass
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


async def purge_expired_soft_deleted_entities(db_manager: DatabaseManager, tenant_manager: TenantManager):
    """TSK-6132: reap soft-deleted trash/recover rows past the recovery window.

    Completes the BE-6130b trash/recover lifecycle for the self-service entities
    (CommThread, Task, VisionDocument, AgentTemplate): a row trashed longer than
    ``RECOVER_WINDOW_DAYS`` ago is no longer recoverable, so this permanently
    hard-deletes it through its OWNING service — cascade/FK handling stays with
    the service that owns the row, and ``tenant_key`` scopes every query. Reuses
    the shared ``domain.soft_delete`` policy (no schema change), is FK-safe and
    idempotent, and runs once at startup alongside ``purge_expired_deleted_items``.
    """
    from giljo_mcp.domain.soft_delete import recover_window_cutoff
    from giljo_mcp.models import AgentTemplate, Task, VisionDocument
    from giljo_mcp.models.comm import CommThread
    from giljo_mcp.services.comm_thread_service import CommThreadService
    from giljo_mcp.services.product_vision_service import ProductVisionService
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.services.template_service import TemplateService

    try:
        logger.info("Running startup reaper for expired soft-deleted trash/recover rows (TSK-6132)...")
        cutoff = recover_window_cutoff()

        async def _tenants_with_expired(session, model) -> set[str]:
            """Enumerate every tenant owning an expired soft-deleted row of ``model``.

            BE-9319: this took a caller-supplied ``needs_bypass`` flag — an opinion
            about registry membership that the caller had to REMEMBER. Three of four
            call sites remembered right and one remembered wrong, and the wrong one
            killed the whole sweep. The flag is gone: every model this reaper handles
            is tenant-scoped, so the cross-tenant enumeration always needs the audited
            bypass, and ``tenant_isolation_bypass`` validates that itself — hand it a
            model that is NOT tenant-scoped and it raises naming the model, which is
            the loud answer a future caller deserves instead of a boolean that can be
            silently wrong.
            """
            stmt = select(model.tenant_key).distinct().where(model.deleted_at.isnot(None), model.deleted_at < cutoff)
            with tenant_isolation_bypass(
                session,
                reason="cross-tenant maintenance scan: enumerate tenants for soft-delete reaper (TSK-6132)",
                models=(model,),
            ):
                result = await session.execute(stmt)
                return {row[0] for row in result.fetchall()}

        async with db_manager.get_session_async() as session:
            thread_tenants = await _tenants_with_expired(session, CommThread)
            task_tenants = await _tenants_with_expired(session, Task)
            doc_tenants = await _tenants_with_expired(session, VisionDocument)
            template_tenants = await _tenants_with_expired(session, AgentTemplate)

        totals = {"threads": 0, "tasks": 0, "vision_documents": 0, "templates": 0}
        try:
            for tenant_key in thread_tenants:
                tenant_manager.set_current_tenant(tenant_key)
                totals["threads"] += await CommThreadService(db_manager, tenant_manager).purge_expired_deleted_threads()
            for tenant_key in task_tenants:
                tenant_manager.set_current_tenant(tenant_key)
                totals["tasks"] += await TaskService(
                    db_manager=db_manager, tenant_manager=tenant_manager
                ).purge_expired_deleted_tasks()
            for tenant_key in doc_tenants:
                tenant_manager.set_current_tenant(tenant_key)
                totals["vision_documents"] += await ProductVisionService(
                    db_manager, tenant_key=tenant_key
                ).purge_expired_deleted_documents()
            for tenant_key in template_tenants:
                tenant_manager.set_current_tenant(tenant_key)
                totals["templates"] += await TemplateService(
                    db_manager, tenant_manager
                ).purge_expired_deleted_templates()
        finally:
            tenant_manager.clear_current_tenant()

        if any(totals.values()):
            logger.info(
                "[TSK-6132] Reaped expired soft-deleted rows: %d thread(s), %d task(s), "
                "%d vision document(s), %d template(s)",
                totals["threads"],
                totals["tasks"],
                totals["vision_documents"],
                totals["templates"],
            )
        else:
            logger.debug("[TSK-6132] No expired soft-deleted rows to reap")
    except Exception as e:  # Broad catch: background startup task, non-fatal
        logger.error("Failed to reap expired soft-deleted rows (TSK-6132): %s", e, exc_info=True)
        logger.warning("Continuing startup despite reaper failure")
