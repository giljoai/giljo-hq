# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib
import logging
import os
from typing import TYPE_CHECKING

from api.broker.in_memory import InMemoryWebSocketEventBroker
from api.startup.background_jobs_gate import ENV_VAR as BACKGROUND_JOBS_ENV_VAR
from api.startup.background_jobs_gate import should_run_background_jobs
from api.startup.database import _worker_count


if TYPE_CHECKING:
    from api.app_state import APIState


logger = logging.getLogger("api.app")


def log_deploy_posture() -> None:
    policy = os.getenv("GILJO_RESTART_POLICY", "").strip() or "unset"
    logger.info(
        "Deploy posture: restart_policy=%s, workers=%d (WEB_CONCURRENCY).",
        policy,
        _worker_count(),
    )


def assert_multiworker_prerequisites(state: APIState, *, giljo_mode: str) -> None:
    log_deploy_posture()
    worker_count = _worker_count()
    if worker_count <= 1:
        return

    missing: list[str] = []

    broker = getattr(state, "websocket_broker", None)
    if broker is None or isinstance(broker, InMemoryWebSocketEventBroker):
        missing.append(
            "WebSocket broker is 'in_memory' (or absent): cross-worker events — "
            "realtime updates AND live-session revocation — would be silently "
            "dropped. Set GILJO_WS_BROKER=postgres_notify."
        )

    if should_run_background_jobs():
        missing.append(
            f"Background jobs are ON in this web process ({BACKGROUND_JOBS_ENV_VAR} "
            "unset/truthy): every worker would race the reapers and duplicate "
            "customer emails / destructive sweeps. Set "
            f"{BACKGROUND_JOBS_ENV_VAR}=off on multi-worker web processes and run "
            "the shared loops in the dedicated worker service."
        )

    if giljo_mode == "saas":
        if getattr(state, "redis_mode", None) != "connected":
            missing.append(
                "Shared cache/license backend is not on Redis (redis_mode="
                f"{getattr(state, 'redis_mode', None)!r}): license and "
                "OAuth-idempotency state would be per-process and incoherent "
                "across workers. Set REDIS_URL to a reachable Redis."
            )

        rate_limiter_mod = importlib.import_module("api.saas_middleware.rate_limiter_tenant")
        if rate_limiter_mod.build_default_store() is None:
            missing.append(
                "Tenant rate-limit store failed to construct "
                "(build_default_store() returned None): the per-user limiter is "
                "silently absent, so per-user limits multiply across workers. Fix "
                "REDIS_URL so a RedisRateLimitStore is built."
            )

    if not missing:
        logger.info(
            "Multi-worker prerequisites satisfied (WEB_CONCURRENCY=%d): broker, background-job split%s.",
            worker_count,
            ", shared cache backend, tenant rate-limit store" if giljo_mode == "saas" else "",
        )
        return

    detail = "\n".join(f"  - {item}" for item in missing)
    raise RuntimeError(
        f"Refusing to boot with WEB_CONCURRENCY={worker_count}: "
        f"{len(missing)} multi-worker prerequisite(s) not satisfied. Each would "
        f"silently corrupt shared state across workers:\n{detail}\n"
        "Fix the listed items or run a single worker (WEB_CONCURRENCY=1)."
    )
