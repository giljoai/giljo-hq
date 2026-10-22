# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib
import logging
import os
from urllib.parse import urlsplit


logger = logging.getLogger("api.app")


def register_saas_tenant_scoped_models(*, giljo_mode: str) -> None:
    is_saas = giljo_mode == "saas"
    if not is_saas:
        return
    try:
        importlib.import_module("giljo_mcp.saas.tenant_registration").register_saas_tenant_scoped_models()
        logger.info("SaaS tenant-scoped models registered")
    except Exception:
        logger.critical(
            "SaaS Phase 8.6 [saas_tenant_registration] failed — aborting boot "
            "(SEC-9131 fail-loud): tenant-scope widening must never be silently absent."
        )
        raise


def _is_backup_key_error(exc: BaseException) -> bool:
    errors = importlib.import_module("giljo_mcp.saas.backup.errors")
    return isinstance(exc, errors.BackupEncryptionKeyInvalidError | errors.BackupEncryptionKeyMissingError)


async def start_deletion_reaper_phase(state):
    try:
        reaper_mod = importlib.import_module("giljo_mcp.saas.deletion.reaper")
        restore_mod = importlib.import_module("giljo_mcp.saas.restore.service")
        task = await reaper_mod.start_deletion_reaper(
            state.db_manager.AsyncSessionLocal,
            restore_mod.build_storage_adapter_from_env(),
        )
    except Exception as exc:
        if _is_backup_key_error(exc):
            logger.critical(
                "SaaS Phase 10 [deletion_reaper] backup encryption key is invalid — aborting boot (SEC-9817)"
            )
            raise
        logger.warning("Optional startup phase [deletion_reaper] failed: %s — running without deletion reaper", exc)
        state.degraded_services.append("deletion_reaper")
        return None
    logger.info("Deletion reaper background task started")
    return task


async def start_backup_scheduler_phase(state):
    try:
        sched_mod = importlib.import_module("giljo_mcp.saas.backup.scheduler")
        restore_mod = importlib.import_module("giljo_mcp.saas.restore.service")
        task = await sched_mod.start_backup_scheduler(
            state.db_manager.AsyncSessionLocal, restore_mod.build_storage_adapter_from_env()
        )
    except Exception as exc:
        if _is_backup_key_error(exc):
            logger.critical(
                "SaaS Phase 10.6 [backup_scheduler] backup encryption key is invalid — aborting boot (SEC-9817)"
            )
            raise
        logger.warning("Optional startup phase [backup_scheduler] failed: %s — running without backup scheduler", exc)
        state.degraded_services.append("backup_scheduler")
        return None
    logger.info("Backup snapshot scheduler background task started")
    return task


def require_public_base_url(*, giljo_mode: str) -> None:
    is_saas = giljo_mode == "saas"
    if not is_saas:
        return
    pinned = os.environ.get("GILJO_PUBLIC_BASE_URL", "").strip()
    if not pinned:
        logger.critical(
            "SaaS boot requires GILJO_PUBLIC_BASE_URL — aborting boot (SEC-9131 fail-loud): "
            "the OAuth issuer/audience and emailed lifecycle links must never derive from "
            "the Host header (SEC-9227h / SEC-9171 #30). Set GILJO_PUBLIC_BASE_URL to the "
            "canonical public origin, e.g. https://app.example.com"
        )
        raise RuntimeError("GILJO_PUBLIC_BASE_URL is required in SaaS mode (SEC-9227h)")
    problem = _public_base_url_problem(pinned)
    if problem:
        logger.critical(
            "GILJO_PUBLIC_BASE_URL is malformed (%s): %r — aborting boot (SEC-9131 fail-loud): "
            "a malformed origin pin is as unsafe as a missing one (SEC-9227h).",
            problem,
            pinned,
        )
        raise RuntimeError(f"GILJO_PUBLIC_BASE_URL is malformed ({problem}) (SEC-9227h)")


def _public_base_url_problem(pinned: str) -> str | None:
    try:
        parts = urlsplit(pinned)
        hostname = parts.hostname
        has_credentials = bool(parts.username or parts.password)
    except ValueError:
        return "not a parseable URL"
    if parts.scheme not in ("https", "http"):
        return "scheme must be https://"
    if not hostname:
        return "no hostname"
    if parts.scheme == "http" and hostname not in ("localhost", "127.0.0.1", "::1"):
        return "http:// is only allowed for localhost"
    if has_credentials:
        return "must not contain credentials"
    if parts.path not in ("", "/"):
        return "must not contain a path"
    if parts.query or parts.fragment:
        return "must not contain a query or fragment"
    return None


def register_mcp_subscription_gate(*, giljo_mode: str) -> None:
    is_saas = giljo_mode == "saas"
    if not is_saas:
        return
    try:
        importlib.import_module("giljo_mcp.saas.billing.mcp_subscription_gate").register()
        logger.info("MCP subscription gate registered")
    except Exception:
        logger.critical(
            "SaaS Phase 8.7 [mcp_subscription_gate] failed — aborting boot "
            "(SEC-9131 fail-loud): /mcp billing enforcement must never be silently absent."
        )
        raise


async def install_access_log(state, *, giljo_mode: str) -> None:
    is_saas = giljo_mode == "saas"
    if not is_saas:
        return
    from api.startup.background_jobs_gate import should_run_background_jobs

    try:
        access_log = importlib.import_module("giljo_mcp.saas.auth.access_log")
        access_log.install(state.db_manager.AsyncSessionLocal)
        if should_run_background_jobs():
            state.access_log_purge_task = await access_log.start_access_log_purge(state.db_manager.AsyncSessionLocal)
        logger.info("Access log recorder installed")
    except Exception as e:  # noqa: BLE001 - optional startup phase: degrade and report, never abort boot
        logger.warning("Optional startup phase [access_log] failed: %s — running without the access log", e)
        state.degraded_services.append("access_log")
