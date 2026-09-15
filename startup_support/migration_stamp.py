# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import contextlib
import os

from startup_support.console import print_info, print_success, print_warning


def _check_and_stamp_migration_version() -> None:
    try:
        from sqlalchemy import inspect, text

        from src.giljo_mcp.database import DatabaseManager

        db_url = _get_database_url()
        if not db_url:
            return

        db_manager = DatabaseManager(database_url=db_url, is_async=False)
        with db_manager.get_session() as session:
            if not inspect(session.get_bind()).has_table("alembic_version"):
                _stamp_fresh_database(session)
                return

            result = session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            current = result.scalar()

            if not current or current == "baseline_v37":
                _heal_schema_to_v37(session)
                return

            known_legacy_revisions = {
                "baseline_v33",
                "baseline_v34",
                "baseline_v35",
                "baseline_v36",
                "0855a_setup_state",
                "0904_auto_checkin",
                "0950b_exec_status",
                "0960_checkin_min",
                "0435b_closed_status",
                "0435d_requires_action",
                "bee938301ffa",
            }

            if current in known_legacy_revisions:
                print_info(f"Stamping migration: {current} -> baseline_v37")
                _heal_schema_to_v37(session)
                session.execute(text("UPDATE alembic_version SET version_num = 'baseline_v37'"))
                session.commit()
                print_success("Migration version updated to baseline_v37")
                return

            from pathlib import Path as _Path

            versions_dir = _Path(__file__).parent.parent / "migrations" / "versions"
            known_revisions: set[str] = {"baseline_v37", "baseline_v38"}
            if versions_dir.is_dir():
                for entry in versions_dir.glob("*.py"):
                    if entry.name == "__init__.py":
                        continue
                    known_revisions.add(entry.stem)

            if current in known_revisions:
                return

            print_warning(
                f"Revision {current} is not in this build's migration chain - "
                "treating database as already migrated (newer build?). "
                "NOT stamping down to baseline_v37."
            )

    except Exception as e:
        print_warning(f"Migration version check skipped: {e}")


FRESH_INSTALL_STAMP_REVISION = "ce_0077_sequence_run_reviewed_project_ids"


def _stamp_fresh_database(session) -> None:
    from sqlalchemy import text

    print_info("Fresh database detected - taking the baseline_v38 fast path")
    session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(64) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
    )
    session.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:rev) ON CONFLICT DO NOTHING").bindparams(
            rev=FRESH_INSTALL_STAMP_REVISION
        )
    )
    session.commit()
    print_success(f"Stamped fresh database at {FRESH_INSTALL_STAMP_REVISION} (squash boundary)")


def _heal_schema_to_v37(session) -> None:
    from sqlalchemy import text

    heal_statements = [
        "ALTER TABLE agent_templates ADD COLUMN IF NOT EXISTS user_managed_export BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS org_setup_complete BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE agent_executions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ",
        (
            "CREATE TABLE IF NOT EXISTS product_agent_assignments ("
            "  id VARCHAR(36) PRIMARY KEY,"
            "  product_id VARCHAR(36) NOT NULL REFERENCES products(id) ON DELETE CASCADE,"
            "  template_id VARCHAR(36) NOT NULL REFERENCES agent_templates(id) ON DELETE CASCADE,"
            "  is_active BOOLEAN NOT NULL DEFAULT true,"
            "  tenant_key VARCHAR(36) NOT NULL,"
            "  created_at TIMESTAMPTZ DEFAULT now(),"
            "  updated_at TIMESTAMPTZ"
            ")"
        ),
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_template_assignment ON product_agent_assignments (product_id, template_id)",
        "CREATE INDEX IF NOT EXISTS idx_assignment_tenant ON product_agent_assignments (tenant_key)",
        "CREATE INDEX IF NOT EXISTS idx_assignment_product ON product_agent_assignments (product_id)",
        "CREATE INDEX IF NOT EXISTS idx_assignment_template ON product_agent_assignments (template_id)",
        "CREATE INDEX IF NOT EXISTS idx_assignment_active ON product_agent_assignments (is_active)",
        "DROP TABLE IF EXISTS discovery_config CASCADE",
        "DROP TABLE IF EXISTS git_configs CASCADE",
        "DROP TABLE IF EXISTS optimization_rules CASCADE",
        "DROP TABLE IF EXISTS optimization_metrics CASCADE",
        "ALTER TABLE agent_templates DROP CONSTRAINT IF EXISTS uq_template_product_name_version",
        "DROP INDEX IF EXISTS idx_template_product",
    ]

    heal_statements.append(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_template_tenant_name_version') THEN "
        "ALTER TABLE agent_templates ADD CONSTRAINT uq_template_tenant_name_version UNIQUE (tenant_key, name, version); "
        "END IF; END $$"
    )

    applied = 0
    for stmt in heal_statements:
        try:
            session.execute(text(stmt))
            applied += 1
        except Exception as e:
            print_warning(f"Schema heal skipped: {e}")
    session.commit()
    if applied:
        print_info(f"Schema heal: {applied}/{len(heal_statements)} statements applied")


def _get_database_url() -> str | None:
    with contextlib.suppress(Exception):
        from dotenv import load_dotenv

        load_dotenv()

        database_url = os.getenv("DATABASE_URL")
        if database_url:
            return database_url

        from urllib.parse import quote_plus

        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "giljo_mcp")
        db_user = os.getenv("DB_USER", "postgres")
        db_password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD", "")
        if not db_password:
            return None
        return f"postgresql://{db_user}:{quote_plus(db_password)}@{db_host}:{db_port}/{db_name}"
    return None
