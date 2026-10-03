# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from api.app_state import APIState
from api.startup.background_jobs_gate import ENV_VAR as _BG_JOBS_ENV
from api.startup.background_jobs_gate import should_run_background_jobs
from api.startup.context_tuning_banner import (
    compute_context_tuning_due,
    emit_context_tuning_due_banner,
)
from api.startup.metrics_flushers import (
    log_task_death,
    sync_api_metrics_to_db,
    sync_ws_metrics_to_db,
)
from api.startup.migration_check import get_pending_migration_info
from api.startup.oauth_code_reaper import start_oauth_code_cleanup_task
from api.startup.soft_delete_reaper import purge_expired_soft_deleted_entities
from giljo_mcp import branding
from giljo_mcp.database import DatabaseManager, tenant_isolation_bypass
from giljo_mcp.models import APIKey, Product, Project
from giljo_mcp.models.auth import User
from giljo_mcp.services.auth_service import AuthService
from giljo_mcp.services.notification_service import NotificationService
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


_TOOLS_ROUTE = "Tools"

_GITHUB_RELEASES_URL = "https://github.com/giljoai/giljo-hq/releases"


async def _tenant_keys_with_admins(db_manager: DatabaseManager) -> set[str]:
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session,
            reason="cross-tenant maintenance scan: enumerate tenants with admins for system banners",
            models=(User,),
        ):
            result = await session.execute(
                select(User.tenant_key).distinct().where(User.role == "admin", User.is_active.is_(True))
            )
            return {row[0] for row in result.fetchall()}


async def emit_system_banners(state: APIState) -> None:
    if not state.db_manager:
        return

    try:
        tenant_keys = await _tenant_keys_with_admins(state.db_manager)
    except (SQLAlchemyError, TypeError, ValueError, AttributeError) as exc:
        logger.error("system banner tenant enumeration failed: %s", exc, exc_info=True)
        return

    if not tenant_keys:
        return

    is_saas = os.environ.get("GILJO_MODE") == "saas"

    pending_info = None if is_saas else get_pending_migration_info(state)
    update_info = None if is_saas else getattr(state, "update_available", None)
    tool_rename_boot_count = None if is_saas else await _get_tool_rename_boot_count(state.db_manager)

    for tenant_key in tenant_keys:
        try:
            service = NotificationService(
                db_manager=state.db_manager,
                websocket_manager=getattr(state, "websocket_manager", None),
            )
            if not is_saas:
                await _emit_pending_migrations_banner(service, tenant_key, pending_info)
                await _emit_update_available_banner(service, tenant_key, update_info)
                await _emit_tool_rename_notice_banner(service, tenant_key, tool_rename_boot_count)
            skills_drift = await _compute_skills_drift(state.db_manager, tenant_key)
            await _emit_skills_drift_banner(service, tenant_key, skills_drift)
            tuning_due = await compute_context_tuning_due(state.db_manager, tenant_key)
            await emit_context_tuning_due_banner(service, tenant_key, tuning_due, tools_route=_TOOLS_ROUTE)
        except Exception as exc:
            logger.error("system banner emit failed for tenant %s: %s", tenant_key, exc, exc_info=True)


async def _emit_pending_migrations_banner(
    service: NotificationService, tenant_key: str, pending_info: dict | None
) -> None:
    dedupe_key = "system.pending_migrations"
    if pending_info is None:
        await service.resolve_by_dedupe_key(tenant_key, dedupe_key)
        return
    if pending_info.get("unknown"):
        logger.warning("migration status unknown; leaving the pending-migrations banner as it is")
        return
    count = pending_info["pending"]
    await service.upsert_by_dedupe_key(
        tenant_key=tenant_key,
        user_id=None,
        notification_type="system.pending_migrations",
        severity="warning",
        title=f"{count} database migration{'s' if count != 1 else ''} pending",
        body="Restart your server to apply pending migrations (or run python update.py).",
        dedupe_key=dedupe_key,
        surface="banner",
        role_filter="admin",
        cta_label="View status",
        cta_route=_TOOLS_ROUTE,
        dismissible=False,
        payload={"pending": count, "head": pending_info["head"]},
    )


