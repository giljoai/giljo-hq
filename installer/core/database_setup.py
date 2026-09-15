# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class DatabaseSetupMixin:

    def detect_postgresql_port(self) -> int:
        from installer.shared.postgres import detect_cluster_port

        configured = int(self.settings.get("pg_port", 5432))

        try:
            detected = detect_cluster_port(current_port=configured)
        except Exception as exc:  # pragma: no cover - defensive
            self._print_warning(f"Could not determine the PostgreSQL cluster port: {exc}")
            return configured

        if detected is None:
            self._print_info(f"Using PostgreSQL port {configured} (cluster port not reported)")
            return configured

        if detected != configured:
            self._print_warning(
                f"PostgreSQL is listening on port {detected}, not {configured} — "
                f"something else is using {configured}. Using {detected} for the "
                "database, .env and config.yaml."
            )
            self.settings["pg_port"] = detected
        else:
            self._print_success(f"PostgreSQL cluster port confirmed: {detected}")

        return detected

    def setup_database(self) -> dict[str, Any]:
        try:
            self._ensure_venv_site_packages()
            from installer.core.database import DatabaseInstaller

            db_settings = {
                "host": self.settings.get("pg_host", "localhost"),
                "port": self.settings.get("pg_port", 5432),
                "password": self.settings.get("pg_password"),
                "username": self.settings.get("pg_user", "postgres"),
                "db_name": self.settings.get("db_name", "giljo_mcp"),
                "headless": self.settings.get("headless", False),
                "unattended": self.settings.get("unattended", False),
            }

            db_installer = DatabaseInstaller(settings=db_settings)

            self._print_info("Creating database and roles...")
            result = db_installer.setup()

            if not result["success"]:
                self._print_error("Database creation failed")
                for error in result.get("errors", []):
                    self._print_error(f"  • {error}")
                return result

            self._print_success("Database and roles created successfully")

            if result.get("roles_reused"):
                env_path = self.install_dir / ".env"
                owner_pw = ""
                user_pw = ""
                if env_path.exists():
                    from dotenv import dotenv_values

                    existing_env = dotenv_values(str(env_path))
                    owner_pw = existing_env.get("POSTGRES_OWNER_PASSWORD", "") or ""
                    user_pw = existing_env.get("POSTGRES_PASSWORD", "") or ""

                env_usable = bool(owner_pw and user_pw)
                repair = bool(self.settings.get("repair"))

                if env_usable:
                    self._print_info(
                        "PostgreSQL roles already exist — reusing credentials from existing .env "
                        "(role passwords left unchanged)."
                    )
                    self.database_credentials = {"owner_password": owner_pw, "user_password": user_pw}

                elif repair:
                    self._print_warning(
                        "PostgreSQL roles exist but .env is missing or incomplete — --repair is "
                        "resetting the giljo_owner/giljo_user passwords and regenerating .env."
                    )
                    reset_result = db_installer.reset_role_passwords()
                    if not reset_result.get("success"):
                        self._print_error("Repair could not reset PostgreSQL role passwords")
                        for error in reset_result.get("errors", []):
                            self._print_error(f"  • {error}")
                        result["success"] = False
                        result["errors"] = reset_result.get("errors", ["role password reset failed"])
                        return result

                    self.database_credentials = reset_result.get("credentials", {})
                    self._print_info("Regenerating .env with reset database credentials...")
                    env_result = self.update_env_with_real_credentials()
                    if not env_result["success"]:
                        self._print_error("Failed to regenerate .env during repair")
                        for error in env_result.get("errors", []):
                            self._print_error(f"  • {error}")
                        result["success"] = False
                        return result
                    self._print_success(".env regenerated with reset database credentials")

                else:
                    self._print_error(
                        "PostgreSQL roles 'giljo_owner'/'giljo_user' already exist on this host but "
                        "no usable .env was found at the install path (missing file, or missing "
                        "POSTGRES_OWNER_PASSWORD / POSTGRES_PASSWORD). This usually means a prior "
                        "install was interrupted. Re-run with 'python install.py --repair' to reset "
                        "these role passwords and rebuild .env, or — for a second co-located install "
                        "— choose a distinct database name (python install.py --db-name giljo_mcp_2)."
                    )
                    result["success"] = False
                    result["errors"] = [
                        "existing roles but no usable .env — re-run with --repair or use a distinct database name"
                    ]
                    return result

            else:
                self.database_credentials = result.get("credentials", {})

                if not self.database_credentials:
                    result["errors"] = ["Database credentials not returned by DatabaseInstaller"]
                    result["success"] = False
                    return result

                self._print_info("Generating .env with real database credentials...")
                env_result = self.update_env_with_real_credentials()

                if not env_result["success"]:
                    self._print_error("Failed to generate .env file")
                    for error in env_result.get("errors", []):
                        self._print_error(f"  • {error}")
                    result["success"] = False
                    return result

                self._print_success(".env file generated with database credentials")

            import os

            from dotenv import load_dotenv

            load_dotenv(override=True)

            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                result["errors"] = ["DATABASE_URL not found in .env after regeneration"]
                result["success"] = False
                return result

            self._print_info(f"Loaded DATABASE_URL from .env: {db_url.split('@')[0]}@...")

            db_name = self.settings.get("db_name", "giljo_mcp")
            self._print_info(f"Verifying database '{db_name}' exists...")
            try:
                import psycopg2

                verify_conn = psycopg2.connect(db_url)
                verify_conn.close()
                self._print_success(f"Database '{db_name}' is reachable")
            except Exception as verify_err:
                self._print_error(f"Database '{db_name}' is not reachable: {verify_err}")
                self._print_error("The database may not have been created. Create it manually:")
                self._print_info(f'  sudo -u postgres psql -c "CREATE DATABASE {db_name} OWNER giljo_owner;"')
                result["success"] = False
                result["errors"] = [f"Database '{db_name}' does not exist or is not reachable"]
                return result

            self._print_info("Running database migrations to create schema...")
            migration_result = self.run_database_migrations()

            if not migration_result["success"]:
                self._print_error("Database migration failed")
                for error in migration_result.get("errors", []):
                    self._print_error(f"  • {error}")
                result["success"] = False
                result["migration_error"] = migration_result.get("error", "Unknown error")
                return result

            self._print_success("Database schema created via Alembic migrations")

            result["migrations_applied"] = migration_result.get("migrations_applied", [])

            self._print_info("Creating setup state...")
            import asyncio

            effective_tenant_key = self._seed_setup_state(db_url)

            if effective_tenant_key:
                self.default_tenant_key = effective_tenant_key
                self._print_success("Setup state initialized")
                result["setup_state_created"] = True
                result["admin_created"] = False
            else:
                self._print_error("Setup state creation failed")
                result["success"] = False
                return result

            self._print_info("Seeding demo data for agent succession...")
            try:
                demo_seeded = asyncio.run(self._seed_agent_job_demo_data(effective_tenant_key))
                if demo_seeded:
                    self._print_success("Demo data seeded successfully")
                else:
                    self._print_info("Demo data seeding skipped (already exists)")
            except Exception as e:
                self._print_warning(f"Failed to seed demo data: {e}")

            return result

        except Exception as e:
            import traceback

            self._print_error(f"Database setup failed: {e}")
            traceback.print_exc()
            return {"success": False, "errors": [str(e)]}

    def _seed_setup_state(self, db_url: str) -> str | None:
        import asyncio
        from datetime import UTC, datetime  # noqa: PLC0415 — UTC MUST be imported here (BE-9060 split dropped it)
        from uuid import uuid4

        from sqlalchemy import select, text

        from giljo_mcp.database import DatabaseManager, tenant_session_context
        from giljo_mcp.models import SetupState
        from giljo_mcp.tenant import TenantManager

        async def _run() -> str | None:
            db_manager = DatabaseManager(db_url, is_async=True)
            try:
                async with db_manager.get_session_async() as session:
                    existing_tk = None
                    try:
                        pre = await session.execute(
                            text("SELECT tenant_key FROM setup_state ORDER BY created_at LIMIT 1")
                        )
                        existing_tk = pre.scalar()
                    except Exception:
                        existing_tk = None

                    tenant_key = existing_tk or TenantManager.generate_tenant_key("default_installation")

                    with tenant_session_context(session, tenant_key):
                        stmt = select(SetupState).where(SetupState.tenant_key == tenant_key)
                        existing_state = (await session.execute(stmt)).scalar_one_or_none()

                        if not existing_state:
                            now = datetime.now(UTC)
                            session.add(
                                SetupState(
                                    id=str(uuid4()),
                                    tenant_key=tenant_key,
                                    database_initialized=True,
                                    database_initialized_at=now,
                                    setup_version="3.1.0",
                                    created_at=now,
                                    updated_at=now,
                                )
                            )
                            await session.commit()

                return tenant_key
            finally:
                await db_manager.close_async()

        try:
            return asyncio.run(_run())
        except Exception as e:
            self._print_warning(f"Setup state seeding error: {e}")
            return None

    async def _seed_agent_job_demo_data(self, tenant_key: str = "default") -> bool:
        try:
            import os
            from datetime import UTC, datetime, timedelta
            from uuid import uuid4

            from dotenv import load_dotenv
            from sqlalchemy import select

            from giljo_mcp.database import DatabaseManager, tenant_session_context
            from giljo_mcp.models.agent_identity import AgentExecution, AgentJob

            load_dotenv(override=True)
            db_url = os.getenv("DATABASE_URL")

            if not db_url:
                self._print_warning("DATABASE_URL not found - skipping demo data seeding")
                return False

            db_manager = DatabaseManager(db_url, is_async=True)

            async with db_manager.get_session_async() as session:
                with tenant_session_context(session, tenant_key):
                    stmt = select(AgentJob).where(
                        AgentJob.tenant_key == tenant_key,
                        AgentJob.mission.contains("Demo: Orchestrator with Succession"),
                    )
                    result = await session.execute(stmt)
                    existing_job = result.scalar_one_or_none()

                    if existing_job:
                        self._print_info("Demo data already exists - skipping seed")
                        return True

                    job_id = str(uuid4())
                    demo_job = AgentJob(
                        job_id=job_id,
                        tenant_key=tenant_key,
                        project_id=None,
                        mission="Demo: Orchestrator with Succession - This is a sample job showing how orchestrator succession works when context limits are approached.",
                        job_type="orchestrator",
                        status="active",
                        created_at=datetime.now(UTC) - timedelta(hours=2),
                        job_metadata={
                            "demo": True,
                            "description": "Demonstrates succession workflow",
                        },
                    )
                    session.add(demo_job)

                    first_agent_id = str(uuid4())
                    orchestrator_execution = AgentExecution(
                        agent_id=first_agent_id,
                        job_id=job_id,
                        tenant_key=tenant_key,
                        agent_display_name="orchestrator",
                        status="working",
                        started_at=datetime.now(UTC) - timedelta(hours=1),
                        completed_at=None,
                        progress=35,
                        current_task="Monitoring implementation agents and coordinating integration testing",
                        health_status="healthy",
                        last_progress_at=datetime.now(UTC),
                        agent_name="Orchestrator",
                    )
                    session.add(orchestrator_execution)

                    await session.commit()

            await db_manager.close_async()
            return True

        except Exception as e:
            self._print_warning(f"Failed to seed demo data: {e}")
            import traceback

            traceback.print_exc()
            return False

    def check_custom_postgresql_path(self, path_str: str) -> bool:
        try:
            path_str = path_str.strip().strip('"').strip("'")
            path = Path(path_str).resolve()

            if not path.exists():
                self._print_error(f"Path does not exist: {path}")
                parent = path.parent
                if parent.exists():
                    self._print_info(f"Parent directory exists: {parent}")
                    self._print_info("Did you mean to include the 'bin' subdirectory?")
                return False

            if not path.is_dir():
                self._print_error(f"Path is not a directory: {path}")
                return False

            if self.platform.platform_name == "Windows":
                psql_path = path / "psql.exe"
            else:
                psql_path = path / "psql"

            if not psql_path.exists():
                self._print_error(f"psql executable not found in: {path}")
                psql_no_ext = path / "psql"
                if psql_no_ext.exists() and self.platform.platform_name == "Windows":
                    self._print_info("Found 'psql' without .exe extension - this may not work on Windows")
                if path.name == "psql.exe" and path.exists():
                    self._print_info("You provided the path to psql.exe directly")
                    self._print_info(f"Please provide the bin directory instead: {path.parent}")
                return False

            self._print_success(f"Valid PostgreSQL installation found: {psql_path}")
            return True

        except Exception as e:
            self._print_error(f"Invalid path: {e}")
            return False

    def _get_postgresql_scan_paths(self) -> list[Path]:
        return self.platform.get_postgresql_scan_paths()

    def run_database_migrations(self) -> dict[str, Any]:
        result = {"success": False, "migrations_applied": []}

        try:
            cwd = Path.cwd()

            alembic_ini = cwd / "alembic.ini"
            if not alembic_ini.exists():
                self._print_error(f"alembic.ini not found at {alembic_ini}")
                result["error"] = "Alembic configuration file missing"
                return result

            migrations_dir = cwd / "migrations"
            if not migrations_dir.exists():
                self._print_error(f"Migrations directory not found at {migrations_dir}")
                result["error"] = "Migrations directory missing"
                return result

            try:
                import greenlet  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "greenlet is required for alembic async migrations but is not installed. "
                    "This typically means a fresh venv is missing transitive deps on this platform "
                    "(macOS arm64 is a common case). Add 'greenlet>=3.5.0' to requirements.txt and reinstall."
                ) from exc

            import asyncio
            import os

            async def check_and_stamp_base():
                try:
                    from sqlalchemy import text

                    from giljo_mcp.database import DatabaseManager

                    db_url = os.getenv("DATABASE_URL")
                    if not db_url:
                        return False

                    db_manager = DatabaseManager(db_url, is_async=True)

                    async with db_manager.get_session_async() as session:
                        check_query = text("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables
                                WHERE table_name = 'alembic_version'
                            )
                        """)
                        result_check = await session.execute(check_query)
                        table_exists = result_check.scalar()

                        if not table_exists:
                            self._print_info("Fresh install detected - taking the baseline_v38 fast path")
                            await session.execute(
                                text(
                                    "CREATE TABLE IF NOT EXISTS alembic_version ("
                                    "version_num VARCHAR(64) NOT NULL, "
                                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                                )
                            )
                            await session.execute(
                                text(
                                    "INSERT INTO alembic_version (version_num) VALUES (:rev) ON CONFLICT DO NOTHING"
                                ).bindparams(rev="ce_0077_sequence_run_reviewed_project_ids")
                            )
                            await session.commit()
                            self._print_success(
                                "Stamped fresh database at the squash boundary - "
                                "baseline_v38 will build the schema in one step"
                            )
                            await db_manager.close_async()
                            return True

                        version_query = text("SELECT version_num FROM alembic_version LIMIT 1")
                        result_version = await session.execute(version_query)
                        current_version = result_version.scalar()

                        known_old_revisions = {
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

                        if current_version and current_version in known_old_revisions:
                            self._print_info(f"Upgrading migration chain: {current_version} -> baseline_v37")
                            self._print_info("Reconciling schema for baseline_v37...")

                            reconcile_statements = [
                                "ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_preferences JSONB",
                                "ALTER TABLE products ADD COLUMN IF NOT EXISTS tuning_state JSONB",
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS project_type_id VARCHAR(36)",
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS series_number INTEGER",
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS subseries VARCHAR(1)",
                                "ALTER TABLE agent_jobs ADD COLUMN IF NOT EXISTS phase INTEGER",
                                "ALTER TABLE agent_executions ADD COLUMN IF NOT EXISTS result JSON",
                                "ALTER TABLE agent_executions ADD COLUMN IF NOT EXISTS accumulated_duration_seconds FLOAT DEFAULT 0.0",
                                "ALTER TABLE agent_executions ADD COLUMN IF NOT EXISTS reactivation_count INTEGER DEFAULT 0",
                                "ALTER TABLE mcp_sessions ALTER COLUMN api_key_id DROP NOT NULL",
                                "ALTER TABLE users ADD COLUMN IF NOT EXISTS setup_complete BOOLEAN NOT NULL DEFAULT false",
                                "ALTER TABLE users ADD COLUMN IF NOT EXISTS setup_selected_tools JSONB",
                                "ALTER TABLE users ADD COLUMN IF NOT EXISTS setup_step_completed INTEGER NOT NULL DEFAULT 0",
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS auto_checkin_enabled BOOLEAN NOT NULL DEFAULT false",
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS auto_checkin_interval INTEGER NOT NULL DEFAULT 10",
                                "ALTER TABLE messages ADD COLUMN IF NOT EXISTS requires_action BOOLEAN NOT NULL DEFAULT false",
                            ]

                            for stmt_text in reconcile_statements:
                                try:
                                    await session.execute(text(stmt_text))
                                except Exception as reconcile_err:
                                    self._print_warning(f"Reconcile skipped: {reconcile_err}")

                            stamp_query = text("UPDATE alembic_version SET version_num = 'baseline_v37'")
                            await session.execute(stamp_query)
                            await session.commit()
                            self._print_success("Schema reconciled and stamped to baseline_v37")
                            await db_manager.close_async()
                            return True

                        if current_version and current_version not in known_old_revisions:
                            versions_dir = migrations_dir / "versions"
                            known_modern_revisions: set[str] = {"baseline_v37", "baseline_v38"}
                            if versions_dir.is_dir():
                                for entry in versions_dir.glob("*.py"):
                                    if entry.name == "__init__.py":
                                        continue
                                    known_modern_revisions.add(entry.stem)

                            if current_version in known_modern_revisions:
                                self._print_info(
                                    f"Database already at {current_version} - alembic will advance to head"
                                )
                            else:
                                self._print_warning(
                                    f"Revision {current_version} is not in this build's migration "
                                    "chain - treating database as already migrated (newer build?). "
                                    "NOT stamping down to baseline_v37."
                                )
                            await db_manager.close_async()
                            return True

                        if not current_version:
                            self._print_info("Empty alembic_version table - will run migrations")

                        await db_manager.close_async()
                        return True

                except Exception as e:
                    self._print_warning(f"Could not check alembic version: {e}")
                    return True

            asyncio.run(check_and_stamp_base())

            self._print_info("Running database migrations (alembic upgrade head)...")

            venv_python = self.platform.get_venv_python(self.venv_dir)
            proc = subprocess.run(
                [str(venv_python), "-m", "alembic", "upgrade", "head"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(cwd),
                check=False,
            )

            if proc.returncode == 0:
                self._print_success("Database migrations completed successfully")
                result["success"] = True
                result["output"] = proc.stdout

                for line in proc.stdout.split("\n"):
                    if "Running upgrade" in line:
                        result["migrations_applied"].append(line.strip())

                if result["migrations_applied"]:
                    self._print_info(f"Applied {len(result['migrations_applied'])} migration(s)")
                    for migration in result["migrations_applied"]:
                        self._print_info(f"  {migration}")
                else:
                    self._print_info("No new migrations to apply (database already up to date)")

                self._print_info("Verifying database schema...")
                verification_result = asyncio.run(self._verify_essential_tables())

                if not verification_result["success"]:
                    self._print_error("Schema verification failed!")
                    self._print_error("Migrations ran but essential tables are missing.")
                    for missing in verification_result.get("missing_tables", []):
                        self._print_error(f"  Missing: {missing}")
                    self._print_error("")
                    self._print_error("This usually means:")
                    self._print_error("  1. migrations/versions/ folder is empty")
                    self._print_error("  2. Migration files are corrupted or orphaned")
                    self._print_error("")
                    self._print_error("Solution: Ensure baseline migration exists in migrations/versions/")
                    result["success"] = False
                    result["error"] = f"Missing tables: {', '.join(verification_result.get('missing_tables', []))}"
                    return result

                self._print_success(f"Schema verified: {verification_result['tables_found']} essential tables present")
            else:
                self._print_error("Database migration failed")
                self._print_error(f"STDOUT: {proc.stdout}")
                self._print_error(f"STDERR: {proc.stderr}")
                result["error"] = f"Migration failed: {proc.stderr}"
                result["output"] = proc.stdout
                result["stderr"] = proc.stderr

        except subprocess.TimeoutExpired:
            self._print_error("Database migration timed out after 120 seconds")
            result["error"] = "Migration timeout"
        except Exception as e:
            self._print_error(f"Database migration error: {e}")
            import traceback

            traceback.print_exc()
            result["error"] = str(e)

        return result

    def _set_postgres_password_via_peer(self, password: str) -> bool:
        escaped = password.replace("'", "''")
        safe_sql = f"ALTER USER postgres PASSWORD '{escaped}';"

        system = platform.system()
        try:
            if system == "Darwin":
                cmd = ["psql", "-U", "postgres", "-d", "postgres", "-c", safe_sql]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
            else:
                cmd = ["sudo", "-u", "postgres", "psql", "-c", safe_sql]
                self._print_info("Setting PostgreSQL password (sudo may ask for your password)...")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)

            if result.returncode == 0:
                return True

            self._print_warning(f"Peer auth password set failed: {result.stderr.strip()}")
            return False

        except subprocess.TimeoutExpired:
            self._print_warning("Password set timed out")
            return False
        except FileNotFoundError:
            self._print_warning("psql not found in PATH")
            return False
        except Exception as e:
            self._print_warning(f"Peer auth password set failed: {e}")
            return False
