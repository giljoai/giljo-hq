# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
FastAPI application for Giljo HQ
Provides REST API and WebSocket endpoints for orchestration system

This module is the application ASSEMBLER plus the startup/lifespan phase
sequence. The stateless wiring groups (middleware, routers, route/event
handlers, websocket helpers, OpenAPI servers) were extracted into
behavior-preserving free functions in ``api.wiring`` (BE-6042b split of the
former 1,237-line god-module) and are imported + re-invoked here in the same
order. ``create_app``, the module-level ``app``, and the ``lifespan`` /
``_warm_up`` / ``_load_env_from_dotfile`` startup helpers stay here — the
lifespan's broad startup-resilience ``except Exception`` blocks live under this
file's existing ``BLE001`` per-file-ignore.

The load-bearing private aliases (``_configure_middleware``, ``_register_routers``,
``_build_openapi_servers``, ``_register_event_handlers``) are re-exported from the
wiring package so existing importers and ``patch("api.app.GILJO_MODE", ...)``
tests keep resolving them through the ``api.app`` namespace exactly as before.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path


# Set up logging early to catch import issues.
# Level honors the LOG_LEVEL env var (default INFO), mirroring the canonical
# logging setup in giljo_mcp.logging. Never hardcode DEBUG here: this runs at
# import time before .env loads, so a hardcoded level would force the entire
# app to that level on every deploy regardless of LOG_LEVEL or uvicorn
# --log-level, flooding prod logs and adding per-request I/O overhead.
_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level, format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
)
logger = logging.getLogger(__name__)
logger.info("Loading FastAPI application...")

try:
    from fastapi import FastAPI

    logger.info("FastAPI and core dependencies loaded successfully")
except ImportError as e:
    logger.error(f"Failed to import FastAPI dependencies: {e}", exc_info=True)
    raise

# Edition detection: canonical source is api.app_state.
# NOTE: GILJO_MODE is read from os.environ at api.app_state import time.
# .env loading has been deferred to the FastAPI lifespan (closes seq 100),
# so GILJO_MODE here reflects only the process-level environment, not .env.
# Operators who need GILJO_MODE driven by .env must export it before launch
# or re-resolve it inside the lifespan after _load_env_from_dotfile() runs.
from api.app_state import GILJO_MODE


logger.info(f"GILJO_MODE: {GILJO_MODE}")

# Ensure project root is on sys.path for module resolution
# (api/ is not a pip package — it needs the project root on sys.path)
import sys as _sys
from pathlib import Path as _Path


_PROJECT_ROOT = str(_Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

from api.app_state import APIState, state  # noqa: F401 — canonical source, re-exported

# Wiring groups (BE-6042b). Imported as the private aliases the rest of the
# codebase + tests resolve via the ``api.app`` namespace. The SaaS gates inside
# configure_middleware / register_routers read ``api.app.GILJO_MODE`` at call
# time, so patching it here still drives them.
from api.wiring.events import register_event_handlers as _register_event_handlers
from api.wiring.middleware import configure_middleware as _configure_middleware
from api.wiring.openapi import build_openapi_servers as _build_openapi_servers
from api.wiring.routers import register_routers as _register_routers


def _load_env_from_dotfile() -> None:
    """Load .env into os.environ. Invoked from the FastAPI lifespan, never at import.

    Uses ``override=False`` so a process-level environment variable always wins
    over a .env entry. This relocation closes audit seq 100 (load_dotenv at
    module-import) and seq 97 (api/__init__.py import-time DATABASE_URL
    mutation — the mutation came from this same load_dotenv call propagating
    DATABASE_URL via the api package).
    """
    from dotenv import load_dotenv

    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=False)
    logger.info(f"Environment variables loaded from .env file: {env_path}")

    # SEC-9131: app_state latches GILJO_MODE at import time; load_dotenv(override=False)
    # can introduce a different GILJO_MODE afterwards, so call-time os.environ readers
    # would disagree with import-latched readers. Re-pin os.environ to the latch.
    _reconcile_giljo_mode_after_dotenv()

    jwt_secret = os.getenv("JWT_SECRET") or os.getenv("GILJO_MCP_SECRET_KEY") or os.getenv("SECRET_KEY")
    if jwt_secret:
        logger.info("JWT secret key found in environment")
    else:
        logger.error("JWT secret key NOT found in environment - authentication will fail")