async def _emit_update_available_banner(
    service: NotificationService, tenant_key: str, update_info: dict | None
) -> None:
    if not update_info:
        await service.resolve_open_by_type(tenant_key, "system.update_available")
        return

    commits_behind = update_info.get("commits_behind")
    tag = update_info.get("latest_version") or update_info.get("tag")
    release_url = update_info.get("release_url") or _GITHUB_RELEASES_URL
    natural = tag or (str(commits_behind) if commits_behind is not None else "available")
    dedupe_key = f"system.update_available:{natural}"

    title = update_info.get("message", f"A {branding.PRODUCT_NAME} update is available")
    await service.upsert_by_dedupe_key(
        tenant_key=tenant_key,
        user_id=None,
        notification_type="system.update_available",
        severity="info",
        title=title[:255],
        dedupe_key=dedupe_key,
        surface="banner",
        role_filter="admin",
        cta_label="View release",
        cta_route=None,
        payload={
            "commits_behind": commits_behind,
            "release_url": release_url,
            "tag": tag,
        },
    )
    await service.resolve_open_by_type(tenant_key, "system.update_available", keep_dedupe_key=dedupe_key)


_SKILLS_DRIFT_RESURFACE_HOURS = 24

_SKILLS_DRIFT_DEDUPE_KEY = "system.skills_drift"


async def _emit_skills_drift_banner(service: NotificationService, tenant_key: str, drift: dict | None) -> None:
    if drift is None:
        await service.resolve_by_dedupe_key(tenant_key, _SKILLS_DRIFT_DEDUPE_KEY)
        return
    await service.upsert_by_dedupe_key(
        tenant_key=tenant_key,
        user_id=None,
        notification_type="system.skills_drift",
        severity="info",
        title="A newer slash-command bundle is available",
        body=drift["message"],
        dedupe_key=_SKILLS_DRIFT_DEDUPE_KEY,
        surface="banner",
        role_filter="admin",
        cta_label="Update bundle",
        cta_route=_TOOLS_ROUTE,
        resurface_after_hours=_SKILLS_DRIFT_RESURFACE_HOURS,
        payload={
            "current": drift["current"],
            "announced": drift["announced"],
            "message": drift["message"],
        },
    )


async def _compute_skills_drift(db_manager: DatabaseManager, tenant_key: str) -> dict | None:
    from giljo_mcp.services.settings_service import TenantSkillsAckService
    from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

    async with db_manager.get_session_async() as session:
        ack_service = TenantSkillsAckService(session, tenant_key)
        acknowledged = await ack_service.get_acknowledged_version()

    if acknowledged is None or acknowledged == SKILLS_VERSION:
        return None
    return {
        "current": SKILLS_VERSION,
        "announced": acknowledged,
        "message": (
            f"Skills bundle updated to v{SKILLS_VERSION} (you have v{acknowledged}) — "
            "re-run /giljo_setup on each machine to update."
        ),
    }


_TOOL_RENAME_NOTICE_DEDUPE_KEY = "system.tool_rename_notice"


async def _get_tool_rename_boot_count(db_manager: DatabaseManager) -> int:
    from giljo_mcp.services.settings_service import SystemSettingsService

    async with db_manager.get_session_async() as session:
        return await SystemSettingsService(session).get_tool_rename_boot_count()


TOOL_RENAME_NOTICE_PAIRS: tuple[str, ...] = (
    "get_agent_mission → get_job_mission",
    "update_agent_mission → update_job_mission",
    "fetch_context → get_context",
    "write_360_memory → write_memory_entry",
    "close_project_and_update_memory → write_project_closeout",
    "inspect_messages → get_thread_history (the message bus was removed)",
    "update_product_fields → update_product_context",
    "submit_tuning_review → apply_context_tuning",
)


