# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError


logger = logging.getLogger(__name__)

UNKNOWN: dict = {"unknown": True}


def _missing_heads(state) -> tuple[set[str], set[str]] | None:
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from alembic.util.exc import CommandError
        from sqlalchemy import create_engine
    except ImportError:
        logger.warning("Alembic not available; migration status unknown", exc_info=True)
        return None

    alembic_ini = Path.cwd() / "alembic.ini"
    if not alembic_ini.exists():
        logger.warning("alembic.ini not found at %s; migration status unknown", alembic_ini)
        return None
    if state.db_manager is None:
        logger.warning("db_manager not initialised; migration status unknown")
        return None

    try:
        alembic_cfg = Config(str(alembic_ini))
        giljo_mode = os.environ.get("GILJO_MODE", "ce").lower()
        migrations_dir = Path.cwd() / "migrations"
        version_locations = [str(migrations_dir / "versions")]
        saas_versions_dir = migrations_dir / "saas_versions"
        if saas_versions_dir.is_dir() and giljo_mode == "saas":
            version_locations.append(str(saas_versions_dir))
        alembic_cfg.set_main_option("version_locations", os.pathsep.join(version_locations))
        heads = set(ScriptDirectory.from_config(alembic_cfg).get_heads())
        if not heads:
            logger.warning("Alembic script directory has no heads; migration status unknown")
            return None

        raw_url = state.db_manager.database_url
        if not raw_url:
            raw_url = str(state.db_manager.async_engine.url).replace("+asyncpg", "")
        engine = create_engine(raw_url)
        try:
            with engine.connect() as conn:
                current_heads = set(MigrationContext.configure(conn).get_current_heads())
        finally:
            engine.dispose()
    except (OSError, ValueError, KeyError, SQLAlchemyError, CommandError):
        logger.warning("Could not check migration status; migration status unknown", exc_info=True)
        return None

    return heads - current_heads, heads


async def check_pending_migrations(state) -> bool | None:
    result = _missing_heads(state)
    if result is None:
        return None
    missing, heads = result
    if missing:
        logger.warning(
            "Pending migrations detected: missing heads %s (current: %s, expected: %s)",
            sorted(missing),
            sorted(heads - missing),
            sorted(heads),
        )
        return True
    logger.debug("Database is up to date (heads: %s)", sorted(heads))
    return False


def get_pending_migration_info(state) -> dict | None:
    result = _missing_heads(state)
    if result is None:
        return UNKNOWN
    missing, heads = result
    if not missing:
        return None
    return {"pending": len(missing), "head": sorted(heads)[-1]}
