# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Per-worker telemetry flusher loops + maintenance-loop death logging (BE-9053).

Extracted from ``background_tasks.py``, which sits at the 800-line CI guardrail
(same rationale as ``oauth_code_reaper.py``'s split). Two things live here:

1. The API/WebSocket metrics flusher loops. These previously caught only
   ``SQLAlchemyError`` — and the API-metrics flusher acquired its session
   OUTSIDE the try — so ONE transient DB error killed the task permanently
   and silently. Both loops now follow the SaaS reaper discipline:
   ``asyncio.CancelledError`` re-raised (clean shutdown), everything else
   caught-logged-continued at the loop boundary.

2. ``log_task_death`` — an ``asyncio.Task`` done-callback attached to every
   maintenance loop at creation. A maintenance loop must run forever, so its
   task finishing AT ALL (other than cancellation at shutdown) is logged at
   ERROR (Sentry-visible in SaaS) instead of telling nobody.
"""

import asyncio
import logging
import os
import socket
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from api.app_state import APIState
from giljo_mcp.models import ApiMetrics, ServerRuntimeMetric


logger = logging.getLogger(__name__)


def log_task_death(task: asyncio.Task) -> None:
    """Done-callback: a maintenance loop exiting on its own is an ERROR.

    Cancellation is the one legitimate exit (lifespan shutdown) — silent.
    Any other completion (exception that escaped the loop's catch, or the
    coroutine returning) is logged at ERROR so the operator learns a
    maintenance loop is dead BEFORE its absence bites (BE-9053 item 2).
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("maintenance_loop_died task=%s error=%r", task.get_name(), exc, exc_info=exc)
    else:
        logger.error("maintenance_loop_exited task=%s — loop returned; it should run forever", task.get_name())


async def sync_api_metrics_to_db(state: APIState):
    """Background task to sync API metrics to the database every 5 minutes."""
    while True:
        await asyncio.sleep(300)  # 5 minutes
        if not state.db_manager:
            continue
        # Copy + reset the counters BEFORE the DB round-trip; restore on any
        # failure so the window's counts are retried next cycle (pre-existing
        # semantics, kept verbatim).
        api_counts = state.api_call_count.copy()
        mcp_counts = state.mcp_call_count.copy()
        state.api_call_count.clear()
        state.mcp_call_count.clear()
        try:
            async with state.db_manager.get_session_async() as session:
                # Union of both maps' keys, not just api_counts': a tenant can
                # make MCP calls with no API calls in the same window (/mcp is
                # a public path, so auth never sets tenant_key there) and its
                # mcp_call_count must still reach the DB even though it was
                # already cleared unconditionally above.
                for tenant_key in api_counts.keys() | mcp_counts.keys():
                    api_count = api_counts.get(tenant_key, 0)
                    mcp_count = mcp_counts.get(tenant_key, 0)

                    stmt = (
                        insert(ApiMetrics)
                        .values(
                            tenant_key=tenant_key,
                            date=datetime.now(UTC),
                            total_api_calls=api_count,
                            total_mcp_calls=mcp_count,
                        )
                        .on_conflict_do_update(
                            index_elements=["tenant_key"],
                            set_={
                                "total_api_calls": ApiMetrics.total_api_calls + api_count,
                                "total_mcp_calls": ApiMetrics.total_mcp_calls + mcp_count,
                                "date": datetime.now(UTC),
                            },
                        )
                    )
                    await session.execute(stmt)
                await session.commit()
            # House rule: a periodic loop logs at INFO only when it did something;
            # an idle tick logs at DEBUG. This predicate IS the edition difference
            # (CE idles at 0 tenants, SaaS does not) — do not make it a mode check.
            if api_counts:
                logger.info("Synced API metrics for %d tenants.", len(api_counts))
            else:
                # Scoped to the API counts on purpose: /mcp is a public path, so
                # auth never sets tenant_key and api_call_count stays empty while
                # mcp_call_count fills. A blanket "nothing to flush" would be a
                # false statement on an MCP-only server.
                logger.debug("API metrics sync: no API call counts to flush")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # BE-9053: catch-log-continue at the loop boundary (SaaS reaper
            # pattern). Previously only SQLAlchemyError was caught and the
            # session was acquired outside the try — one transient DB error
            # killed this flusher permanently and silently.
            logger.error(f"Error during API metrics sync: {e}", exc_info=True)
            state.api_call_count.update(api_counts)
            state.mcp_call_count.update(mcp_counts)


# BE-6108: server-level runtime gauges. The active WebSocket count is a live,
# per-worker number (sum across workers = total), unlike the cumulative
# tenant-keyed ApiMetrics — so it gets its own short-cadence sibling writer into
# server_runtime_metrics (int gauge, no PII, no tenant_key). The Ops Panel reads
# SUM(value) within a freshness window; stale rows from exited workers are
# excluded by that window and pruned here.
WS_METRIC_NAME = "ws_active_connections"
WS_METRIC_SYNC_INTERVAL_SECONDS = 30
_WS_METRIC_STALE_PRUNE = timedelta(hours=1)


async def sync_ws_metrics_to_db(state: APIState):
    """Background task: upsert THIS worker's active WebSocket gauge every 30s.

    Sibling of :func:`sync_api_metrics_to_db`. Writes one row per
    (worker_id, metric) keyed on a stable per-process id so the upsert updates
    the same row each cycle; prunes rows from workers not seen in an hour
    (pid reuse across restarts) so the table stays bounded.
    """
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    while True:
        await asyncio.sleep(WS_METRIC_SYNC_INTERVAL_SECONDS)
        ws_manager = getattr(state, "websocket_manager", None)
        if not state.db_manager or ws_manager is None:
            continue
        try:
            count = int(ws_manager.get_connection_count())
        except (AttributeError, TypeError, ValueError):
            continue
        try:
            now = datetime.now(UTC)
            async with state.db_manager.get_session_async() as session:
                stmt = (
                    insert(ServerRuntimeMetric)
                    .values(
                        id=str(uuid4()),
                        worker_id=worker_id,
                        metric=WS_METRIC_NAME,
                        value=count,
                        updated_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["worker_id", "metric"],
                        set_={"value": count, "updated_at": now},
                    )
                )
                await session.execute(stmt)
                # Bound the table across worker restarts (pid reuse): drop gauges
                # from workers not seen within the prune window. The reader uses a
                # tighter freshness window, so this only removes long-dead rows.
                await session.execute(
                    delete(ServerRuntimeMetric).where(
                        ServerRuntimeMetric.metric == WS_METRIC_NAME,
                        ServerRuntimeMetric.updated_at < now - _WS_METRIC_STALE_PRUNE,
                    )
                )
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # BE-9053: catch-log-continue at the loop boundary (SaaS reaper pattern).
            logger.error(f"Error during WS metrics sync: {e}", exc_info=True)