async def _emit_tool_rename_notice_banner(
    service: NotificationService, tenant_key: str, boot_count: int | None
) -> None:
    from giljo_mcp.services.settings_service import TOOL_RENAME_NOTICE_MAX_BOOTS

    if boot_count is None or not (1 <= boot_count <= TOOL_RENAME_NOTICE_MAX_BOOTS):
        await service.resolve_by_dedupe_key(tenant_key, _TOOL_RENAME_NOTICE_DEDUPE_KEY)
        return
    rename_list = "; ".join(TOOL_RENAME_NOTICE_PAIRS)
    await service.upsert_by_dedupe_key(
        tenant_key=tenant_key,
        user_id=None,
        notification_type="system.tool_rename_notice",
        severity="info",
        title="GiljoAI updated its tools",
        body=(
            f"Re-run giljo_setup to refresh your commands and agents. "
            f"8 tool names changed: {rename_list}. "
            "If you referenced old names in a template's editable instructions, update them or "
            "restore to default. Re-run giljo_setup on each machine to apply the new bundle."
        ),
        dedupe_key=_TOOL_RENAME_NOTICE_DEDUPE_KEY,
        surface="banner",
        role_filter="admin",
        cta_label="Open Tools",
        cta_route=_TOOLS_ROUTE,
        dismissible=True,
    )


async def cleanup_expired_download_tokens(state: APIState):
    from giljo_mcp.download_tokens import TokenManager
    from giljo_mcp.file_staging import FileStaging

    while True:
        try:
            await asyncio.sleep(900)

            if state.db_manager:
                async with state.db_manager.get_session_async() as session:
                    token_manager = TokenManager(session)
                    result = await token_manager.cleanup_expired_tokens()
                    deleted_total = result.get("total", 0) if isinstance(result, dict) else int(result or 0)
                    pairs = result.get("pairs", []) if isinstance(result, dict) else []

                    staging = FileStaging()
                    reaped = 0
                    for tenant_key, token in pairs:
                        if await staging.purge_token_dir(tenant_key, token):
                            reaped += 1

                    if deleted_total > 0:
                        logger.info(
                            f"Download token cleanup: {deleted_total} tokens removed, {reaped} staging dir(s) reaped"
                        )
                    else:
                        logger.debug("Download token cleanup: no tokens removed")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error during download token cleanup: {e}", exc_info=True)


async def purge_expired_deleted_items(db_manager: DatabaseManager, tenant_manager: TenantManager):
    try:
        logger.info("Running startup purge of expired deleted items...")

        async with db_manager.get_session_async() as session:
            cutoff_date = datetime.now(UTC) - timedelta(days=10)

            project_stmt = (
                select(Project.tenant_key)
                .distinct()
                .where(Project.deleted_at.isnot(None), Project.deleted_at < cutoff_date)
            )

            product_stmt = (
                select(Product.tenant_key)
                .distinct()
                .where(Product.deleted_at.isnot(None), Product.deleted_at < cutoff_date)
            )

            with tenant_isolation_bypass(
                session,
                reason="cross-tenant maintenance scan: enumerate tenants for purge",
                models=(Project, Product),
            ):
                project_result = await session.execute(project_stmt)
                project_tenants = {row[0] for row in project_result.fetchall()}
                product_result = await session.execute(product_stmt)
                product_tenants = {row[0] for row in product_result.fetchall()}

            all_tenants = project_tenants | product_tenants

            if not all_tenants:
                logger.debug("[Handover 0070] No expired deleted items to purge")
            else:
                total_projects_purged = 0
                total_products_purged = 0

                for tenant_key in all_tenants:
                    project_service = ProjectService(db_manager=db_manager, tenant_manager=tenant_manager)
                    tenant_manager.set_current_tenant(tenant_key)

                    project_purge_result = await project_service.deletion.purge_expired_deleted_projects(
                        days_before_purge=10
                    )
                    total_projects_purged += project_purge_result.purged_count

                    product_service = ProductService(db_manager=db_manager, tenant_key=tenant_key)

                    product_purge_result = await product_service.lifecycle.purge_expired_deleted_products(
                        days_before_purge=10
                    )
                    total_products_purged += product_purge_result.purged_count

                tenant_manager.clear_current_tenant()

                if total_projects_purged > 0 or total_products_purged > 0:
                    logger.info(
                        f"[Handover 0070] Purged {total_projects_purged} expired deleted project(s) "
                        f"and {total_products_purged} expired deleted product(s)"
                    )
                else:
                    logger.debug("[Handover 0070] No expired deleted items to purge")

        logger.info("Startup purge complete")
    except Exception as e:
        logger.error(f"Failed to purge expired deleted items: {e}", exc_info=True)
        logger.warning("Continuing startup despite purge failure")


