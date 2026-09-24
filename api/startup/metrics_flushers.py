# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import logging
import os
import socket
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from api.app_state import APIState
from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import ApiMetrics, McpToolCallMetric, ServerRuntimeMetric
from giljo_mcp.models.auth import User


logger = logging.getLogger(__name__)


def log_task_death(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("maintenance_loop_died task=%s error=%r", task.get_name(), exc, exc_info=exc)
    else:
        logger.error("maintenance_loop_exited task=%s — loop returned; it should run forever", task.get_name())


async def _live_tenant_keys(session, tenant_keys: set[str]) -> set[str]:
    if not tenant_keys:
        return set()
    with tenant_isolation_bypass(
        session,
        reason="BE-9582: cross-tenant liveness check so purged tenants are not re-created in api_metrics",
        models=(User,),
    ):
        result = await session.execute(select(User.tenant_key).where(User.tenant_key.in_(tenant_keys)).distinct())
    return set(result.scalars().all())


async def flush_api_metrics_once(state: APIState) -> None:
    api_counts = state.api_call_count.copy()
    mcp_counts = state.mcp_call_count.copy()
    tool_counts = state.mcp_tool_call_count.copy()
    state.api_call_count.clear()
    state.mcp_call_count.clear()
    state.mcp_tool_call_count.clear()
    tool_rows: dict[str, list[tuple[str, object, int]]] = {}
    for (buffered_tenant, tool_name, day), tool_count in tool_counts.items():
        tool_rows.setdefault(buffered_tenant, []).append((tool_name, day, tool_count))
    try:
        async with state.db_manager.get_session_async() as session:
            buffered = api_counts.keys() | mcp_counts.keys() | tool_rows.keys()
            live = await _live_tenant_keys(session, set(buffered))
            skipped = len(buffered) - len(live)
            for tenant_key in sorted(live):
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

                for tool_name, day, tool_count in sorted(tool_rows.get(tenant_key, ())):
                    await session.execute(
                        insert(McpToolCallMetric)
                        .values(
                            id=str(uuid4()),
                            tenant_key=tenant_key,
                            tool_name=tool_name,
                            day=day,
                            call_count=tool_count,
                        )
                        .on_conflict_do_update(
                            index_elements=["tenant_key", "tool_name", "day"],
                            set_={"call_count": McpToolCallMetric.call_count + tool_count},
                        )
                    )
            await session.commit()
        if skipped:
            logger.info("API metrics sync: skipped %d purged tenant(s) with buffered counts", skipped)
        if api_counts:
            logger.info("Synced API metrics for %d tenants.", len(api_counts))
        else:
            logger.debug("API metrics sync: no API call counts to flush")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Error during API metrics sync: {e}", exc_info=True)
        state.api_call_count.update(api_counts)
        state.mcp_call_count.update(mcp_counts)
        state.mcp_tool_call_count.update(tool_counts)


async def sync_api_metrics_to_db(state: APIState):
    while True:
        await asyncio.sleep(300)
        if not state.db_manager:
            continue
        await flush_api_metrics_once(state)


WS_METRIC_NAME = "ws_active_connections"
WS_METRIC_SYNC_INTERVAL_SECONDS = 30
_WS_METRIC_STALE_PRUNE = timedelta(hours=1)


async def sync_ws_metrics_to_db(state: APIState):
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
            logger.error(f"Error during WS metrics sync: {e}", exc_info=True)
