# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Background tasks initialization module

Handles background tasks: download token cleanup, API metrics sync, and one-time purge.
Extracted from api/app.py lifespan function (lines ~335-577).
"""

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


# Named Vue route the admin system banners deep-link to (Tools page).
_TOOLS_ROUTE = "Tools"

# Public GitHub releases page the "update available" banner links out to.
# Used as a fallback when the update checker did not capture a specific
# release_url (git-mode installs report commit counts, not a release URL).
_GITHUB_RELEASES_URL = "https://github.com/giljoai/giljo-hq/releases"


async def _tenant_keys_with_admins(db_manager: DatabaseManager) -> set[str]:
    """Return the set of tenant_keys that have at least one active admin user.

    The CE system banners (pending migrations / update available / skills drift)
    are admin-only (``role_filter='admin'``), so there is no value emitting them
    for tenants with no admin to see them. Cross-tenant discovery uses the
    audited model-scoped bypass (mirrors ``scan_expiring_api_keys_task``).
    """
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
    """Upsert/resolve the CE admin system banners for every tenant.

    Idempotent and safe to call repeatedly (startup + each update-checker cycle):
    each banner is a present-or-not upsert keyed by a stable ``dedupe_key`` with
    ``role_filter='admin'`` and ``surface='banner'``. When a condition no longer
    holds, the matching open notification is resolved (auto-clear).

    Conditions:
    - ``system.pending_migrations`` — DB schema behind the bundled head.
    - ``system.update_available`` — newer code/release available (from
      ``state.update_available`` populated by the update checker).
    - ``system.skills_drift`` — bundled SKILLS_VERSION ahead of the announced
      value.
    - ``system.tool_rename_notice`` — INF-6049a one-time migration prompt, shown
      for the first few CE process boots (counter bumped once per startup).
    """
    if not state.db_manager:
        return

    try:
        tenant_keys = await _tenant_keys_with_admins(state.db_manager)
    except (SQLAlchemyError, TypeError, ValueError, AttributeError) as exc:
        logger.error("system banner tenant enumeration failed: %s", exc, exc_info=True)
        return

    if not tenant_keys:
        return

    # On hosted SaaS, GiljoAI controls migrations and code rollout, so the
    # self-hosted "pending migrations" / "update available" admin banners do not
    # apply. The skills-drift banner stays in BOTH editions (BE-6031c).
    is_saas = os.environ.get("GILJO_MODE") == "saas"

    pending_info = None if is_saas else get_pending_migration_info(state)
    update_info = None if is_saas else getattr(state, "update_available", None)
    # INF-6049a: the first-3-boots tool-rename notice is CE-only. The counter is
    # READ here (per emit cycle) and incremented exactly once per process startup
    # in init_background_tasks -- never advanced by an update-checker tick.
    tool_rename_boot_count = None if is_saas else await _get_tool_rename_boot_count(state.db_manager)

    for tenant_key in tenant_keys:
        # FE-9202 F1: per-tenant isolation. One tenant's failure (e.g. a product
        # deactivated mid-cycle) must NOT abort the emit for every tenant after it
        # — otherwise a single broken tenant silently freezes the whole banner
        # refresh (including the skills-drift resurface) on every 6-hour tick.
        try:
            service = NotificationService(
                db_manager=state.db_manager,
                websocket_manager=getattr(state, "websocket_manager", None),
            )
            if not is_saas:
                await _emit_pending_migrations_banner(service, tenant_key, pending_info)
                await _emit_update_available_banner(service, tenant_key, update_info)
                await _emit_tool_rename_notice_banner(service, tenant_key, tool_rename_boot_count)
            # Drift is PER TENANT: compare the bundled SKILLS_VERSION against THIS
            # tenant's acknowledged_version, so one tenant re-running /giljo_setup
            # clears only its own banner.
            skills_drift = await _compute_skills_drift(state.db_manager, tenant_key)
            await _emit_skills_drift_banner(service, tenant_key, skills_drift)
            # FE-9202: context-tuning-due reminder. Emits in BOTH editions (context
            # tuning is a core concern) and is per-user (role_filter=None), so it
            # runs outside the is_saas guard above. Gated on the user's
            # tuning_reminder_threshold (count-based staleness, BE-9218).
            tuning_due = await compute_context_tuning_due(state.db_manager, tenant_key)
            await emit_context_tuning_due_banner(service, tenant_key, tuning_due, tools_route=_TOOLS_ROUTE)
        except Exception as exc:  # Broad catch: one tenant's failure never blocks the rest.
            logger.error("system banner emit failed for tenant %s: %s", tenant_key, exc, exc_info=True)


async def _emit_pending_migrations_banner(
    service: NotificationService, tenant_key: str, pending_info: dict | None
) -> None:
    dedupe_key = "system.pending_migrations"
    if pending_info is None:
        await service.resolve_by_dedupe_key(tenant_key, dedupe_key)
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
    # Always carry a usable GitHub URL: release-zip installs report a specific
    # release_url; git-mode installs report only a commit count, so fall back to
    # the releases landing page. The banner CTA opens this externally (no in-app
    # cta_route) since the actual upgrade happens in the user's terminal.
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
    # Clear any stale older-version update banners now superseded by this one.
    await service.resolve_open_by_type(tenant_key, "system.update_available", keep_dedupe_key=dedupe_key)


# Resurface a dismissed skills-drift banner after this many hours if drift persists.
_SKILLS_DRIFT_RESURFACE_HOURS = 24

# Stable per-tenant dedupe key: drift is now evaluated against the tenant's
# acknowledged_version and cleared by resolve-on-catch-up, so a single open row
# per tenant is correct (no per-version key churn).
_SKILLS_DRIFT_DEDUPE_KEY = "system.skills_drift"


async def _emit_skills_drift_banner(service: NotificationService, tenant_key: str, drift: dict | None) -> None:
    if drift is None:
        # Tenant has caught up (acknowledged == bundled) or never ran setup:
        # resolve any open drift banner so a re-run of /giljo_setup clears it.
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
    """Return drift info when the bundled SKILLS_VERSION is ahead of this tenant.

    ``acknowledged`` is THIS tenant's ``tenant_skills_ack.acknowledged_version``
    (the version it last installed via ``/giljo_setup``). Drift exists when the
    tenant has acknowledged some version that is not the bundled
    ``SKILLS_VERSION``. A tenant that has NEVER run setup (``acknowledged`` is
    None) raises no banner: there is nothing to "re-run" yet, and a fresh
    install should not nag before first setup.
    """
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


# INF-6049a: one-time CE migration notice for the get_orchestrator_instructions ->
# get_staging_context tool rename. Surfaced for the first N CE process boots after
# this version, reusing the EXISTING system-banner family (no new banner family).
_TOOL_RENAME_NOTICE_DEDUPE_KEY = "system.tool_rename_notice"


async def _get_tool_rename_boot_count(db_manager: DatabaseManager) -> int:
    """Read the deployment-wide tool-rename-notice boot count (0 if unset)."""
    from giljo_mcp.services.settings_service import SystemSettingsService

    async with db_manager.get_session_async() as session:
        return await SystemSettingsService(session).get_tool_rename_boot_count()


# The rename pairs the CE first-boots migration banner shows a self-hoster.
#
# BE-9563: module-level so a startup guard can assert every TARGET name against the
# live registry -- a hardcoded roster that nothing re-checks silently goes stale, and
# this one is read by a human.
#
# The LEFT side is history and must not be edited -- it records what those names used to
# be. Only the right side is a live claim.
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
    """Upsert/resolve the first-3-boots tool-rename migration notice (CE-only).

    Fires while the process boot count is within the notice window (1..MAX_BOOTS);
    once past it (or never set, or SaaS where ``boot_count`` is None) the open
    banner is resolved so it disappears.
    """
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
    """Background task to cleanup expired download tokens every 15 minutes.

    Deletes expired token rows AND reaps their on-disk staging directories
    (``temp/{tenant_key}/{token}/``). Before BE-3011 the reaper deleted rows
    only, orphaning the staging dirs on disk (a slow disk-filler with no
    operator on CE self-hosts). The DB delete returns the purged
    ``(tenant_key, token)`` pairs; each dir is removed via the path-validated
    ``FileStaging.purge_token_dir`` (idempotent; refuses any path escaping the
    staging root).
    """
    from giljo_mcp.download_tokens import TokenManager
    from giljo_mcp.file_staging import FileStaging

    while True:
        try:
            await asyncio.sleep(900)  # 15 minutes

            if state.db_manager:
                async with state.db_manager.get_session_async() as session:
                    token_manager = TokenManager(session)
                    result = await token_manager.cleanup_expired_tokens()
                    # Backward-compatible handling: support int or dict
                    deleted_total = result.get("total", 0) if isinstance(result, dict) else int(result or 0)
                    pairs = result.get("pairs", []) if isinstance(result, dict) else []

                    # Reap the on-disk staging dir for each purged token. Default
                    # base_path (Path.cwd()/temp) matches every production
                    # FileStaging caller. Path-validated + idempotent per pair.
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
        # BE-9053: catch-log-continue at the loop boundary (SaaS reaper pattern).
        # The old narrow tuple let one unexpected exception kill the loop
        # permanently and silently.
        except Exception as e:
            logger.error(f"Error during download token cleanup: {e}", exc_info=True)


async def purge_expired_deleted_items(db_manager: DatabaseManager, tenant_manager: TenantManager):
    """Run one-time purge of expired deleted projects and products (Handover 0070)"""
    try:
        logger.info("Running startup purge of expired deleted items...")

        # Get all tenants that have deleted items
        async with db_manager.get_session_async() as session:
            # Find all unique tenant keys with deleted items
            cutoff_date = datetime.now(UTC) - timedelta(days=10)

            # Get unique tenants with expired deleted projects
            project_stmt = (
                select(Project.tenant_key)
                .distinct()
                .where(Project.deleted_at.isnot(None), Project.deleted_at < cutoff_date)
            )

            # Get unique tenants with expired deleted products
            product_stmt = (
                select(Product.tenant_key)
                .distinct()
                .where(Product.deleted_at.isnot(None), Product.deleted_at < cutoff_date)
            )

            # BE6004C-5: these two discovery reads enumerate EVERY tenant with
            # expired deleted items -- no single tenant is knowable before the
            # query, so the audited model-scoped bypass is the correct mechanism.
            # The per-tenant purge BELOW runs tenant-scoped (set_current_tenant
            # per tenant), NOT under this bypass.
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

                # Purge for each tenant
                for tenant_key in all_tenants:
                    # Purge expired deleted projects
                    project_service = ProjectService(db_manager=db_manager, tenant_manager=tenant_manager)
                    # Set tenant context for this purge
                    tenant_manager.set_current_tenant(tenant_key)

                    project_purge_result = await project_service.deletion.purge_expired_deleted_projects(
                        days_before_purge=10
                    )
                    total_projects_purged += project_purge_result.purged_count

                    # Purge expired deleted products
                    product_service = ProductService(db_manager=db_manager, tenant_key=tenant_key)

                    product_purge_result = await product_service.lifecycle.purge_expired_deleted_products(
                        days_before_purge=10
                    )
                    total_products_purged += product_purge_result.purged_count

                # Clear tenant context
                tenant_manager.clear_current_tenant()

                if total_projects_purged > 0 or total_products_purged > 0:
                    logger.info(
                        f"[Handover 0070] Purged {total_projects_purged} expired deleted project(s) "
                        f"and {total_products_purged} expired deleted product(s)"
                    )
                else:
                    logger.debug("[Handover 0070] No expired deleted items to purge")

        logger.info("Startup purge complete")
    except Exception as e:  # Broad catch: background task startup, non-fatal
        logger.error(f"Failed to purge expired deleted items: {e}", exc_info=True)
        logger.warning("Continuing startup despite purge failure")


async def scan_expiring_api_keys_task(state: APIState):
    """Background task: notify users of API keys expiring within 7 days.

    Runs once per hour (NEVER per-minute). Enumerates every tenant that owns at
    least one API key, then runs the tenant-scoped expiry scan; the scan emits
    de-duplicated ``api_key.expiring_soon`` notifications, so re-running each hour
    does not produce duplicates.
    """
    while True:
        await asyncio.sleep(3600)  # 1 hour
        if not state.db_manager:
            continue
        try:
            async with state.db_manager.get_session_async() as session:
                # Cross-tenant discovery: no single tenant is knowable before the
                # query, so the audited model-scoped bypass is the correct
                # mechanism (mirrors purge_expired_deleted_items). The per-tenant
                # scan BELOW runs tenant-scoped via its own session.
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
        # BE-9053: catch-log-continue at the loop boundary (SaaS reaper pattern).
        # The old narrow tuple let one unexpected exception kill the loop
        # permanently and silently.
        except Exception as e:
            logger.error("Error during API key expiry scan: %s", e, exc_info=True)


# BE-3011: the notifications table had no purge path and grows unbounded per
# tenant. Conservative default retention for SAFELY-purgeable (resolved/expired)
# rows only. A module constant — NOT a new env var — keeps this within the
# complexity budget (mirrors MCPSessionManager.SESSION_CLEANUP_THRESHOLD_HOURS).
NOTIFICATION_RETENTION_DAYS = 30


async def purge_old_notifications_task(state: APIState):
    """Background task: purge resolved/expired notifications past retention.

    BE-3011 retention valve. Runs every 6 hours. Enumerates every tenant that
    owns at least one notification (audited model-scoped bypass — no single
    tenant is knowable before the query), then runs the tenant-scoped purge via
    the owning service so tenant A's sweep can never touch tenant B's rows.
    Only SAFELY-purgeable rows are removed (resolved or expired AND older than
    the retention window); active/unresolved notifications are never deleted by
    age alone.
    """
    from giljo_mcp.models.notifications import Notification

    while True:
        await asyncio.sleep(21600)  # 6 hours
        if not state.db_manager:
            continue
        try:
            async with state.db_manager.get_session_async() as session:
                # Cross-tenant discovery: no single tenant is knowable before the
                # query, so the audited model-scoped bypass is the correct
                # mechanism (mirrors the APIKey scan above). The per-tenant purge
                # BELOW stays tenant-scoped via the owning service's explicit
                # predicate, so tenant A's sweep can never reach tenant B's rows.
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
        # BE-9053: catch-log-continue at the loop boundary (SaaS reaper pattern).
        # The old narrow tuple let one unexpected exception kill the loop
        # permanently and silently.
        except Exception as e:
            logger.error("Error during notification retention purge: %s", e, exc_info=True)


async def cleanup_expired_mcp_sessions_task(state: APIState):
    """Background task: purge MCP HTTP sessions inactive beyond the threshold.

    BE-3011: ``MCPSessionManager.cleanup_expired_sessions`` existed and was
    correct but had ZERO callers, so the ``mcp_sessions`` table grew unbounded.
    Wired in here (runs every 6 hours). The manager method now runs its
    cross-tenant DELETE under the audited tenant-isolation bypass.
    """
    from api.endpoints.mcp_session import MCPSessionManager

    while True:
        await asyncio.sleep(21600)  # 6 hours
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
        # BE-9053: catch-log-continue at the loop boundary (SaaS reaper pattern).
        # The old narrow tuple let one unexpected exception kill the loop
        # permanently and silently.
        except Exception as e:
            logger.error("Error during MCP session cleanup: %s", e, exc_info=True)


async def refresh_system_banners_task(state: APIState) -> None:
    """Re-evaluate the CE system banners every 6 hours (FE-9202).

    ``emit_system_banners`` is idempotent (present-or-not upserts + resolve-on-
    clear) but was only ever invoked at startup and on update-checker
    transitions, so TIME-based banners never re-evaluated on a long-running
    server. This loop closes that gap. Two banners depend on it:
    - ``system.context_tuning_due`` (new) — the 14-day reminder can only appear
      once its window elapses, which needs periodic evaluation.
    - ``system.skills_drift`` (existing) — its documented 24h dismissal-resurface
      now actually fires; a dismissed drift banner reappears daily while drift
      persists, exactly as its ``resurface_after_hours`` always specified.
    """
    while True:
        await asyncio.sleep(21600)  # 6 hours
        if not state.db_manager:
            continue
        try:
            await emit_system_banners(state)
            logger.debug("System banners re-evaluated (6-hourly refresh)")
        except asyncio.CancelledError:
            raise
        # BE-9053: catch-log-continue at the loop boundary (SaaS reaper pattern).
        except Exception as e:
            logger.error("Error during system banner refresh: %s", e, exc_info=True)


async def init_background_tasks(state: APIState) -> None:
    """Initialize background tasks: cleanup, metrics sync, and one-time purge

    Args:
        state: APIState instance to populate with task references

    Raises:
        Exception: Logged but not raised - background task failures are non-fatal
    """
    # Per-worker telemetry flushers ALWAYS run, regardless of the background-jobs
    # gate: they drain THIS worker's in-memory API/WebSocket counters, so routing
    # them to a request-less worker process would silently lose telemetry
    # (INF-3009b — the audit's "justify staying per-worker" carve-out).
    # Start API metrics sync task
    try:
        logger.info("Starting API metrics sync task...")
        metrics_sync_task = asyncio.create_task(sync_api_metrics_to_db(state), name="api-metrics-flusher")
        metrics_sync_task.add_done_callback(log_task_death)
        state.metrics_sync_task = metrics_sync_task
        logger.info("API metrics sync task started (runs every 5 minutes)")
    except Exception as e:  # Broad catch: background task startup, non-fatal
        logger.error(f"Failed to start API metrics sync task: {e}", exc_info=True)

    # Start WebSocket runtime-gauge sync task (BE-6108)
    try:
        logger.info("Starting WebSocket metrics sync task...")
        ws_metrics_sync_task = asyncio.create_task(sync_ws_metrics_to_db(state), name="ws-metrics-flusher")
        ws_metrics_sync_task.add_done_callback(log_task_death)
        state.ws_metrics_sync_task = ws_metrics_sync_task
        logger.info("WebSocket metrics sync task started (runs every 30 seconds)")
    except Exception as e:  # Broad catch: background task startup, non-fatal
        logger.error(f"Failed to start WebSocket metrics sync task: {e}", exc_info=True)

    # INF-3009b worker gate: everything below is a shared cross-tenant
    # maintenance/reaper loop or one-time sweep. Behind GILJO_RUN_BACKGROUND_JOBS
    # (default ON) so a single dedicated worker service can own them once
    # WEB_CONCURRENCY>1 — stopping duplicate reaper emails and racing destructive
    # sweeps. Default ON keeps CE single-process + un-split SaaS byte-identical.
    if not should_run_background_jobs():
        logger.info(
            "Background maintenance jobs DISABLED for this process (%s=off) — "
            "reaper/sweep/purge loops run in the dedicated worker service instead",
            _BG_JOBS_ENV,
        )
        return
    logger.info("Background maintenance jobs ENABLED for this process (%s)", _BG_JOBS_ENV)

    # Start download token cleanup task (Handover 0100)
    try:
        logger.info("Starting download token cleanup task...")
        cleanup_task = asyncio.create_task(cleanup_expired_download_tokens(state), name="download-token-cleanup")
        cleanup_task.add_done_callback(log_task_death)
        state.cleanup_task = cleanup_task  # Store reference to prevent garbage collection
        logger.info("Download token cleanup task started (runs every 15 minutes)")
    except Exception as e:  # Broad catch: background task startup, non-fatal
        logger.error(f"Failed to start download token cleanup task: {e}", exc_info=True)

    # Start API key expiry scan task (IMP-5037a Phase 3)
    try:
        logger.info("Starting API key expiry scan task...")
        api_key_expiry_task = asyncio.create_task(scan_expiring_api_keys_task(state), name="api-key-expiry-scan")
        api_key_expiry_task.add_done_callback(log_task_death)
        state.api_key_expiry_task = api_key_expiry_task
        logger.info("API key expiry scan task started (runs every hour)")
    except Exception as e:  # Broad catch: background task startup, non-fatal
        logger.error(f"Failed to start API key expiry scan task: {e}", exc_info=True)

    # Start notification retention purge task (BE-3011)
    try:
        logger.info("Starting notification retention purge task...")
        notification_purge_task = asyncio.create_task(purge_old_notifications_task(state), name="notification-purge")
        notification_purge_task.add_done_callback(log_task_death)
        state.notification_purge_task = notification_purge_task
        logger.info("Notification retention purge task started (runs every 6 hours)")
    except Exception as e:  # Broad catch: background task startup, non-fatal
        logger.error(f"Failed to start notification retention purge task: {e}", exc_info=True)

    # Start MCP session cleanup task (BE-3011 — was dead/uncalled)
    try:
        logger.info("Starting MCP session cleanup task...")
        mcp_session_cleanup_task = asyncio.create_task(
            cleanup_expired_mcp_sessions_task(state), name="mcp-session-cleanup"
        )
        mcp_session_cleanup_task.add_done_callback(log_task_death)
        state.mcp_session_cleanup_task = mcp_session_cleanup_task
        logger.info("MCP session cleanup task started (runs every 6 hours)")
    except Exception as e:  # Broad catch: background task startup, non-fatal
        logger.error(f"Failed to start MCP session cleanup task: {e}", exc_info=True)

    # Start OAuth authorization code cleanup task (BE-8000i -- was dead/uncalled).
    # Extracted to oauth_code_reaper.py: this module was already at the 800-line
    # CI guardrail (same rationale as tenant_guard.py's split from database.py).
    start_oauth_code_cleanup_task(state)

    # Start git update checker (CE only — hosted SaaS controls its own rollout, BE-6031c)
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

    # INF-6049a: bump the first-3-boots CE tool-rename-notice counter exactly ONCE
    # per process startup (NOT inside emit_system_banners, which also runs on every
    # update-checker tick — otherwise "first 3 boots" would become "first 3 ticks").
    if not is_saas and state.db_manager:
        try:
            from giljo_mcp.services.settings_service import SystemSettingsService

            async with state.db_manager.get_session_async() as session:
                await SystemSettingsService(session).increment_tool_rename_boot_count()
        except Exception as e:  # Broad catch: counter bump must never block startup
            logger.error(f"Failed to bump tool-rename notice boot count: {e}", exc_info=True)

    # Emit CE admin system banners (pending migrations / update / skills drift / tool-rename notice)
    try:
        await emit_system_banners(state)
        logger.info("System banners emitted at startup")
    except Exception as e:  # Broad catch: banner emission must never block startup
        logger.error(f"Failed to emit system banners at startup: {e}", exc_info=True)

    # FE-9202: 6-hourly system-banner refresh so time-based banners (context-tuning
    # due + skills-drift resurface) re-evaluate on long-running servers.
    try:
        logger.info("Starting system banner refresh task...")
        banner_refresh_task = asyncio.create_task(refresh_system_banners_task(state), name="system-banner-refresh")
        banner_refresh_task.add_done_callback(log_task_death)
        state.system_banner_refresh_task = banner_refresh_task
        logger.info("System banner refresh task started (runs every 6 hours)")
    except Exception as e:  # Broad catch: background task startup, non-fatal
        logger.error(f"Failed to start system banner refresh task: {e}", exc_info=True)

    # Run one-time purge of expired deleted items
    if state.db_manager:
        await purge_expired_deleted_items(state.db_manager, state.tenant_manager)
        # TSK-6132: reap expired soft-deleted trash/recover rows (CommThread,
        # Task, VisionDocument, AgentTemplate) past the BE-6130b recovery window.
        await purge_expired_soft_deleted_entities(state.db_manager, state.tenant_manager)
