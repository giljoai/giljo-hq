# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path


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

from api.app_state import GILJO_MODE


logger.info(f"GILJO_MODE: {GILJO_MODE}")

import sys as _sys
from pathlib import Path as _Path


_PROJECT_ROOT = str(_Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

from api.app_state import APIState, state  # noqa: F401 — canonical source, re-exported

from api.wiring.events import register_event_handlers as _register_event_handlers
from api.wiring.middleware import configure_middleware as _configure_middleware
from api.wiring.openapi import build_openapi_servers as _build_openapi_servers
from api.wiring.routers import register_routers as _register_routers


def _load_env_from_dotfile() -> None:
    from dotenv import load_dotenv

    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=False)
    logger.info(f"Environment variables loaded from .env file: {env_path}")

    _reconcile_giljo_mode_after_dotenv()

    jwt_secret = os.getenv("JWT_SECRET") or os.getenv("GILJO_MCP_SECRET_KEY") or os.getenv("SECRET_KEY")
    if jwt_secret:
        logger.info("JWT secret key found in environment")
    else:
        logger.error("JWT secret key NOT found in environment - authentication will fail")


def _reconcile_giljo_mode_after_dotenv() -> None:
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
    import asyncio
    import os
    import time

    from sqlalchemy import text
    from sqlalchemy.orm import configure_mappers

    warm_connections = max(1, int(os.getenv("GILJO_WARM_DB_CONNECTIONS", "3")))

    started = time.monotonic()
    try:
        configure_mappers()
        if getattr(state, "db_manager", None) is not None:

            async def _warm_one_connection() -> None:
                async with state.db_manager.AsyncSessionLocal() as session:
                    await session.execute(text("SELECT 1"))

            await asyncio.gather(*[_warm_one_connection() for _ in range(warm_connections)])
        logger.info(
            "Warm-up complete in %.0f ms (ORM mappers + %d pooled connection(s))",
            (time.monotonic() - started) * 1000,
            warm_connections,
        )
    except Exception:
        logger.exception("Warm-up phase failed (non-fatal)")


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    logger.info(
        "v1.2.1: MCP list_projects now hides completed/cancelled by default; "
        "use include_completed=true to retrieve archived projects."
    )

    from api.observability.sentry_init import init_sentry

    init_sentry(mode=GILJO_MODE)

    from giljo_mcp.licensing import LicenseValidator

    license_result = LicenseValidator().validate()
    if not license_result.valid:
        raise RuntimeError(f"License validation failed: {license_result.message}")
    state.license = license_result
    app.state.license = license_result
    logger.info("License: %s", license_result.message)

    await init_database(state)

    from api.startup.migration_check import check_pending_migrations

    state.pending_migration = await check_pending_migrations(state)
    if state.pending_migration:
        logger.warning("Database has pending migrations. Run: python update.py")

    await init_core_services(state)

    await init_event_bus(state)
    if state.event_bus is None:
        state.degraded_services.append("event_bus")

    await init_background_tasks(state)

    if should_run_background_jobs():
        await init_health_monitor(state)

        await init_silence_detector(state)

    await init_validation(state)

    app.state.db_manager = state.db_manager
    app.state.websocket_manager = state.websocket_manager
    app.state.websocket_broker = state.websocket_broker

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

    from api.endpoints.mcp_sdk_server import start_mcp_session_manager, stop_mcp_session_manager

    try:
        await start_mcp_session_manager()
    except Exception as e:
        logger.warning("Optional startup phase [mcp_session_manager] failed: %s — running in degraded mode", e)
        state.degraded_services.append("mcp_session_manager")

    from api.startup.cache_backends_gate import install_saas_cache_backends

    await install_saas_cache_backends(state, giljo_mode=GILJO_MODE)

    from api.startup.multiworker_guard_gate import assert_multiworker_prerequisites

    assert_multiworker_prerequisites(state, giljo_mode=GILJO_MODE)

    from api.startup.saas_enforcement_gate import (
        register_mcp_subscription_gate,
        register_saas_tenant_scoped_models,
        require_public_base_url,
    )

    require_public_base_url(giljo_mode=GILJO_MODE)
    register_saas_tenant_scoped_models(giljo_mode=GILJO_MODE)
    register_mcp_subscription_gate(giljo_mode=GILJO_MODE)

    from api.startup.oauth_hydration_gate import run_saas_oauth_hydration

    await run_saas_oauth_hydration(app)

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

    _deletion_reaper_task = None
    if GILJO_MODE == "saas" and should_run_background_jobs():
        try:
            import importlib as _il

            _del_reaper_mod = _il.import_module("giljo_mcp.saas.deletion.reaper")
            _del_restore_svc_mod = _il.import_module("giljo_mcp.saas.restore.service")
            _deletion_reaper_task = await _del_reaper_mod.start_deletion_reaper(
                state.db_manager.AsyncSessionLocal,
                _del_restore_svc_mod.build_storage_adapter_from_env(),
            )
            logger.info("Deletion reaper background task started")
        except Exception as e:
            logger.warning("Optional startup phase [deletion_reaper] failed: %s — running without deletion reaper", e)
            state.degraded_services.append("deletion_reaper")

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

    if GILJO_MODE == "saas":
        try:
            import importlib as _il

            _email_sync_mod = _il.import_module("giljo_mcp.saas.billing.email_sync_subscriber")
            await _email_sync_mod.register_email_sync_subscriber(state.event_bus, state.db_manager.AsyncSessionLocal)
            logger.info("Billing email-sync subscriber registered")
        except Exception as e:
            logger.warning("Optional startup phase [email_sync_subscriber] failed: %s — billing email sync disabled", e)
            state.degraded_services.append("email_sync_subscriber")

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

    if GILJO_MODE == "saas":
        try:
            import importlib as _il

            _lockout_mod = _il.import_module("giljo_mcp.saas.auth.lockout_notifier")
            await _lockout_mod.register_lockout_subscriber(state.event_bus)
            logger.info("Login-lockout notification subscriber registered")
        except Exception as e:
            logger.warning("Optional startup phase [lockout_notifier] failed: %s — lockout notices disabled", e)
            state.degraded_services.append("lockout_notifier")

    await _warm_up(state)

    state.startup_complete = True
    app.state.startup_complete = True

    if state.degraded_services:
        logger.error("Startup complete with degraded services: %s", ", ".join(state.degraded_services))
    logger.info("=" * 70)
    logger.info("API startup complete - All systems initialized")
    logger.info("=" * 70)

    yield

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

    from giljo_mcp import __version__ as giljo_version
    from giljo_mcp import branding

    docs_enabled = GILJO_MODE in ("ce", "")

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
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
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

    _configure_middleware(app)
    _register_routers(app)
    _register_event_handlers(app)

    from api.wiring.events import resolve_static_dir

    dist_dir = resolve_static_dir()
    if (dist_dir / "index.html").exists():
        _install_spa_fallback(app, dist_dir)

    return app


_NON_SPA_PREFIXES = ("/api", "/ws", "/mcp", "/health", "/docs", "/redoc", "/openapi.json")
_ASSET_PREFIXES = ("/assets",)


def _should_serve_spa(path: str) -> bool:
    return not path.startswith(_NON_SPA_PREFIXES + _ASSET_PREFIXES)


def _install_spa_fallback(app: FastAPI, dist_dir: Path) -> None:
    from starlette.responses import FileResponse
    from starlette.staticfiles import StaticFiles

    @app.exception_handler(404)
    async def spa_fallback(request, exc):
        if _should_serve_spa(request.url.path):
            return FileResponse(str(dist_dir / "index.html"))
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    app.mount("/", StaticFiles(directory=str(dist_dir), html=False), name="static")


from api.endpoints.mcp_sdk_server import get_mcp_asgi_app
from api.mcp_dispatcher import McpDispatcher


_fastapi_app = create_app()
app = McpDispatcher(_fastapi_app, get_mcp_asgi_app())
