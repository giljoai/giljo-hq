# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from giljo_mcp.models import Base


config = context.config



load_dotenv()

db_url = os.getenv("DATABASE_URL")
if not db_url:
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "giljo_mcp")
    db_user = os.getenv("POSTGRES_USER", "giljo_user")
    db_pass = os.getenv("POSTGRES_PASSWORD")

    if db_pass:
        db_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    else:
        raise ValueError(
            "PostgreSQL connection not configured!\n\n"
            "The installer should have created .env with POSTGRES_PASSWORD.\n"
            "If running migrations manually, ensure .env exists with:\n"
            "  POSTGRES_PASSWORD=<your_password>\n\n"
            "Note: PostgreSQL 18+ is required."
        )

config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

giljo_mode = os.environ.get("GILJO_MODE", "ce").lower()
migrations_dir = Path(__file__).parent

version_locations = [str(migrations_dir / "versions")]

saas_versions_dir = migrations_dir / "saas_versions"
if saas_versions_dir.is_dir() and giljo_mode == "saas":
    version_locations.append(str(saas_versions_dir))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_locations=version_locations,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_locations=version_locations,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