async def scan_expiring_api_keys_task(state: APIState):
    while True:
        await asyncio.sleep(3600)
        if not state.db_manager:
            continue
        try:
            async with state.db_manager.get_session_async() as session:
                with tenant_isolation_bypass(
                    session,
                    reason="cross-tenant maintenance scan: enumerate tenants with API keys",
                    models=(APIKey,),
                ):
                    result = await session.execute(select(APIKey.tenant_key).distinct())
                    tenant_keys = {row[0] for row in result.fetchall()}

            for tenant_key in tenant_keys:
                auth_service = AuthService(db_manager=state.db_manager)
                notification_service = NotificationService(
                    db_manager=state.db_manager,
                    websocket_manager=getattr(state, "websocket_manager", None),
                )
                await auth_service.scan_expiring_api_keys(
                    tenant_key=tenant_key,
                    days_ahead=7,
                    notification_service=notification_service,
                )
            logger.debug("API key expiry scan complete for %d tenant(s)", len(tenant_keys))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error during API key expiry scan: %s", e, exc_info=True)


NOTIFICATION_RETENTION_DAYS = 30


async def purge_old_notifications_task(state: APIState):
    from giljo_mcp.models.notifications import Notification

    while True:
        await asyncio.sleep(21600)
        if not state.db_manager:
            continue
        try:
            async with state.db_manager.get_session_async() as session:
                with tenant_isolation_bypass(
                    session,
                    reason="cross-tenant maintenance scan: enumerate tenants with notifications",
                    models=(Notification,),
                ):
                    result = await session.execute(select(Notification.tenant_key).distinct())
                    tenant_keys = {row[0] for row in result.fetchall()}

            total_purged = 0
            for tenant_key in tenant_keys:
                notification_service = NotificationService(
                    db_manager=state.db_manager,
                    websocket_manager=getattr(state, "websocket_manager", None),
                )
                total_purged += await notification_service.purge_resolved_older_than(
                    tenant_key=tenant_key,
                    retention_days=NOTIFICATION_RETENTION_DAYS,
                )
            if total_purged > 0:
                logger.info(
                    "Notification retention purge: %d row(s) removed across %d tenant(s)",
                    total_purged,
                    len(tenant_keys),
                )
            else:
                logger.debug("Notification retention purge: nothing to purge")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error during notification retention purge: %s", e, exc_info=True)


async def cleanup_expired_mcp_sessions_task(state: APIState):
    from api.endpoints.mcp_session import MCPSessionManager

    while True:
        await asyncio.sleep(21600)
        if not state.db_manager:
            continue
        try:
            async with state.db_manager.get_session_async() as session:
                manager = MCPSessionManager(session)
                removed = await manager.cleanup_expired_sessions()
            if removed:
                logger.info("MCP session cleanup: %d inactive session(s) removed", removed)
            else:
                logger.debug("MCP session cleanup: nothing to remove")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error during MCP session cleanup: %s", e, exc_info=True)


async def refresh_system_banners_task(state: APIState) -> None:
    while True:
        await asyncio.sleep(21600)
        if not state.db_manager:
            continue
        try:
            await emit_system_banners(state)
            logger.debug("System banners re-evaluated (6-hourly refresh)")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error during system banner refresh: %s", e, exc_info=True)


