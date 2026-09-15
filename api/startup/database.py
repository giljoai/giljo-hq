# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os

from api.app_state import APIState
from giljo_mcp.config_manager import get_config
from giljo_mcp.database import DatabaseManager
from giljo_mcp.logging import ErrorCode
from giljo_mcp.system_prompts import SystemPromptService


logger = logging.getLogger(__name__)


def _worker_count() -> int:
    try:
        return max(1, int(os.getenv("WEB_CONCURRENCY", "1")))
    except (TypeError, ValueError):
        return 1


def _broker_direct_connections(config) -> int:
    from api.broker import POSTGRES_BROKER_TYPES, resolve_broker_type
    from api.broker.postgres_notify import MAX_DB_CONNECTIONS_PER_PROCESS

    if resolve_broker_type(config) in POSTGRES_BROKER_TYPES:
        return MAX_DB_CONNECTIONS_PER_PROCESS
    return 0


def _reserved_slots() -> int:
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
    try:
        logger.info("Initializing configuration...")
        state.config = get_config()
        logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error(
            "config_load_failed error_code=%s error_message=%s",
            ErrorCode.API_INTERNAL_ERROR.value,
            str(e),
            exc_info=True,
        )
        raise


    logger.info("Initializing database connection...")
    db_url = os.getenv("DATABASE_URL")

    if db_url:
        logger.info("Using DATABASE_URL from environment")
    elif state.config.database:
        try:
            logger.info("Constructing database URL from configuration manager")
            db_url = state.config.database.get_connection_string()
            logger.debug(
                f"Database config: host={state.config.database.host}, port={state.config.database.port}, database={state.config.database.database_name}"
            )
        except Exception as _exc:
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
        state.db_manager = DatabaseManager(
            db_url,
            is_async=True,
            pool_size=state.config.database.pg_pool_size,
            max_overflow=state.config.database.pg_max_overflow,
        )
        logger.info("Database manager created successfully")

        check_connection_budget(
            state.config.database.pg_pool_size,
            state.config.database.pg_max_overflow,
            _worker_count(),
            state.config.database.pg_slot_budget,
            broker_per_worker=_broker_direct_connections(state.config),
            reserved_slots=_reserved_slots(),
            pgbouncer=os.getenv("GILJO_PGBOUNCER") == "1",
        )

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
    except Exception as e:
        logger.error(
            "database_init_failed error_code=%s error_message=%s",
            ErrorCode.DB_CONNECTION_FAILED.value,
            str(e),
            exc_info=True,
        )
        raise
