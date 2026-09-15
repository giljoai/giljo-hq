# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
from contextlib import asynccontextmanager, contextmanager, suppress
from urllib.parse import quote_plus
from uuid import uuid4

from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from .logging.error_codes import ErrorCode
from .models import (
    Base,
)
from .tenant import TenantManager


logger = logging.getLogger(__name__)

POOL_RECYCLE_SECONDS = 3600

DEFAULT_POOL_SIZE = 5
DEFAULT_MAX_OVERFLOW = 5


def _pgbouncer_connect_args() -> dict | None:
    if os.getenv("GILJO_PGBOUNCER") != "1":
        return None
    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


from . import tenant_guard as _tenant_guard  # noqa: E402  (after logger/constants above)
from .tenant_guard import (  # noqa: E402,F401  (re-exported for back-compat)
    TENANT_BYPASS_MODELS_KEY,
    TENANT_BYPASS_REASON_KEY,
    TENANT_CONTEXT_SOURCE_KEY,
    TenantIsolationError,
    register_tenant_scoped_models,
    tenant_isolation_bypass,
    tenant_session_context,
)


def __getattr__(name: str):
    return getattr(_tenant_guard, name)


class DatabaseManager:

    def __init__(
        self,
        database_url: str | None = None,
        is_async: bool = False,
        pool_size: int | None = None,
        max_overflow: int | None = None,
        use_null_pool: bool = False,
    ):
        if not database_url:
            raise ValueError("Database URL is required")

        self.database_url = database_url
        self.is_async = is_async
        self.use_null_pool = use_null_pool

        if pool_size is None:
            pool_size = DEFAULT_POOL_SIZE
        if max_overflow is None:
            max_overflow = DEFAULT_MAX_OVERFLOW

        self.pool_size = pool_size
        self.max_overflow = max_overflow

        if "postgresql" not in self.database_url:
            raise ValueError("Only PostgreSQL databases are supported")

        if self.is_async:
            self.async_engine = self._create_async_engine()
            self.AsyncSessionLocal = sessionmaker(self.async_engine, class_=AsyncSession, expire_on_commit=False)
        else:
            self.engine = self._create_sync_engine()
            self.SessionLocal = scoped_session(sessionmaker(self.engine, expire_on_commit=False))

    def _create_sync_engine(self) -> Engine:
        if self.use_null_pool:
            return create_engine(
                self.database_url,
                poolclass=NullPool,
                pool_pre_ping=True,
                echo=False,
            )
        return create_engine(
            self.database_url,
            poolclass=QueuePool,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_pre_ping=True,
            pool_recycle=POOL_RECYCLE_SECONDS,
            echo=False,
        )

    def _create_async_engine(self) -> AsyncEngine:
        async_url = self.database_url

        if async_url.startswith("postgresql://"):
            async_url = async_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        pgbouncer_args = _pgbouncer_connect_args()
        extra_args = {"connect_args": pgbouncer_args} if pgbouncer_args else {}

        if self.use_null_pool:
            return create_async_engine(
                async_url,
                poolclass=NullPool,
                pool_pre_ping=True,
                echo=False,
                **extra_args,
            )
        return create_async_engine(
            async_url,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_pre_ping=True,
            pool_recycle=POOL_RECYCLE_SECONDS,
            echo=False,
            **extra_args,
        )

    def create_tables(self):
        if not self.is_async:
            Base.metadata.create_all(bind=self.engine)
        else:
            raise RuntimeError("Use create_tables_async() for async engine")

    async def create_tables_async(self):
        if not self.is_async:
            raise RuntimeError("Use create_tables() for async engine")
        async with self.async_engine.begin() as conn:
            already_managed = await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table("alembic_version"))
            if already_managed:
                logger.info(
                    "Skipping create_all -- schema is Alembic-managed (alembic_version present); "
                    "migrations are the single source of truth"
                )
                return
            await conn.run_sync(Base.metadata.create_all)

    def drop_tables(self):
        if not self.is_async:
            Base.metadata.drop_all(bind=self.engine)
        else:
            raise RuntimeError("Use drop_tables_async() for async engine")

    async def drop_tables_async(self):
        if self.is_async:
            async with self.async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        else:
            raise RuntimeError("Use drop_tables() for sync engine")

    @contextmanager
    def get_session(self, tenant_key: str | None = None) -> Session:
        if self.is_async:
            raise RuntimeError("Use get_session_async() for async operations")

        session = self.SessionLocal()
        effective_tenant_key = tenant_key or TenantManager.get_current_tenant()
        if effective_tenant_key:
            session.info["tenant_key"] = effective_tenant_key
            session.info[TENANT_CONTEXT_SOURCE_KEY] = "service"
        try:
            yield session
            session.commit()
        except (RuntimeError, OSError):
            session.rollback()
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def get_session_async(self, tenant_key: str | None = None) -> AsyncSession:
        if not self.is_async:
            raise RuntimeError("Use get_session() for sync operations")

        session = self.AsyncSessionLocal()
        effective_tenant_key = tenant_key or TenantManager.get_current_tenant()
        if effective_tenant_key:
            session.info["tenant_key"] = effective_tenant_key
            session.info[TENANT_CONTEXT_SOURCE_KEY] = "service"
        try:
            yield session
            await session.commit()
        except GeneratorExit:
            if hasattr(session, "is_active") and session.is_active:
                with suppress(RuntimeError, OSError):
                    await session.rollback()
            raise
        except Exception as _exc:
            try:
                await session.rollback()
            except (SQLAlchemyError, RuntimeError) as rollback_error:
                logger.error(
                    "session_rollback_failed error_code=%s error_message=%s",
                    ErrorCode.DB_TRANSACTION_ROLLBACK.value,
                    str(rollback_error),
                    exc_info=True,
                )
            raise
        finally:
            if hasattr(session, "is_active") and session.is_active:
                with suppress(RuntimeError, OSError):
                    await session.rollback()
            try:
                await session.close()
            except (RuntimeError, OSError, SQLAlchemyError) as close_error:
                logger.debug(f"Session close during cleanup: {close_error}")

    def close(self):
        if not self.is_async:
            self.SessionLocal.remove()
            self.engine.dispose()
        else:
            raise RuntimeError("Use close_async() for async engine")

    async def close_async(self):
        if self.is_async:
            await self.async_engine.dispose()
        else:
            raise RuntimeError("Use close() for sync engine")

    @staticmethod
    def build_postgresql_url(  # nosec B107
        host: str = "localhost",
        port: int = 5432,
        database: str = "giljo_mcp",
        username: str = "postgres",
        password: str = "",
    ) -> str:
        if password:
            password = quote_plus(password)
            return f"postgresql://{username}:{password}@{host}:{port}/{database}"
        return f"postgresql://{username}@{host}:{port}/{database}"

    @asynccontextmanager
    async def get_tenant_session_async(self, tenant_key: str):
        with TenantManager.with_tenant(tenant_key):
            async with self.get_session_async() as session:
                session.info["tenant_key"] = tenant_key
                yield session


class _DatabaseManagerHolder:

    _instance: DatabaseManager | None = None

    @classmethod
    def get_instance(cls, database_url: str | None = None, is_async: bool = False) -> DatabaseManager:
        if cls._instance is None or (database_url and cls._instance.database_url != database_url):
            cls._instance = DatabaseManager(database_url, is_async)
        return cls._instance

    @classmethod
    def set_instance(cls, manager: DatabaseManager):
        cls._instance = manager


def get_db_manager(database_url: str | None = None, is_async: bool = False) -> DatabaseManager:
    return _DatabaseManagerHolder.get_instance(database_url, is_async)


def set_db_manager(manager: DatabaseManager):
    _DatabaseManagerHolder.set_instance(manager)