async def init_background_tasks(state: APIState) -> None:
    try:
        logger.info("Starting API metrics sync task...")
        metrics_sync_task = asyncio.create_task(sync_api_metrics_to_db(state), name="api-metrics-flusher")
        metrics_sync_task.add_done_callback(log_task_death)
        state.metrics_sync_task = metrics_sync_task
        logger.info("API metrics sync task started (runs every 5 minutes)")
    except Exception as e:
        logger.error(f"Failed to start API metrics sync task: {e}", exc_info=True)

    try:
        logger.info("Starting WebSocket metrics sync task...")
        ws_metrics_sync_task = asyncio.create_task(sync_ws_metrics_to_db(state), name="ws-metrics-flusher")
        ws_metrics_sync_task.add_done_callback(log_task_death)
        state.ws_metrics_sync_task = ws_metrics_sync_task
        logger.info("WebSocket metrics sync task started (runs every 30 seconds)")
    except Exception as e:
        logger.error(f"Failed to start WebSocket metrics sync task: {e}", exc_info=True)

    if not should_run_background_jobs():
        logger.info(
            "Background maintenance jobs DISABLED for this process (%s=off) — "
            "reaper/sweep/purge loops run in the dedicated worker service instead",
            _BG_JOBS_ENV,
        )
        return
    logger.info("Background maintenance jobs ENABLED for this process (%s)", _BG_JOBS_ENV)

    try:
        logger.info("Starting download token cleanup task...")
        cleanup_task = asyncio.create_task(cleanup_expired_download_tokens(state), name="download-token-cleanup")
        cleanup_task.add_done_callback(log_task_death)
        state.cleanup_task = cleanup_task
        logger.info("Download token cleanup task started (runs every 15 minutes)")
    except Exception as e:
        logger.error(f"Failed to start download token cleanup task: {e}", exc_info=True)

    try:
        logger.info("Starting API key expiry scan task...")
        api_key_expiry_task = asyncio.create_task(scan_expiring_api_keys_task(state), name="api-key-expiry-scan")
        api_key_expiry_task.add_done_callback(log_task_death)
        state.api_key_expiry_task = api_key_expiry_task
        logger.info("API key expiry scan task started (runs every hour)")
    except Exception as e:
        logger.error(f"Failed to start API key expiry scan task: {e}", exc_info=True)

    try:
        logger.info("Starting notification retention purge task...")
        notification_purge_task = asyncio.create_task(purge_old_notifications_task(state), name="notification-purge")
        notification_purge_task.add_done_callback(log_task_death)
        state.notification_purge_task = notification_purge_task
        logger.info("Notification retention purge task started (runs every 6 hours)")
    except Exception as e:
        logger.error(f"Failed to start notification retention purge task: {e}", exc_info=True)

    try:
        logger.info("Starting MCP session cleanup task...")
        mcp_session_cleanup_task = asyncio.create_task(
            cleanup_expired_mcp_sessions_task(state), name="mcp-session-cleanup"
        )
        mcp_session_cleanup_task.add_done_callback(log_task_death)
        state.mcp_session_cleanup_task = mcp_session_cleanup_task
        logger.info("MCP session cleanup task started (runs every 6 hours)")
    except Exception as e:
        logger.error(f"Failed to start MCP session cleanup task: {e}", exc_info=True)

    start_oauth_code_cleanup_task(state)

    is_saas = os.environ.get("GILJO_MODE") == "saas"
    if not is_saas:
        try:
            from api.startup.update_checker import start_update_checker

            update_task = await start_update_checker(state)
            if update_task:
                state.update_checker_task = update_task
                logger.info("Git update checker started (runs every 6 hours)")
        except Exception as e:  # noqa: BLE001 — background task startup, non-fatal
            logger.debug("Git update checker not available: %s", e)

    if not is_saas and state.db_manager:
        try:
            from giljo_mcp.services.settings_service import SystemSettingsService

            async with state.db_manager.get_session_async() as session:
                await SystemSettingsService(session).increment_tool_rename_boot_count()
        except Exception as e:
            logger.error(f"Failed to bump tool-rename notice boot count: {e}", exc_info=True)

    try:
        await emit_system_banners(state)
        logger.info("System banners emitted at startup")
    except Exception as e:
        logger.error(f"Failed to emit system banners at startup: {e}", exc_info=True)

    try:
        logger.info("Starting system banner refresh task...")
        banner_refresh_task = asyncio.create_task(refresh_system_banners_task(state), name="system-banner-refresh")
        banner_refresh_task.add_done_callback(log_task_death)
        state.system_banner_refresh_task = banner_refresh_task
        logger.info("System banner refresh task started (runs every 6 hours)")
    except Exception as e:
        logger.error(f"Failed to start system banner refresh task: {e}", exc_info=True)

    if state.db_manager:
        await purge_expired_deleted_items(state.db_manager, state.tenant_manager)
        await purge_expired_soft_deleted_entities(state.db_manager, state.tenant_manager)
