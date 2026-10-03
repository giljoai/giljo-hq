# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import logging
import os

from api.app_state import APIState
from api.websocket import WebSocketManager
from giljo_mcp.auth import AuthManager
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor


logger = logging.getLogger(__name__)


def _resolve_broker_dsn(state: APIState) -> str | None:
    return os.getenv("GILJO_BROKER_DATABASE_URL") or getattr(state.db_manager, "database_url", None)


def assert_pgbouncer_broker_pairing() -> None:
    if os.getenv("GILJO_PGBOUNCER") != "1":
        return
    if not os.getenv("GILJO_BROKER_DATABASE_URL"):
        raise RuntimeError(
            "GILJO_PGBOUNCER=1 but GILJO_BROKER_DATABASE_URL is not set. With the app "
            "database URL behind PgBouncer transaction pooling, the realtime broker's "
            "session-pinned LISTEN cannot survive — cross-worker realtime updates AND "
            "live-session revocation would fail silently. Set GILJO_BROKER_DATABASE_URL "
            "to the DIRECT (unpooled) database URL (on the hosted platform: the Postgres "
            "service's unpooled connection string), or unset GILJO_PGBOUNCER."
        )


async def init_websocket_broker(state: APIState) -> None:
    from api.startup.database import _worker_count

    assert_pgbouncer_broker_pairing()

    worker_count = _worker_count()
    try:
        from api.broker import create_websocket_event_broker, ensure_broker_supports_worker_count

        broker = create_websocket_event_broker(
            config=state.config,
            database_url=_resolve_broker_dsn(state),
        )
        ensure_broker_supports_worker_count(broker, worker_count)
        await broker.start()
        state.websocket_broker = broker
        state.websocket_manager.attach_broker(broker)
        logger.info(f"WebSocket broker initialized: {broker.__class__.__name__}")
        from api.startup.agent_wake_relay import install_wake_relay

        install_wake_relay(
            broker=broker,
            websocket_manager=state.websocket_manager,
            worker_count=worker_count,
        )
    except Exception as e:
        logger.error(f"Failed to initialize WebSocket broker: {e}", exc_info=True)
        if worker_count > 1:
            raise
        state.degraded_services.append("websocket_broker")


async def init_core_services(state: APIState) -> None:
    try:
        logger.info("Initializing tenant manager...")
        state.tenant_manager = TenantManager()
        logger.info("Tenant manager initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize tenant manager: {e}", exc_info=True)
        raise

    try:
        logger.info("Initializing WebSocket manager...")
        state.websocket_manager = WebSocketManager()
        from giljo_mcp.app_registry.service_registry import set_websocket_manager

        set_websocket_manager(state.websocket_manager)
        logger.info("WebSocket manager initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize WebSocket manager: {e}", exc_info=True)
        raise

    await init_websocket_broker(state)

    try:
        logger.info("Initializing tool accessor...")
        state.tool_accessor = ToolAccessor(
            state.db_manager, state.tenant_manager, websocket_manager=state.websocket_manager
        )
        logger.info("Tool accessor initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize tool accessor: {e}", exc_info=True)
        raise

    try:
        logger.info("Initializing authentication manager...")
        state.auth = AuthManager(state.config, db=None)
        logger.info("Auth manager initialized (mode-independent authentication)")
    except Exception as e:
        logger.error(f"Failed to initialize auth manager: {e}", exc_info=True)
        raise

    api_key = os.getenv("API_KEY") or os.getenv("GILJO_MCP_API_KEY")
    if api_key:
        state.auth.api_keys[api_key] = {
            "name": "Installer Generated",
            "created_at": "2024-01-01T00:00:00Z",
            "permissions": ["*"],
            "active": True,
        }
        key_suffix = api_key[-4:] if len(api_key) > 4 else "XXXX"
        logger.info(f"Loaded API key from environment (key ending in: ...{key_suffix})")
    else:
        logger.info("No API key configured - all clients require JWT authentication (unified auth)")

    try:
        logger.info("Starting WebSocket heartbeat task...")
        _start_supervised_heartbeat(state, interval=30)
        logger.info("WebSocket heartbeat started (interval: 30s, supervised)")
    except Exception:
        logger.exception("Optional startup phase [ws_heartbeat] failed")
        state.degraded_services.append("ws_heartbeat")


def _start_supervised_heartbeat(state: APIState, interval: int = 30) -> None:

    def _supervise(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.error("WebSocket heartbeat task died; restarting", exc_info=exc)
        try:
            import sentry_sdk

            sentry_sdk.add_breadcrumb(
                category="websocket",
                level="error",
                message="heartbeat task died; supervisor restarting",
            )
        except ImportError:
            pass
        _start_supervised_heartbeat(state, interval=interval)

    heartbeat_task = asyncio.create_task(state.websocket_manager.start_heartbeat(interval=interval))
    heartbeat_task.add_done_callback(_supervise)
    state.heartbeat_task = heartbeat_task