def _reconcile_giljo_mode_after_dotenv() -> None:
    """Re-pin ``os.environ["GILJO_MODE"]`` to the import-time latch if .env changed it.

    A mismatch means a mixed-edition boot (call-time readers disagree with the
    ``app_state`` latch); log CRITICAL and re-pin so every reader agrees (SEC-9131).
    """
    dotenv_mode = os.environ.get("GILJO_MODE", "").strip().lower()
    if not dotenv_mode or dotenv_mode == GILJO_MODE:
        return
    logger.critical(
        "GILJO_MODE split-brain: .env set GILJO_MODE=%r after the import latch was %r; "
        "re-pinning to the latch (SEC-9131). Export GILJO_MODE before launch to run in %r.",
        dotenv_mode,
        GILJO_MODE,
        dotenv_mode,
    )
    os.environ["GILJO_MODE"] = GILJO_MODE


async def _warm_up(state) -> None:
    """Pre-warm cold-start hot paths so the first real request isn't slow.

    Runs during startup BEFORE the app reports ready, so the platform
    healthcheck only goes green once warm and the first user is never the one
    paying the cold-start cost. Two dominant costs are addressed:

      1. Empty DB connection pool — the first query otherwise pays a fresh
         TCP + TLS + auth handshake to Postgres. A raw ``SELECT 1`` establishes
         a pooled connection now. It is a plain text statement (not an ORM
         model query), so it does not trip the fail-closed tenant guard.
      2. Lazy SQLAlchemy mapper configuration — ``configure_mappers()`` forces
         all ORM mappers to configure now (no DB, no tenant context) instead of
         on the first real query.

    BE-6029: warms SEVERAL pooled connections, not one. The first user after a
    deploy (e.g. launching a job) fires multiple concurrent queries; on a cold
    pool each otherwise pays its own TCP+TLS+auth handshake, and that latency
    spike around connect time is what let the hosting edge reap the still-idle
    WebSocket before the heartbeat established it. Pre-establishing a handful of
    connections removes that first-burst stall.

    Best-effort: any failure is logged and swallowed so warm-up can never block
    or crash boot. Bounded to a few seconds — far under the healthcheck timeout.
    """
    import asyncio
    import os
    import time

    from sqlalchemy import text
    from sqlalchemy.orm import configure_mappers

    # How many pooled connections to pre-establish. A job launch + dashboard
    # load open several at once; default 3 covers the typical first burst.
    warm_connections = max(1, int(os.getenv("GILJO_WARM_DB_CONNECTIONS", "3")))

    started = time.monotonic()
    try:
        configure_mappers()
        if getattr(state, "db_manager", None) is not None:

            async def _warm_one_connection() -> None:
                # Plain text statement (not an ORM model query) so it does not
                # trip the fail-closed tenant guard.
                async with state.db_manager.AsyncSessionLocal() as session:
                    await session.execute(text("SELECT 1"))

            # Open them CONCURRENTLY so the pool grows to `warm_connections`
            # distinct connections rather than reusing a single one serially.
            await asyncio.gather(*[_warm_one_connection() for _ in range(warm_connections)])
        logger.info(
            "Warm-up complete in %.0f ms (ORM mappers + %d pooled connection(s))",
            (time.monotonic() - started) * 1000,
            warm_connections,
        )
    except Exception:
        # ERROR + traceback so Sentry's LoggingIntegration (event_level=ERROR)
        # raises an issue — a boot-time warm-up failure (e.g. DB unreachable)
        # is worth an alert even though it is non-fatal and boot continues.
        logger.exception("Warm-up phase failed (non-fatal)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - orchestrates startup and shutdown"""
    _load_env_from_dotfile()

    from api.startup import (
        init_background_tasks,
        init_core_services,
        init_database,
        init_event_bus,
        init_health_monitor,
        init_silence_detector,
        init_validation,
        shutdown,
    )
    from api.startup.background_jobs_gate import should_run_background_jobs

    logger.info("=" * 70)
    logger.info("Starting Giljo HQ API...")
    logger.info("=" * 70)
    # v1.2.1: list_projects default behavior change.
    # MCP `list_projects` now excludes lifecycle-finished statuses
    # (completed, cancelled) by default. Pass include_completed=True to
    # restore the previous behavior of returning archived projects.
    logger.info(
        "v1.2.1: MCP list_projects now hides completed/cancelled by default; "
        "use include_completed=true to retrieve archived projects."
    )

    # Phase 0a: Sentry init (SaaS only — INF-5063).
    # init_sentry() short-circuits in CE; the gate IS the CE/SaaS boundary here.
    from api.observability.sentry_init import init_sentry

    init_sentry(mode=GILJO_MODE)

    # Phase 0: License validation
    # [CE] License validation — CE always passes. Commercial builds enforce here.
    from giljo_mcp.licensing import LicenseValidator

    license_result = LicenseValidator().validate()
    if not license_result.valid:
        raise RuntimeError(f"License validation failed: {license_result.message}")
    state.license = license_result
    app.state.license = license_result
    logger.info("License: %s", license_result.message)

    # Phase 1: Database and configuration
    await init_database(state)

    # Phase 1.5: Check for pending migrations (read-only)
    try:
        from api.startup.migration_check import check_pending_migrations

        state.pending_migration = await check_pending_migrations(state)
        if state.pending_migration:
            logger.warning("Database has pending migrations. Run: python update.py")
    except Exception as e:
        logger.warning("Could not check migration status: %s", e)

    # Phase 2: Core services
    await init_core_services(state)

    # Phase 3: Event bus and WebSocket listener (optional — REST API works without it)
    await init_event_bus(state)
    if state.event_bus is None:
        state.degraded_services.append("event_bus")

    # Phase 4: Background tasks (optional — individual tasks handle their own failures)
    await init_background_tasks(state)

    # Phase 5/6: Agent health monitoring + silence detection. INF-3009b: these are
    # cross-tenant background scans that mutate agent status / notify orchestrators,
    # so under WEB_CONCURRENCY>1 they would double-fail agents and duplicate notices.
    # Gated behind GILJO_RUN_BACKGROUND_JOBS (default ON → CE + un-split SaaS
    # unchanged) so the dedicated worker service owns them.
    if should_run_background_jobs():
        # Phase 5: Health monitoring (optional — already degrades gracefully)
        await init_health_monitor(state)

        # Phase 6: Silence detection (optional — already degrades gracefully)
        await init_silence_detector(state)

    # Phase 7: Validation (optional — already degrades gracefully)
    await init_validation(state)

    # Expose db_manager and websocket_manager directly on app.state
    # This must be done AFTER initialization, not in create_app()
    app.state.db_manager = state.db_manager
    app.state.websocket_manager = state.websocket_manager
    app.state.websocket_broker = state.websocket_broker

    # Suppress Windows ProactorEventLoop ConnectionResetError noise
    # (Python 3.12+ on Windows: browser closes keep-alive connections,
    # proactor transport logs ERROR trying to shutdown already-closed sockets)
    import sys

    if sys.platform == "win32":
        loop = asyncio.get_running_loop()
        _original_handler = loop.get_exception_handler()

        def _suppress_connection_reset(loop, context):
            exc = context.get("exception")
            if isinstance(exc, ConnectionResetError):
                return
            if _original_handler:
                _original_handler(loop, context)
            else:
                loop.default_exception_handler(context)

        loop.set_exception_handler(_suppress_connection_reset)

    # Phase 8: MCP SDK session manager (optional — REST/dashboard work without it)
    from api.endpoints.mcp_sdk_server import start_mcp_session_manager, stop_mcp_session_manager

    try:
        await start_mcp_session_manager()
    except Exception as e:  # Broad catch: startup resilience, non-fatal initialization
        logger.warning("Optional startup phase [mcp_session_manager] failed: %s — running in degraded mode", e)
        state.degraded_services.append("mcp_session_manager")

    # Phase 8.5: OAuth/rate-limiter/license cache backends (SaaS only — INF-5074,
    # fail-loud policy INF-3009c). Unlike the other "optional, degrade gracefully"
    # phases in this function, a configured-but-unreachable Redis is NOT caught
    # here — install_saas_cache_backends raises, which propagates out of
    # lifespan() and aborts uvicorn startup, the same fail-loud pattern as the
    # Phase 0 license-validation check above. See that module's docstring for
    # the full unset/reachable/unreachable contract.
    from api.startup.cache_backends_gate import install_saas_cache_backends

    await install_saas_cache_backends(state, giljo_mode=GILJO_MODE)

    # Phase 8.55: Multi-worker boot fence (INF-3009e). Refuses to start under
    # WEB_CONCURRENCY>1 unless every cross-worker prerequisite is live (broker,
    # background-job split, and — SaaS only — shared cache backend + tenant
    # rate-limit store). No-op for a single worker, so CE and un-split SaaS are
    # byte-identical to today. Runs AFTER Phase 8.5 because it consumes the
    # redis_mode that install_saas_cache_backends() sets, and BEFORE the 8.6/8.7
    # enforcement wiring so a misconfigured multi-worker boot aborts early. Like
    # the license and Redis gates above, its RuntimeError is NOT caught here —
    # it propagates out of lifespan() and stops uvicorn (fail-loud).
    from api.startup.multiworker_guard_gate import assert_multiworker_prerequisites

    assert_multiworker_prerequisites(state, giljo_mode=GILJO_MODE)

    # Phases 8.6/8.7: SaaS enforcement wiring (tenant-scope widening + /mcp gate).
    # Extracted into api/startup/saas_enforcement_gate.py so the SEC-9131 fail-loud
    # policy is unit-testable (mirrors INF-3009c's extraction of Phase 8.5 into
    # cache_backends_gate.py). Both gates are no-ops for CE and use importlib so no
    # static saas import crosses the boundary — the Deletion Test holds. In saas
    # mode a registration failure now ABORTS boot rather than degrading silently
    # (BE-6069 incident class): enforcement absent must never look like a healthy boot.
    from api.startup.saas_enforcement_gate import (
        register_mcp_subscription_gate,
        register_saas_tenant_scoped_models,
        require_public_base_url,
    )

    # Phase 8.58 (SEC-9227h / M7): SaaS must never boot without the origin pin —
    # otherwise the OAuth issuer/audience and emailed lifecycle links silently
    # derive from the attacker-influenceable Host header. Runs BEFORE 8.6/8.7 so
    # a misconfigured deploy aborts as early as possible. No-op for CE.
    require_public_base_url(giljo_mode=GILJO_MODE)
    register_saas_tenant_scoped_models(giljo_mode=GILJO_MODE)
    register_mcp_subscription_gate(giljo_mode=GILJO_MODE)

    # Phase 9: Trial reaper (SaaS only)
    # Uses importlib to satisfy CE/SaaS import boundary (no static import from saas/).
    # INF-3009b: also gated on should_run_background_jobs() (default ON) so this
    # background job runs in exactly one process, preventing duplicate work when
    # more than one worker process is live.
    _trial_reaper_task = None
    if GILJO_MODE == "saas" and should_run_background_jobs():
        try:
            import importlib

            _reaper_mod = importlib.import_module("giljo_mcp.saas.trial.reaper")
            _trial_reaper_task = await _reaper_mod.start_trial_reaper(state.db_manager.AsyncSessionLocal)
            logger.info("Trial reaper background task started")
        except Exception as e:
            logger.warning("Optional startup phase [trial_reaper] failed: %s — running without trial reaper", e)
            state.degraded_services.append("trial_reaper")

    # Phase 10: Deletion reaper (SaaS only)
    # INF-3009b: also gated on should_run_background_jobs() (default ON) so this
    # destructive sweep runs in exactly one process, never racing.
    _deletion_reaper_task = None
    if GILJO_MODE == "saas" and should_run_background_jobs():
        try:
            import importlib as _il

            _del_reaper_mod = _il.import_module("giljo_mcp.saas.deletion.reaper")
            # BE-9040 WP1: shares the storage adapter factory with the backup
            # scheduler ("one selection point") so both agree on the same
            # storage configuration — see saas/ for what each step does.
            _del_restore_svc_mod = _il.import_module("giljo_mcp.saas.restore.service")
            _deletion_reaper_task = await _del_reaper_mod.start_deletion_reaper(
                state.db_manager.AsyncSessionLocal,
                _del_restore_svc_mod.build_storage_adapter_from_env(),
            )
            logger.info("Deletion reaper background task started")
        except Exception as e:
            logger.warning("Optional startup phase [deletion_reaper] failed: %s — running without deletion reaper", e)
            state.degraded_services.append("deletion_reaper")

    # Phase 10.6: Backup snapshot scheduler (SaaS only — INF-6139)
    # Periodic per-tenant snapshot job; see saas/ for the schedule and storage
    # backend. Uses importlib to satisfy the CE/SaaS import boundary (no static
    # import from saas/). INF-3009b: also gated on should_run_background_jobs()
    # (default ON) so this job runs in exactly one process, not once per worker.
    _backup_scheduler_task = None
    if GILJO_MODE == "saas" and should_run_background_jobs():
        try:
            import importlib as _il

            _backup_sched_mod = _il.import_module("giljo_mcp.saas.backup.scheduler")
            _restore_svc_mod = _il.import_module("giljo_mcp.saas.restore.service")
            _backup_adapter = _restore_svc_mod.build_storage_adapter_from_env()
            _backup_scheduler_task = await _backup_sched_mod.start_backup_scheduler(
                state.db_manager.AsyncSessionLocal, _backup_adapter
            )
            logger.info("Backup snapshot scheduler background task started")
        except Exception as e:
            logger.warning("Optional startup phase [backup_scheduler] failed: %s — running without backup scheduler", e)
            state.degraded_services.append("backup_scheduler")

    # Phase 10.5: Billing email-sync subscriber (SaaS only — BE-6011)
    # Subscribes a SaaS handler to the neutral CE user:email:changed signal so
    # billing records stay in sync with the account's email; see saas/ for
    # the sync target. Uses importlib to satisfy the CE/SaaS import boundary
    # (no static import from saas/).
    if GILJO_MODE == "saas":
        try:
            import importlib as _il

            _email_sync_mod = _il.import_module("giljo_mcp.saas.billing.email_sync_subscriber")
            await _email_sync_mod.register_email_sync_subscriber(state.event_bus, state.db_manager.AsyncSessionLocal)
            logger.info("Billing email-sync subscriber registered")
        except Exception as e:
            logger.warning("Optional startup phase [email_sync_subscriber] failed: %s — billing email sync disabled", e)
            state.degraded_services.append("email_sync_subscriber")

    # Phase 10.5b: Email-change dual-notification subscriber (SaaS only — FE-6008)
    # Notifies BOTH the old and new address that the email was changed. Separate
    # concern from billing email-sync above; gated via importlib for the CE/SaaS
    # import boundary (no static import from saas/).
    if GILJO_MODE == "saas":
        try:
            import importlib as _il

            _email_change_mod = _il.import_module("giljo_mcp.saas.auth.email_change_notifier")
            await _email_change_mod.register_email_change_subscriber(state.event_bus)
            logger.info("Email-change notification subscriber registered")
        except Exception as e:
            logger.warning(
                "Optional startup phase [email_change_notifier] failed: %s — email-change notices disabled", e
            )
            state.degraded_services.append("email_change_notifier")

    # Phase 10.5c: Login-lockout email subscriber (SaaS only — SEC-3001a Wave 2).
    # Emails the user an "unusual sign-in activity" notice when their account is
    # locked after too many failed logins. CE locks accounts too but has no email
    # backend, so this notice is SaaS-only; gated via importlib (no static saas/ import).
    if GILJO_MODE == "saas":
        try:
            import importlib as _il

            _lockout_mod = _il.import_module("giljo_mcp.saas.auth.lockout_notifier")
            await _lockout_mod.register_lockout_subscriber(state.event_bus)
            logger.info("Login-lockout notification subscriber registered")
        except Exception as e:
            logger.warning("Optional startup phase [lockout_notifier] failed: %s — lockout notices disabled", e)
            state.degraded_services.append("lockout_notifier")

    # Phase 11: Warm-up (cold-start mitigation — INF-6019). Runs before the app
    # reports ready so the first real request lands on a hot DB pool + configured
    # ORM mappers instead of paying the cold-start cost.
    await _warm_up(state)

    # Mark startup complete
    state.startup_complete = True
    app.state.startup_complete = True

    if state.degraded_services:
        # BE-9053: ERROR (not WARNING) — Sentry's logging integration captures
        # ERROR-level records as events, so a boot with the backup scheduler or
        # a reaper silently OFF alerts the operator instead of telling nobody.
        logger.error("Startup complete with degraded services: %s", ", ".join(state.degraded_services))
    logger.info("=" * 70)
    logger.info("API startup complete - All systems initialized")
    logger.info("=" * 70)

    yield

    # Shutdown
    if _trial_reaper_task is not None:
        _trial_reaper_task.cancel()
        with suppress(asyncio.CancelledError):
            await _trial_reaper_task
        logger.info("Trial reaper stopped")

    if _deletion_reaper_task is not None:
        _deletion_reaper_task.cancel()
        with suppress(asyncio.CancelledError):
            await _deletion_reaper_task
        logger.info("Deletion reaper stopped")

    if _backup_scheduler_task is not None:
        _backup_scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await _backup_scheduler_task
        logger.info("Backup snapshot scheduler stopped")

    if "mcp_session_manager" not in state.degraded_services:
        await stop_mcp_session_manager()
    await shutdown(state)

    logger.info("API shutdown complete")


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""

    from giljo_mcp import __version__ as giljo_version
    from giljo_mcp import branding

    app = FastAPI(
        title=f"{branding.PRODUCT_NAME} API v{giljo_version} - Community Edition",
        description=f"""
        ## Multi-Agent Orchestration System REST API

        {branding.PRODUCT_NAME} provides a comprehensive REST API for managing AI agent orchestration,
        enabling coordinated development teams that can tackle projects of unlimited complexity.

        ### Key Features:
        - **Project Management**: Create and manage development projects with AI agents
        - **Agent Orchestration**: Coordinate multiple specialized AI agents working together
        - **Message Queue**: Reliable inter-agent communication with acknowledgment
        - **Task Tracking**: Capture and manage technical debt and work items
        - **Configuration**: Flexible runtime and tenant-specific configuration
        - **Real-time Updates**: WebSocket support for live monitoring
        - **Statistics**: Comprehensive metrics and performance monitoring

        ### Authentication:
        API authentication can be enabled via configuration. Supports API key and OAuth methods.

        ### WebSocket:
        Connect to `/ws/{{client_id}}` for real-time updates on projects, agents, and messages.

        ### Rate Limiting:
        Rate limiting can be configured per tenant. Default: 60 requests/minute.
        """,
        version=giljo_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {
                "name": "projects",
                "description": "Project management operations - create, update, and monitor AI development projects",
            },
            {
                "name": "messages",
                "description": "Inter-agent messaging - send, acknowledge, and complete messages between agents",
            },
            {"name": "tasks", "description": "Task management - track and manage development tasks and technical debt"},
            {"name": "configuration", "description": "Configuration management - system and tenant-specific settings"},
            {
                "name": "statistics",
                "description": "Statistics and monitoring - system metrics, performance, and health checks",
            },
        ],
        servers=_build_openapi_servers(),
        contact={
            "name": "GiljoAI Support",
            "url": "https://github.com/giljoai/mcp-orchestrator",
            "email": "infoteam@giljo.ai",
        },
        license_info={
            "name": "Elastic License 2.0",
            "url": "https://github.com/giljoai/giljo-hq/blob/master/LICENSE",
        },
    )

    # Configure middleware, routers, and event handlers
    _configure_middleware(app)
    _register_routers(app)
    _register_event_handlers(app)

    # Production frontend serving (single-port mode)
    # Must be LAST so API routes registered above take priority
    dist_dir = Path(state.config.get_nested("paths.static", "frontend/dist")) if state.config else Path("frontend/dist")
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        _install_spa_fallback(app, dist_dir)

    return app


