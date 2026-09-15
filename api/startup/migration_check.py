# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
from pathlib import Path


logger = logging.getLogger(__name__)


async def check_pending_migrations(state) -> bool:
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine
    except ImportError as exc:
        logger.warning("Alembic not available — skipping migration check: %s", exc)
        return False

    alembic_ini = Path.cwd() / "alembic.ini"
    if not alembic_ini.exists():
        logger.warning("alembic.ini not found at %s — skipping migration check", alembic_ini)
        return False

    if state.db_manager is None:
        logger.warning("db_manager not initialised — skipping migration check")
        return False

    try:
        alembic_cfg = Config(str(alembic_ini))
        giljo_mode = os.environ.get("GILJO_MODE", "ce").lower()
        migrations_dir = Path.cwd() / "migrations"
        version_locations = [str(migrations_dir / "versions")]
        saas_versions_dir = migrations_dir / "saas_versions"
        if saas_versions_dir.is_dir() and giljo_mode == "saas":
            version_locations.append(str(saas_versions_dir))
        alembic_cfg.set_main_option("version_locations", os.pathsep.join(version_locations))

        script = ScriptDirectory.from_config(alembic_cfg)
        heads = set(script.get_heads())
    except Exception as exc:
        logger.warning("Could not read Alembic script directory: %s", exc)
        return False

    if not heads:
        logger.warning("Alembic script directory has no heads — skipping migration check")
        return False

    try:
        raw_url = state.db_manager.database_url
        if not raw_url:
            async_url = str(state.db_manager.async_engine.url)
            raw_url = async_url.replace("+asyncpg", "")

        engine = create_engine(raw_url)
        try:
            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_heads = set(context.get_current_heads())
        finally:
            engine.dispose()
    except Exception as exc:
        logger.warning("Could not connect to database for migration check: %s", exc)
        return False

    missing = heads - current_heads
    if missing:
        logger.warning(
            "Pending migrations detected — missing heads: %s (current: %s, expected: %s)",
            sorted(missing),
            sorted(current_heads),
            sorted(heads),
        )
        return True

    logger.debug("Database is up to date (heads: %s)", sorted(current_heads))
    return False


def get_pending_migration_info(state) -> dict | None:
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine
    except ImportError:
        return None

    alembic_ini = Path.cwd() / "alembic.ini"
    if not alembic_ini.exists() or state.db_manager is None:
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

        script = ScriptDirectory.from_config(alembic_cfg)
        heads = set(script.get_heads())
        if not heads:
            return None

        raw_url = state.db_manager.database_url
        if not raw_url:
            raw_url = str(state.db_manager.async_engine.url).replace("+asyncpg", "")

        engine = create_engine(raw_url)
        try:
            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_heads = set(context.get_current_heads())
        finally:
            engine.dispose()
    except Exception as exc:
        logger.warning("Could not compute pending migration info: %s", exc)
        return None

    missing = heads - current_heads
    if not missing:
        return None
    return {"pending": len(missing), "head": sorted(heads)[-1]}
