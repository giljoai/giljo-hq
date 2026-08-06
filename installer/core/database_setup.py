# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Database setup / migration phase of the CE installer (BE-9060 split).

Methods moved VERBATIM out of install.py's UnifiedInstaller. This class is a
mixin: it is only ever instantiated as part of UnifiedInstaller and relies on
attributes (settings, platform, install_dir, venv_dir) and the self._print_*
helpers the main class defines.
"""

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class DatabaseSetupMixin:
    """PostgreSQL path validation, database creation, and migration execution."""

    def detect_postgresql_port(self) -> int:
        """Point settings['pg_port'] at the port the cluster is really on.

        Everything downstream -- the DatabaseInstaller connection, config.yaml,
        .env's DATABASE_URL, the saved credentials file and the generated
        create_db script -- reads this one setting, so correcting it here
        corrects all of them. Before INF-9321 it was a hardcoded 5432, and an
        install whose cluster landed on 5433 (because something else already
        held 5432) aimed every one of those at a server that was not ours.

        Best-effort by design: when nothing can be determined the configured
        port stands, which is exactly the old behaviour.

        Returns:
            The port now in settings['pg_port'].
        """
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
        """
        Setup PostgreSQL database using Alembic-first strategy (v3.1.0+)

        PRODUCTION-GRADE APPROACH:
        All schema changes MUST go through Alembic migrations.
        NO direct create_all() calls - this ensures:
        - Version control for schema changes
        - Rollback safety
        - Upgrade path for existing installations
        - Consistent schema across environments

        Sequence:
        1. Create database and roles (DatabaseInstaller)
        2. Update .env with REAL credentials
        3. Reload environment variables
        4. Run Alembic migrations to create schema (REPLACES create_all())
        5. Seed initial data (SetupState ONLY - no admin user per Handover 0034)

        Returns:
            Database setup result with migrations_applied list
        """
        try:
            # Ensure venv site-packages are available before imports
            self._ensure_venv_site_packages()
            from installer.core.database import DatabaseInstaller

            # Prepare settings for DatabaseInstaller
            # Keys must match DatabaseInstaller.__init__ expectations
            db_settings = {
                "host": self.settings.get("pg_host", "localhost"),
                "port": self.settings.get("pg_port", 5432),
                "password": self.settings.get("pg_password"),
                "username": self.settings.get("pg_user", "postgres"),
                "db_name": self.settings.get("db_name", "giljo_mcp"),
                # Propagate headless/unattended so fallback_setup() never hangs
                # on input() during automated or second-instance installs. (INF-6260)
                "headless": self.settings.get("headless", False),
                "unattended": self.settings.get("unattended", False),
            }

            db_installer = DatabaseInstaller(settings=db_settings)

            # STEP 1: Create database and roles
            self._print_info("Creating database and roles...")
            result = db_installer.setup()

            if not result["success"]:
                self._print_error("Database creation failed")
                for error in result.get("errors", []):
                    self._print_error(f"  • {error}")
                return result

            self._print_success("Database and roles created successfully")

            # STEP 1.5: Handle co-located / idempotent reinstall.
            # When giljo_owner/giljo_user already existed, create_database_direct()
            # left their passwords untouched (INF-6260: ALTER ROLE PASSWORD on a
            # shared role would silently break any co-located live installation).
            # We must NOT overwrite .env with freshly-generated (wrong) passwords.
            # Instead, reload the correct credentials from the existing .env so the
            # rest of setup_database() can proceed unchanged.
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
                    # Normal reuse path: the roles exist and .env holds their credentials.
                    # NEVER reset a shared role's password (co-located-safe, INF-6260) —
                    # reload the correct credentials from the existing .env instead.
                    self._print_info(
                        "PostgreSQL roles already exist — reusing credentials from existing .env "
                        "(role passwords left unchanged)."
                    )
                    self.database_credentials = {"owner_password": owner_pw, "user_password": user_pw}
                    # Skip STEP 2 and STEP 3 — .env already has the correct passwords.

                elif repair:
                    # Re-entrancy recovery (INF-5089, --repair): the roles exist but their
                    # passwords are unrecoverable (a prior run created them with fresh random
                    # passwords, then died before writing a usable .env). --repair is an
                    # explicit operator action to fix THIS install, so we may reset the role
                    # passwords to new random values and regenerate .env from them.
                    # (Do NOT use --repair if another co-located install shares these roles.)
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
                    # Roles exist, their passwords are unrecoverable, and --repair was not
                    # requested. Fail fast with an actionable recovery path.
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
                # STEP 2: Store real credentials (fresh install path).
                self.database_credentials = result.get("credentials", {})

                if not self.database_credentials:
                    result["errors"] = ["Database credentials not returned by DatabaseInstaller"]
                    result["success"] = False
                    return result

                # STEP 3: Update .env with REAL database credentials
                self._print_info("Generating .env with real database credentials...")
                env_result = self.update_env_with_real_credentials()

                if not env_result["success"]:
                    self._print_error("Failed to generate .env file")
                    for error in env_result.get("errors", []):
                        self._print_error(f"  • {error}")
                    result["success"] = False
                    return result

                self._print_success(".env file generated with database credentials")

            # STEP 4: Reload environment variables
            import os

            from dotenv import load_dotenv

            load_dotenv(override=True)  # Force reload to pick up new DATABASE_URL

            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                result["errors"] = ["DATABASE_URL not found in .env after regeneration"]
                result["success"] = False
                return result

            self._print_info(f"Loaded DATABASE_URL from .env: {db_url.split('@')[0]}@...")

            # STEP 5: Verify database exists before running migrations
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

            # STEP 6: Run Alembic migrations to create schema
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

            # Store migration results in main result
            result["migrations_applied"] = migration_result.get("migrations_applied", [])

            # STEP 6: Seed initial data (SetupState ONLY - no admin user per Handover 0034)
            self._print_info("Creating setup state...")
            import asyncio

            effective_tenant_key = self._seed_setup_state(db_url)

            if effective_tenant_key:
                # Store tenant key on the instance for .env generation / demo seeding.
                self.default_tenant_key = effective_tenant_key
                self._print_success("Setup state initialized")
                result["setup_state_created"] = True
                result["admin_created"] = False  # Explicitly mark as not created (Handover 0034)
            else:
                self._print_error("Setup state creation failed")
                result["success"] = False
                return result

            # STEP 6.5: Seed demo AgentJob and AgentExecution data (Handover 0366d-4)
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
        """Idempotently seed the SetupState bootstrap row; return the effective tenant_key.

        Re-entrancy (INF-5089): a prior — possibly interrupted — install may have already
        written a setup_state row under a randomly-generated tenant_key. Minting a *fresh*
        random key on every run would make the ORM existence check never match, so each
        re-run would insert another SetupState row (and re-seed demo data) — silent
        duplicate work. Instead, reuse any tenant_key already present in setup_state so a
        re-run is a no-op. On a genuinely fresh database, generate a new key and insert.

        Returns the effective tenant_key (truthy) on success, or None on failure.
        """
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
                    # Idempotency pre-check (raw SQL — no tenant context needed): reuse an
                    # existing bootstrap tenant_key instead of minting a new one each run.
                    existing_tk = None
                    try:
                        pre = await session.execute(
                            text("SELECT tenant_key FROM setup_state ORDER BY created_at LIMIT 1")
                        )
                        existing_tk = pre.scalar()
                    except Exception:
                        # Table may not exist yet on a truly fresh DB — fall through to generate.
                        existing_tk = None

                    tenant_key = existing_tk or TenantManager.generate_tenant_key("default_installation")

                    # The tenant-isolation guard (enforce mode) requires an active tenant
                    # CONTEXT for any ORM statement touching SetupState — an explicit
                    # tenant_key predicate is deliberately not accepted. Set the context here.
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
                                    setup_version="3.1.0",  # Alembic-first architecture
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
        """
        Seed sample AgentJob and AgentExecution records to demonstrate succession.

        Creates a demo orchestrator job with two executions showing succession chain:
        - First execution: completed at 85% context usage (triggered succession)
        - Second execution: active, continuing work from predecessor

        Args:
            tenant_key: Tenant key for multi-tenant isolation

        Returns:
            bool - True if seeding succeeded, False otherwise

        Note:
            Idempotent - checks for existing demo data before inserting.
        """
        try:
            # Get database URL from environment
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
                # Enforce-mode tenant isolation requires an active tenant CONTEXT for any
                # ORM write to AgentJob/AgentExecution; a tenant_key predicate is not
                # accepted. Set it for the fresh-install bootstrap seed. (INF-6037)
                with tenant_session_context(session, tenant_key):
                    # Check if demo data already exists (idempotent)
                    stmt = select(AgentJob).where(
                        AgentJob.tenant_key == tenant_key,
                        AgentJob.mission.contains("Demo: Orchestrator with Succession"),
                    )
                    result = await session.execute(stmt)
                    existing_job = result.scalar_one_or_none()

                    if existing_job:
                        self._print_info("Demo data already exists - skipping seed")
                        return True

                    # Create demo AgentJob
                    job_id = str(uuid4())
                    demo_job = AgentJob(
                        job_id=job_id,
                        tenant_key=tenant_key,
                        project_id=None,  # Not associated with a project
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

                    # Create orchestrator execution (active)
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
        """
        Check if custom PostgreSQL path is valid

        Validates:
        1. Path exists
        2. Contains psql or psql.exe executable

        Args:
            path_str: Path to PostgreSQL bin directory

        Returns:
            True if path is valid, False otherwise
        """
        try:
            # Normalize path (handle backslashes, forward slashes, quotes, etc.)
            path_str = path_str.strip().strip('"').strip("'")
            path = Path(path_str).resolve()

            # Check if directory exists
            if not path.exists():
                self._print_error(f"Path does not exist: {path}")
                # Try to be helpful
                parent = path.parent
                if parent.exists():
                    self._print_info(f"Parent directory exists: {parent}")
                    self._print_info("Did you mean to include the 'bin' subdirectory?")
                return False

            # Check if it's a directory
            if not path.is_dir():
                self._print_error(f"Path is not a directory: {path}")
                return False

            # Check for psql executable (platform-specific)
            # Windows uses .exe extension, Linux/macOS don't
            if self.platform.platform_name == "Windows":
                psql_path = path / "psql.exe"
            else:
                psql_path = path / "psql"

            if not psql_path.exists():
                self._print_error(f"psql executable not found in: {path}")
                # Try to be helpful - check if psql exists without extension
                psql_no_ext = path / "psql"
                if psql_no_ext.exists() and self.platform.platform_name == "Windows":
                    self._print_info("Found 'psql' without .exe extension - this may not work on Windows")
                # Check if user provided the full path to psql.exe instead of bin directory
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
        """
        Get platform-specific PostgreSQL scan paths

        Delegates to platform handler to eliminate hardcoded OS-specific paths.

        Returns:
            List of paths to check for psql
        """
        return self.platform.get_postgresql_scan_paths()

    def run_database_migrations(self) -> dict[str, Any]:
        """
        Run Alembic database migrations (alembic upgrade head)

        PRODUCTION-GRADE APPROACH (v3.1.0+):
        This is the PRIMARY method for schema creation and updates.
        All schema changes MUST go through Alembic migrations.

        Handles both:
        - Fresh installs (no existing alembic_version table) - runs all migrations
        - Upgrades (existing alembic_version table) - runs only pending migrations

        Returns:
            Result dictionary with success status and details
        """
        result = {"success": False, "migrations_applied": []}

        try:
            # Ensure we're in the install directory
            cwd = Path.cwd()

            # Check if alembic.ini exists
            alembic_ini = cwd / "alembic.ini"
            if not alembic_ini.exists():
                self._print_error(f"alembic.ini not found at {alembic_ini}")
                result["error"] = "Alembic configuration file missing"
                return result

            # Check if migrations directory exists
            migrations_dir = cwd / "migrations"
            if not migrations_dir.exists():
                self._print_error(f"Migrations directory not found at {migrations_dir}")
                result["error"] = "Migrations directory missing"
                return result

            # Fail fast if greenlet is missing (required by SQLAlchemy async engine;
            # missing on macOS arm64 when only pulled transitively — alembic silently
            # no-ops DDL without it, causing schema verification to fail later).
            try:
                import greenlet  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "greenlet is required for alembic async migrations but is not installed. "
                    "This typically means a fresh venv is missing transitive deps on this platform "
                    "(macOS arm64 is a common case). Add 'greenlet>=3.5.0' to requirements.txt and reinstall."
                ) from exc

            # Check database state before running migrations
            import asyncio
            import os

            async def check_and_stamp_base():
                """Check alembic_version and handle fresh vs upgrade installs.

                For upgrades from pre-v33 databases: the schema is already correct
                (all incremental migrations ran), so we stamp to baseline_v37 to
                align with the consolidated migration chain.
                """
                try:
                    from sqlalchemy import text

                    from giljo_mcp.database import DatabaseManager

                    db_url = os.getenv("DATABASE_URL")
                    if not db_url:
                        return False

                    db_manager = DatabaseManager(db_url, is_async=True)

                    async with db_manager.get_session_async() as session:
                        # Check if alembic_version table exists
                        check_query = text("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables
                                WHERE table_name = 'alembic_version'
                            )
                        """)
                        result_check = await session.execute(check_query)
                        table_exists = result_check.scalar()

                        if not table_exists:
                            # Fresh database (INF-5060 fast path): create the version
                            # table at VARCHAR(64) (ce_0003 width fix -- alembic's
                            # default 32 chars truncates long revision IDs) and stamp
                            # the squash boundary, so `alembic upgrade head` executes
                            # ONLY the guarded baseline_v38 instead of replaying the
                            # full incremental chain. Keep the revision in sync with
                            # FRESH_INSTALL_STAMP_REVISION in
                            # startup_support/migration_stamp.py and with
                            # baseline_v38_unified.py's down_revision.
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

                        # Check current version
                        version_query = text("SELECT version_num FROM alembic_version LIMIT 1")
                        result_version = await session.execute(version_query)
                        current_version = result_version.scalar()

                        # Known old revisions that need stamping to baseline_v37
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
                            # Existing database from a previous baseline.
                            # Reconcile schema: add any columns that may be missing.
                            self._print_info(f"Upgrading migration chain: {current_version} -> baseline_v37")
                            self._print_info("Reconciling schema for baseline_v37...")

                            reconcile_statements = [
                                # Handover 0831: Product context tuning
                                "ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_preferences JSONB",
                                "ALTER TABLE products ADD COLUMN IF NOT EXISTS tuning_state JSONB",
                                # Handover 0440a: Project taxonomy
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS project_type_id VARCHAR(36)",
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS series_number INTEGER",
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS subseries VARCHAR(1)",
                                # Handover 0411a: Agent job phases
                                "ALTER TABLE agent_jobs ADD COLUMN IF NOT EXISTS phase INTEGER",
                                # Handover 0497b: Agent execution result
                                "ALTER TABLE agent_executions ADD COLUMN IF NOT EXISTS result JSON",
                                # Handover 0827c: Reactivation tracking
                                "ALTER TABLE agent_executions ADD COLUMN IF NOT EXISTS accumulated_duration_seconds FLOAT DEFAULT 0.0",
                                "ALTER TABLE agent_executions ADD COLUMN IF NOT EXISTS reactivation_count INTEGER DEFAULT 0",
                                # Handover 0828: OAuth JWT sessions (nullable api_key_id)
                                "ALTER TABLE mcp_sessions ALTER COLUMN api_key_id DROP NOT NULL",
                                # Handover 0855a: User setup wizard state
                                "ALTER TABLE users ADD COLUMN IF NOT EXISTS setup_complete BOOLEAN NOT NULL DEFAULT false",
                                "ALTER TABLE users ADD COLUMN IF NOT EXISTS setup_selected_tools JSONB",
                                "ALTER TABLE users ADD COLUMN IF NOT EXISTS setup_step_completed INTEGER NOT NULL DEFAULT 0",
                                # Handover 0904: Orchestrator auto check-in
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS auto_checkin_enabled BOOLEAN NOT NULL DEFAULT false",
                                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS auto_checkin_interval INTEGER NOT NULL DEFAULT 10",
                                # Handover 0435d: Message requires_action flag
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
                            # Any revision outside the explicit legacy list above is
                            # treated as already-migrated. Recognized revisions
                            # (baseline_v37, ce_0001..ce_XXXX) advance via `alembic
                            # upgrade head`; an unrecognized one means the DB was
                            # written by a DIFFERENT (likely newer) build. Stamping it
                            # down to baseline_v37 would replay the whole chain over an
                            # already-migrated schema and wedge the install (INF-9113:
                            # a `__file__`-relative scan here resolved to a non-existent
                            # dir, misclassified every ce_0XXX as unknown, and
                            # destructively stamped fresh at-head DBs). Never stamp
                            # down; `alembic upgrade head` fails loudly if it cannot
                            # locate the revision.
                            versions_dir = migrations_dir / "versions"
                            # Baseline revision IDs differ from their file stems
                            # (baseline_v38_unified.py -> revision "baseline_v38"),
                            # so seed them explicitly; ce_0XXX stems ARE the IDs.
                            known_modern_revisions: set[str] = {"baseline_v37", "baseline_v38"}
                            if versions_dir.is_dir():
                                for entry in versions_dir.glob("*.py"):
                                    if entry.name == "__init__.py":
                                        continue
                                    # Alembic revision filenames are <rev_id>_<slug>.py;
                                    # the full revision ID is the file stem.
                                    known_modern_revisions.add(entry.stem)

                            if current_version in known_modern_revisions:
                                # Modern revision -- alembic upgrade head will handle it.
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
                    return True  # Proceed with migrations anyway

            # Check database state
            asyncio.run(check_and_stamp_base())

            self._print_info("Running database migrations (alembic upgrade head)...")

            # Run alembic upgrade head
            # Use venv Python to ensure alembic is available (not system Python)
            venv_python = self.platform.get_venv_python(self.venv_dir)
            proc = subprocess.run(
                [str(venv_python), "-m", "alembic", "upgrade", "head"],
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
                cwd=str(cwd),
                check=False,  # Ensure correct working directory
            )

            if proc.returncode == 0:
                self._print_success("Database migrations completed successfully")
                result["success"] = True
                result["output"] = proc.stdout

                # Parse output to see which migrations ran
                for line in proc.stdout.split("\n"):
                    if "Running upgrade" in line:
                        result["migrations_applied"].append(line.strip())

                if result["migrations_applied"]:
                    self._print_info(f"Applied {len(result['migrations_applied'])} migration(s)")
                    for migration in result["migrations_applied"]:
                        self._print_info(f"  {migration}")
                else:
                    self._print_info("No new migrations to apply (database already up to date)")

                # CRITICAL: Verify essential tables were actually created
                # This catches the case where migrations "succeed" but no tables exist
                # (e.g., empty migrations/versions folder)
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
        """Set PostgreSQL password using local peer/trust authentication.

        On Linux: uses sudo -u postgres psql (peer auth over Unix socket)
        On macOS: uses psql -U postgres directly (Homebrew trust auth)

        Returns True if password was set successfully.
        """
        # Escape single quotes in password for SQL literal (double them per SQL standard).
        # This runs via subprocess/psql before psycopg2 is available in the venv.
        escaped = password.replace("'", "''")
        safe_sql = f"ALTER USER postgres PASSWORD '{escaped}';"

        system = platform.system()
        try:
            if system == "Darwin":
                # macOS (Homebrew): postgres runs as current user
                cmd = ["psql", "-U", "postgres", "-d", "postgres", "-c", safe_sql]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
            else:
                # Linux: use sudo -u postgres for peer auth
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
