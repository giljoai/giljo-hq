# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
from urllib.parse import urlsplit

from sqlalchemy.exc import ProgrammingError

from api.app_state import APIState
from giljo_mcp.config_manager import get_config
from giljo_mcp.database import DatabaseManager
from giljo_mcp.logging import ErrorCode
from giljo_mcp.system_prompts import SystemPromptService


logger = logging.getLogger(__name__)

_DUPLICATE_SCHEMA_SQLSTATES = frozenset({"42P07", "42710"})


def _worker_count() -> int:
    raw = os.getenv("WEB_CONCURRENCY", "1")
    try:
        return max(1, int(raw))
    except ValueError as exc:
        raise ValueError(f"WEB_CONCURRENCY must be a whole number, got {raw!r}") from exc


def _broker_direct_connections(config) -> int:
    from api.broker import POSTGRES_BROKER_TYPES, resolve_broker_type
    from api.broker.postgres_notify import MAX_DB_CONNECTIONS_PER_PROCESS

    if resolve_broker_type(config) in POSTGRES_BROKER_TYPES:
        return MAX_DB_CONNECTIONS_PER_PROCESS
    return 0


def _reserved_slots() -> int:
    raw = os.getenv("GILJO_DB_RESERVED_SLOTS", "0")
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise ValueError(f"GILJO_DB_RESERVED_SLOTS must be a whole number, got {raw!r}") from exc


def check_connection_budget(
    pool_size,
    max_overflow,
    workers,
    slot_budget,
    broker_per_worker=0,
    reserved_slots=0,
    pgbouncer=False,
) -> None:
    numbers: dict[str, int] = {}
    for name, value in (
        ("pool_size", pool_size),
        ("max_overflow", max_overflow),
        ("workers", workers),
        ("slot_budget", slot_budget),
        ("broker_per_worker", broker_per_worker),
        ("reserved_slots", reserved_slots),
    ):
        try:
            numbers[name] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"DB connection budget input {name} must be a whole number, got {value!r}") from exc
    per_worker_pool = numbers["pool_size"] + numbers["max_overflow"]
    n_workers = numbers["workers"]
    budget = numbers["slot_budget"]
    broker = numbers["broker_per_worker"]
    reserved = numbers["reserved_slots"]

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

    target = urlsplit(db_url)
    logger.info("Connecting to database: %s:%s%s", target.hostname or "local socket", target.port or "", target.path)

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
            except ProgrammingError as ct_exc:
                if getattr(ct_exc.orig, "sqlstate", None) not in _DUPLICATE_SCHEMA_SQLSTATES:
                    raise
                logger.warning(
                    "create_tables_async() saw already-existing schema (migrations are authoritative): %s",
                    str(ct_exc).split("\n", 1)[0][:200],
                )

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
