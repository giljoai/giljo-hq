# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Multi-worker boot-prerequisite guard (INF-3009e) — fail-loud, never silent.

The single-worker fence used to exist only in comments and operator memory
(ARCHITECTURE_AUDIT_2026-06-11): nothing in code refused ``WEB_CONCURRENCY>1``.
Flipping that env var without the prerequisite work ships four simultaneous
incident classes from one variable — duplicate reaper/customer emails, per-user
rate limits multiplied by worker count, per-process license/cache state, and
dropped cross-worker WebSocket events.

This gate encodes the fence IN CODE. With ``worker_count > 1`` it refuses to boot
unless EVERY prerequisite is live, and the error names each missing one:

1. **WebSocket broker** must be cross-worker capable (not ``in_memory``). Already
   enforced upstream at core-services init by ``ensure_broker_supports_worker_count``
   (BE-3008c); re-asserted here so this gate is a single documented checkpoint
   that survives phase reordering.
2. **Background jobs** must be OFF in a multi-worker web process
   (``GILJO_RUN_BACKGROUND_JOBS`` falsey, INF-3009b) — a dedicated single-replica
   worker service owns the reapers, else each web worker races them and duplicates
   customer emails / destructive sweeps.
3. **Shared cache/license backend** (SaaS only) must be a live Redis
   (``state.redis_mode == "connected"``, INF-3009c/d) — per-process dicts make
   license and OAuth-idempotency state incoherent across workers.
4. **Tenant rate-limit store** (SaaS only) must construct
   (``build_default_store()`` non-None, the 2026-07-11 amendment) — a ``None``
   store silently drops the per-user limiter, so per-IP counts multiply by N.

Contract:

- ``worker_count <= 1``: pure no-op for ANY config. CE single-process and any
  un-split single-web-process SaaS deployment stay byte-identical to today.
- ``worker_count > 1``: raise ``RuntimeError`` listing every unmet prerequisite.
  Callers must NOT catch it — it propagates out of ``lifespan()`` and aborts
  uvicorn, the same fail-loud pattern as the Phase 0 license check and the
  INF-3009c Redis gate. Refusing to boot is the whole point: a degraded
  multi-worker process looks healthy while silently corrupting shared state.

CE never imports anything under a ``saas`` tree: the two SaaS-only checks reach
``api.saas_middleware`` through ``importlib`` and only when ``giljo_mode == "saas"``,
so the Deletion Test holds regardless of whether the SaaS tree exists.

The actual test/prod ``WEB_CONCURRENCY`` flip stays operator-gated and out of
scope (operator-internal flip checklist).
"""

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
    """Log the effective restart policy + worker count so incident logs self-describe.

    Incident 2026-07-16: a platform SIGTERM after a healthy deploy left the prod
    service down for ~51 min, and diagnosing it required reconstructing the
    restart policy and worker posture from platform state after the fact. This
    one INFO line puts both in every boot log. ``GILJO_RESTART_POLICY`` is
    exported by the platform's start-command config (the single source of
    truth for the start command), so ``restart_policy=unset`` is itself a
    signal: this process was NOT launched by the config-as-code start command
    (CE, local dev, or a dashboard start-command override drifting from the
    repo).
    """
    policy = os.getenv("GILJO_RESTART_POLICY", "").strip() or "unset"
    logger.info(
        "Deploy posture: restart_policy=%s, workers=%d (WEB_CONCURRENCY).",
        policy,
        _worker_count(),
    )


def assert_multiworker_prerequisites(state: APIState, *, giljo_mode: str) -> None:
    """Refuse to boot under ``WEB_CONCURRENCY>1`` unless every prerequisite is live.

    No-op when the process is a single worker (after logging the deploy posture).
    See the module docstring for the full per-prerequisite contract and rationale.
    """
    log_deploy_posture()
    worker_count = _worker_count()
    if worker_count <= 1:
        # Single worker: shared state is complete per-process — nothing to guard.
        return

    missing: list[str] = []

    # 1. Cross-worker WebSocket broker (edition-neutral).
    broker = getattr(state, "websocket_broker", None)
    if broker is None or isinstance(broker, InMemoryWebSocketEventBroker):
        missing.append(
            "WebSocket broker is 'in_memory' (or absent): cross-worker events — "
            "realtime updates AND live-session revocation — would be silently "
            "dropped. Set GILJO_WS_BROKER=postgres_notify."
        )

    # 2. Background-job split (edition-neutral, INF-3009b).
    if should_run_background_jobs():
        missing.append(
            f"Background jobs are ON in this web process ({BACKGROUND_JOBS_ENV_VAR} "
            "unset/truthy): every worker would race the reapers and duplicate "
            "customer emails / destructive sweeps. Set "
            f"{BACKGROUND_JOBS_ENV_VAR}=off on multi-worker web processes and run "
            "the shared loops in the dedicated worker service."
        )

    # 3 + 4: SaaS-only shared stores. CE never reaches the saas tree.
    if giljo_mode == "saas":
        # 3. Shared cache/license backend (INF-3009c/d). "connected" means Redis
        #    was verified reachable at boot; anything else is per-process dicts.
        if getattr(state, "redis_mode", None) != "connected":
            missing.append(
                "Shared cache/license backend is not on Redis (redis_mode="
                f"{getattr(state, 'redis_mode', None)!r}): license and "
                "OAuth-idempotency state would be per-process and incoherent "
                "across workers. Set REDIS_URL to a reachable Redis."
            )

        # 4. Tenant rate-limit store (amendment). None = the per-user limiter is
        #    silently absent, so the CE per-IP floor multiplies by worker count.
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