# Infra/API prefixes that must return a real 404 (JSON), never the SPA shell.
_NON_SPA_PREFIXES = ("/api", "/ws", "/mcp", "/health", "/docs", "/redoc", "/openapi.json")
# Build-asset prefix. FE-6120: a request to a missing hashed asset must 404, NOT
# fall through to index.html (text/html). Returning index.html for /assets/* makes
# a stale lazy-chunk look like a 200 the CDN then caches, and the browser refuses
# to execute HTML as a JS module — the stale-chunk failure the FE handler recovers
# from. A clean 404 keeps the FE detection unambiguous and stops CDN amplification.
_ASSET_PREFIXES = ("/assets",)


def _should_serve_spa(path: str) -> bool:
    """True when a 404 path should fall through to index.html (Vue Router)."""
    return not path.startswith(_NON_SPA_PREFIXES + _ASSET_PREFIXES)


def _install_spa_fallback(app: FastAPI, dist_dir: Path) -> None:
    """Register the single-port SPA fallback: serve index.html for unknown
    non-API routes, a real 404 for API/infra paths and missing build assets."""
    from starlette.responses import FileResponse
    from starlette.staticfiles import StaticFiles

    @app.exception_handler(404)
    async def spa_fallback(request, exc):
        """SPA fallback: non-API 404s serve index.html for Vue Router."""
        if _should_serve_spa(request.url.path):
            return FileResponse(str(dist_dir / "index.html"))
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    app.mount("/", StaticFiles(directory=str(dist_dir), html=False), name="static")


# Export for uvicorn.
# BE-6060c: the top-level McpDispatcher sits ABOVE the FastAPI middleware onion so /mcp
# traffic is routed to the MCP ASGI app (unbuffered, no 307) before any FastAPI
# middleware runs, while every other scope — including the "lifespan" scope that starts
# the shared MCP session manager — flows to the FastAPI app unchanged. get_mcp_asgi_app()
# is import-safe at module load (it lazily builds the session-manager singleton, which
# the FastAPI lifespan then runs); construction order is correct because the lifespan
# reuses that same singleton rather than rebuilding it. uvicorn target stays api.app:app.
from api.endpoints.mcp_sdk_server import get_mcp_asgi_app
from api.mcp_dispatcher import McpDispatcher


_fastapi_app = create_app()
app = McpDispatcher(_fastapi_app, get_mcp_asgi_app())
