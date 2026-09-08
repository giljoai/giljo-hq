# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Core services initialization module

Handles initialization of TenantManager, WebSocketManager, ToolAccessor, and AuthManager.
Extracted from api/app.py lifespan function (lines ~215-293).
"""

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
    """Resolve the DSN the LISTEN/NOTIFY broker connects on (INF-3009f, P2).

    The broker holds a session-pinned ``LISTEN`` connection (``postgres_notify.py``),
    which PgBouncer transaction pooling cannot serve — a pooled connection is handed
    back at every COMMIT, so the ``LISTEN`` registration would be lost and cross-worker
    realtime + live-session revocation would silently die. When the app's
    ``DATABASE_URL`` points at PgBouncer, ``GILJO_BROKER_DATABASE_URL`` supplies the
    broker its own DIRECT (unpooled) DSN. Unset -> fall back to the app database URL,
    which is byte-identical to the pre-INF-3009f behavior (CE / single-worker / no
    PgBouncer never set the var).
    """
    return os.getenv("GILJO_BROKER_DATABASE_URL") or getattr(state.db_manager, "database_url", None)


def assert_pgbouncer_broker_pairing() -> None:
    """Fail boot when ``GILJO_PGBOUNCER=1`` is set without ``GILJO_BROKER_DATABASE_URL`` (INF-3009f).

    The two variables are a pair: ``GILJO_PGBOUNCER=1`` declares that the app's
    ``DATABASE_URL`` sits behind PgBouncer transaction pooling, and transaction
    pooling cannot serve the broker's session-pinned ``LISTEN`` — without a direct
    DSN, cross-worker realtime AND live-session revocation (TSK-9006) die with no
    error anywhere. Nothing else enforces the pairing (the vars live in the
    platform's dashboards, not code), so this converts the worst failure mode from silent to
    structural, same fail-loud posture as ``ensure_broker_supports_worker_count``.

    The flag gate matches P1's idiom: only the exact value ``"1"`` is ON.
    """
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
    """Create, guard, and attach the cross-worker WebSocket event broker.

    BE-3008c fail-loud posture: with workers > 1 the broker is security-load-bearing
    (it fans the disconnect_tenant session-revocation control message across
    workers, TSK-9006), so ANY broker problem — in_memory selected, or a broker
    that fails to start — aborts boot instead of silently degrading. A single
    worker keeps the graceful local-only degrade: its local delivery is complete.
    """
    from api.startup.database import _worker_count

    # INF-3009f: MUST run before (and outside) the try below — the single-worker
    # degrade path swallows broker exceptions, and this misconfig must abort boot
    # at ANY worker count.
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
        # BE-9296a: additive cross-worker fan-out for the agent wake signal. No-ops on
        # a single worker, where the in-process registry is already complete.
        from api.startup.agent_wake_relay import install_wake_relay

        install_wake_relay(
            broker=broker,
            websocket_manager=state.websocket_manager,
            worker_count=worker_count,
        )
    except Exception as e:  # Broad catch: single-worker degrade path re-raises when multi-worker
        logger.error(f"Failed to initialize WebSocket broker: {e}", exc_info=True)
        if worker_count > 1:
            raise
        # Single worker: degrade gracefully — continue with local-only broadcasts.


async def init_core_services(state: APIState) -> None:
    """Initialize core services: TenantManager, WebSocketManager, ToolAccessor, AuthManager

    Each core service initializer logs the failing service by name and then
    RE-RAISES: a partially constructed core service is not survivable, so boot
    aborts rather than serving. The heartbeat task at the end is the exception —
    it is genuinely optional, and its failure is logged without aborting.

    Args:
        state: APIState instance to populate with service managers

    Raises:
        Exception: If TenantManager, WebSocketManager, ToolAccessor or
            AuthManager fails to initialize. Aborts boot by design.
    """
    # Initialize tenant manager
    try:
        logger.info("Initializing tenant manager...")
        state.tenant_manager = TenantManager()  # TenantManager uses static methods
        logger.info("Tenant manager initialized successfully")
    except Exception as e:  # Broad catch: name the failing service, then abort boot
        logger.error(f"Failed to initialize tenant manager: {e}", exc_info=True)
        raise

    # Initialize WebSocket manager BEFORE tool accessor (needed for MessageRoutingService,
    # CommThreadService, UserApprovalService, and OrchestrationService's real-time emission)
    try:
        logger.info("Initializing WebSocket manager...")
        state.websocket_manager = WebSocketManager()
        # Register in service registry so src/giljo_mcp/ code can access it
        from giljo_mcp.app_registry.service_registry import set_websocket_manager

        set_websocket_manager(state.websocket_manager)
        logger.info("WebSocket manager initialized successfully")
    except Exception as e:  # Broad catch: name the failing service, then abort boot
        logger.error(f"Failed to initialize WebSocket manager: {e}", exc_info=True)
        raise

    # Initialize WebSocket broker (0379e)
    await init_websocket_broker(state)

    # Initialize tool accessor (now websocket_manager is available)
    try:
        logger.info("Initializing tool accessor...")
        state.tool_accessor = ToolAccessor(
            state.db_manager, state.tenant_manager, websocket_manager=state.websocket_manager
        )
        logger.info("Tool accessor initialized successfully")
    except Exception as e:  # Broad catch: name the failing service, then abort boot
        logger.error(f"Failed to initialize tool accessor: {e}", exc_info=True)
        raise

    # Initialize auth with database session (for auto-login support)
    try:
        logger.info("Initializing authentication manager...")
        # Note: db parameter will be set later per-request for auto-login
        # The db_manager provides sessions, not a single session
        state.auth = AuthManager(state.config, db=None)
        logger.info("Auth manager initialized (mode-independent authentication)")
    except Exception as e:  # Broad catch: name the failing service, then abort boot
        logger.error(f"Failed to initialize auth manager: {e}", exc_info=True)
        raise

    # Load API key from environment if available
    api_key = os.getenv("API_KEY") or os.getenv("GILJO_MCP_API_KEY")
    if api_key:
        # Add the configured API key to AuthManager (for network clients)
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

    # Start heartbeat task (WebSocket manager already initialized earlier)
    try:
        logger.info("Starting WebSocket heartbeat task...")
        _start_supervised_heartbeat(state, interval=30)
        logger.info("WebSocket heartbeat started (interval: 30s, supervised)")
    except Exception as e:  # Broad catch: genuinely non-fatal -- boot continues without a heartbeat
        logger.error(f"Failed to start heartbeat task: {e}", exc_info=True)


def _start_supervised_heartbeat(state: APIState, interval: int = 30) -> None:
    """Create the heartbeat task and supervise it (BE-3008a).

    A done-callback restarts the task if it dies unexpectedly, so a latent
    crash in a broadcast path can no longer silently kill the heartbeat and let
    stale connections accumulate. A shutdown-driven ``cancel()`` is respected —
    the supervisor never resurrects a cancelled task. No restart counter/backoff
    by design (the crash source is fixed in api/websocket.py); each restart is
    logged so a storm would be visible.
    """

    def _supervise(task: asyncio.Task) -> None:
        if task.cancelled():
            return  # Shutdown cancelled it — do not resurrect.
        exc = task.exception()
        if exc is None:
            return  # Clean exit (the loop runs forever, so this is unexpected but harmless).
        logger.error("WebSocket heartbeat task died; restarting", exc_info=exc)
        try:
            import sentry_sdk

            sentry_sdk.add_breadcrumb(
                category="websocket",
                level="error",
                message="heartbeat task died; supervisor restarting",
            )
        except ImportError:
            pass  # CE without sentry-sdk installed — breadcrumb is a no-op.
        _start_supervised_heartbeat(state, interval=interval)

    heartbeat_task = asyncio.create_task(state.websocket_manager.start_heartbeat(interval=interval))
    heartbeat_task.add_done_callback(_supervise)
    state.heartbeat_task = heartbeat_task  # Store reference to prevent garbage collection
