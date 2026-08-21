# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Database initialization module

Handles database connection, table creation, and configuration loading.
Extracted from api/app.py lifespan function (lines ~160-214).
"""

import logging
import os

from api.app_state import APIState
from giljo_mcp.config_manager import get_config
from giljo_mcp.database import DatabaseManager
from giljo_mcp.logging import ErrorCode
from giljo_mcp.system_prompts import SystemPromptService


logger = logging.getLogger(__name__)


def _worker_count() -> int:
    """Resolve the uvicorn worker count this process is part of.

    The hosted platform's start-command config exports WEB_CONCURRENCY (prod
    default 4 since 2026-07-12) and passes --workers from that same variable
    (INF-9192), so uvicorn and every reader of this helper see one consistent
    value.
    A bad value falls back to 1 rather than crashing boot.
    """
    try:
        return max(1, int(os.getenv("WEB_CONCURRENCY", "1")))
    except (TypeError, ValueError):
        return 1


def _broker_direct_connections(config) -> int:
    """Direct DB connections the LISTEN/NOTIFY broker holds per worker process.

    INF-3009f: the postgres_notify broker connects OUTSIDE the SQLAlchemy pool
    (1 session-pinned LISTEN + a publish pool), so the budget check must count it
    separately or the "budget OK" line under-reports by up to 6 per worker.
    """
    from api.broker import POSTGRES_BROKER_TYPES, resolve_broker_type
    from api.broker.postgres_notify import MAX_DB_CONNECTIONS_PER_PROCESS

    if resolve_broker_type(config) in POSTGRES_BROKER_TYPES:
        return MAX_DB_CONNECTIONS_PER_PROCESS
    return 0


def _reserved_slots() -> int:
    """Slots to reserve for OTHER services sharing this database (env-declared).

    INF-3009f: another service sharing the database holds its own pools, invisible
    to this process. GILJO_DB_RESERVED_SLOTS lets each service declare that
    external usage so the budget math is honest. Unset/invalid -> 0 (single-service
    installs need nothing).
    """
    try:
        return max(0, int(os.getenv("GILJO_DB_RESERVED_SLOTS", "0")))
    except (TypeError, ValueError):
        logger.warning("Ignoring non-numeric GILJO_DB_RESERVED_SLOTS=%r", os.getenv("GILJO_DB_RESERVED_SLOTS"))
        return 0


def check_connection_budget(
    pool_size,
    max_overflow,
    workers,
    slot_budget,
    broker_per_worker=0,
    reserved_slots=0,
    pgbouncer=False,
) -> None:
    """Warn (never crash) when this service's aggregate connections overrun the DB slot budget.

    INF-3009a: each worker holds its own pool of up to ``pool_size + max_overflow``
    connections. With multiple workers the aggregate can exceed the database's total
    connection slots (managed Postgres ~100) and cause "too many connections" outages.
    This logs LOUDLY so the misconfig is visible, but deliberately does NOT raise —
    bricking CE/prod boot is worse than running over budget, and the budget itself is
    an estimate (see below). Non-numeric inputs (e.g. a mocked db_manager in tests)
    are skipped silently.

    INF-3009f: the check now counts ``broker_per_worker`` (the LISTEN/NOTIFY broker's
    direct connections, held outside the SQLAlchemy pool) and ``reserved_slots``
    (connections other services sharing the database hold, declared via
    GILJO_DB_RESERVED_SLOTS) — previously both were silently uncounted and the
    "budget OK" line under-reported by the broker's and external services'
    connections.

    With ``pgbouncer=True`` (GILJO_PGBOUNCER=1) the SQLAlchemy pool terminates at
    PgBouncer, not Postgres, so only the direct connections (broker + reserved) are
    scored against the Postgres slot budget; the pooled client-side total is logged
    for visibility. The authoritative post-cutover server budget is the pooler's
    own pool size x replicas, tracked on the platform's PgBouncer panel.
    """
    try:
        per_worker_pool = int(pool_size) + int(max_overflow)
        n_workers = int(workers)
        budget = int(slot_budget)
        broker = int(broker_per_worker)
        reserved = int(reserved_slots)
    except (TypeError, ValueError):
        logger.debug("Skipping DB connection-budget check: non-numeric pool inputs")
        return

    if pgbouncer:
        direct = n_workers * broker + reserved
        if direct > budget:
            logger.warning(
                "DB connection budget EXCEEDED (PgBouncer mode): direct connections "
                "%d worker(s) x broker %d + reserved %d = %d > budget %d. The SQLAlchemy "
                "pool (%d client connections) terminates at PgBouncer and is not counted. "
                "Continuing (non-fatal).",
                n_workers,
                broker,
                reserved,
                direct,
                budget,
                n_workers * per_worker_pool,
            )
        else:
            logger.info(
                "DB connection budget OK (PgBouncer mode): direct connections "
                "%d worker(s) x broker %d + reserved %d = %d <= budget %d. The SQLAlchemy "
                "pool (%d client connections) terminates at PgBouncer; the authoritative "
                "server budget is the pooler's pool size x replicas (the platform's PgBouncer panel).",
                n_workers,
                broker,
                reserved,
                direct,
                budget,
                n_workers * per_worker_pool,
            )
        return

    total = n_workers * (per_worker_pool + broker) + reserved
    if total > budget:
        logger.warning(
            "DB connection budget EXCEEDED: %d worker(s) x (pool_size %d + max_overflow %d "
            "+ broker %d) + reserved %d = %d connections > budget %d. Lower "
            "GILJO_PG_POOL_SIZE / GILJO_PG_MAX_OVERFLOW or WEB_CONCURRENCY, or raise "
            "GILJO_DB_SLOT_BUDGET. Continuing (non-fatal).",
            n_workers,
            pool_size,
            max_overflow,
            broker,
            reserved,
            total,
            budget,
        )
    else:
        logger.info(
            "DB connection budget OK: %d worker(s) x (pool_size %d + max_overflow %d "
            "+ broker %d) + reserved %d = %d <= budget %d (this service only; declare "
            "other services sharing the database via GILJO_DB_RESERVED_SLOTS).",
            n_workers,
            pool_size,
            max_overflow,
            broker,
            reserved,
            total,
            budget,
        )


async def init_database(state: APIState) -> None:
    """Initialize database connection and configuration

    Args:
        state: APIState instance to populate with db_manager, config, and system_prompt_service

    Raises:
        ValueError: If database URL is not configured
        Exception: If database initialization fails
    """
    try:
        # Initialize configuration
        logger.info("Initializing configuration...")
        state.config = get_config()  # Use the singleton getter
        logger.info("Configuration loaded successfully")
        # Bind address derived from install-time network choice (127.0.0.1 for localhost, 0.0.0.0 for LAN/WAN with HTTPS via mkcert)
    except Exception as e:  # Broad catch: database initialization resilience
        logger.error(
            "config_load_failed error_code=%s error_message=%s",
            ErrorCode.API_INTERNAL_ERROR.value,
            str(e),
            exc_info=True,
        )
        raise

    # v3.0: Setup mode removed - all access requires authentication

    # Initialize database (ALWAYS - install.py creates DB before API starts)
    # v3.0: No "setup mode without database" - database exists from installation
    # Check for DATABASE_URL in environment first
    logger.info("Initializing database connection...")
    db_url = os.getenv("DATABASE_URL")

    if db_url:
        logger.info("Using DATABASE_URL from environment")
    elif state.config.database:
        # Construct database URL using configuration manager (handles env + migrations)
        try:
            logger.info("Constructing database URL from configuration manager")
            db_url = state.config.database.get_connection_string()
            logger.debug(
                f"Database config: host={state.config.database.host}, port={state.config.database.port}, database={state.config.database.database_name}"
            )
        except Exception as _exc:  # Broad catch: database initialization resilience
            logger.exception(
                "database_url_build_failed error_code=%s",
                ErrorCode.DB_CONNECTION_FAILED.value,
            )
            raise

    if not db_url:
        logger.error(
            "database_config_missing error_code=%s",
            ErrorCode.DB_CONNECTION_FAILED.value,
        )
        raise ValueError("Database URL not configured. PostgreSQL is required.")

    logger.info(f"Connecting to database: {db_url.split('@')[-1] if '@' in db_url else db_url}")

    try:
        # INF-3009a: pass the explicit, authoritative pool knob from config
        # (env-driven via GILJO_PG_POOL_SIZE / GILJO_PG_MAX_OVERFLOW). No psutil
        # host-RAM heuristic. config.database is guaranteed present here — the
        # missing-config path raised above before reaching this point.
        state.db_manager = DatabaseManager(
            db_url,
            is_async=True,
            pool_size=state.config.database.pg_pool_size,
            max_overflow=state.config.database.pg_max_overflow,
        )
        logger.info("Database manager created successfully")

        # INF-3009a: worker-count-aware sanity check. Logs loudly when the
        # aggregate pool would exceed the DB slot budget; never crashes boot.
        # INF-3009f: broker + declared-external connections counted; PgBouncer-aware.
        check_connection_budget(
            state.config.database.pg_pool_size,
            state.config.database.pg_max_overflow,
            _worker_count(),
            state.config.database.pg_slot_budget,
            broker_per_worker=_broker_direct_connections(state.config),
            reserved_slots=_reserved_slots(),
            pgbouncer=os.getenv("GILJO_PGBOUNCER") == "1",
        )

        # BE-3002a (schema source of truth): on SaaS, Alembic is the ONLY schema
        # writer. SaaS prod runs ``alembic upgrade heads`` via the platform's
        # pre-deploy hook before the app boots, so create_all is redundant AND
        # must not run — a
        # model table added without a migration must NOT silently materialise in
        # the live billing DB. Skipping the call here makes SaaS boot perform ZERO
        # DDL. (The test bootstrap calls create_tables_async() directly, not via
        # this boot path, so test schema provisioning is unaffected.) CE keeps the
        # call; create_tables_async() itself then no-ops when alembic_version is
        # already present, so CE migrated installs also perform zero boot DDL.
        if os.getenv("GILJO_MODE", "").lower() == "saas":
            logger.info(
                "SaaS mode: skipping create_tables_async -- Alembic (preDeploy) is the authoritative "
                "schema writer; boot performs zero DDL"
            )
        else:
            logger.info("Creating database tables...")
            try:
                await state.db_manager.create_tables_async()
                logger.info("Database tables created/verified successfully")
            except Exception as ct_exc:
                # When migrations (alembic upgrade head) already provisioned the
                # schema -- e.g. containerized deploys that run migrations as a
                # pre-deploy hook before the app starts -- create_all() will hit
                # DuplicateTable
                # errors trying to recreate indexes (SQLAlchemy's create_all does
                # checkfirst=True for tables but not for indexes defined in
                # __table_args__). Migrations are authoritative; treat this as a
                # warning, not a fatal error. CE/dev paths that haven't run
                # migrations yet still get the create_all behavior.
                err_str = str(ct_exc).lower()
                if "already exists" in err_str or "duplicatetable" in err_str:
                    logger.warning(
                        "create_tables_async() saw already-existing schema (migrations are authoritative): %s",
                        str(ct_exc).split("\n", 1)[0][:200],
                    )
                else:
                    raise

        state.system_prompt_service = SystemPromptService(state.db_manager)
        logger.info("System prompt service initialized")
    except Exception as e:  # Broad catch: database initialization resilience
        logger.error(
            "database_init_failed error_code=%s error_message=%s",
            ErrorCode.DB_CONNECTION_FAILED.value,
            str(e),
            exc_info=True,
        )
        raise
