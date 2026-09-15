# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from sqlalchemy import select

from giljo_mcp.database import DatabaseManager, tenant_isolation_bypass
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


async def purge_expired_soft_deleted_entities(db_manager: DatabaseManager, tenant_manager: TenantManager):
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
    except Exception as e:
        logger.error("Failed to reap expired soft-deleted rows (TSK-6132): %s", e, exc_info=True)
        logger.warning("Continuing startup despite reaper failure")
