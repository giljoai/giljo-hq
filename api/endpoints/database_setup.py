# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from giljo_mcp._config_io import get_config_path, read_config, write_config
from giljo_mcp.utils.log_sanitizer import sanitize


router = APIRouter()
logger = logging.getLogger(__name__)


def require_setup_incomplete() -> None:
    try:
        import psycopg2

        db_host = os.getenv("POSTGRES_HOST") or os.getenv("DB_HOST")
        db_port = os.getenv("POSTGRES_PORT") or os.getenv("DB_PORT")
        db_name = os.getenv("POSTGRES_DB") or os.getenv("DB_NAME")
        db_user = os.getenv("POSTGRES_USER") or os.getenv("DB_USER")
        db_password = os.getenv("POSTGRES_PASSWORD") or os.getenv("DB_PASSWORD")

        if not all([db_host, db_port, db_name, db_user, db_password]):
            return

        with (
            psycopg2.connect(
                host=db_host,
                port=int(db_port),
                database=db_name,
                user=db_user,
                password=db_password,
                connect_timeout=3,
            ) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT COUNT(*) FROM users")
            user_count = cur.fetchone()[0]

        if user_count > 0:
            raise HTTPException(
                status_code=403,
                detail="Setup already completed. Use admin panel to reconfigure.",
            )
    except HTTPException:
        raise
    except Exception as _exc:  # noqa: BLE001 -- broad catch intentional: any DB failure means setup is not complete
        return


class DatabaseSetupRequest(BaseModel):
    """Request model for database setup."""

    host: str = Field(default="localhost", description="PostgreSQL host")
    port: int = Field(default=5432, description="PostgreSQL port")
    admin_user: str = Field(default="postgres", description="PostgreSQL admin username")
    admin_password: str = Field(..., description="PostgreSQL admin password")
    database_name: str = Field(default="giljo_mcp", description="Database name to create")


@router.post("/test-connection", dependencies=[Depends(require_setup_incomplete)])
async def test_database_connection(request: DatabaseSetupRequest) -> dict:
    """
    Test connection to PostgreSQL server.

    Does NOT create database or make any changes.
    Used to validate credentials before proceeding with setup.

    Args:
        request: Database connection parameters

    Returns:
        Connection test result
    """
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=request.host,
            port=request.port,
            database="postgres",
            user=request.admin_user,
            password=request.admin_password,
            connect_timeout=5,
        )

        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            version_string = cur.fetchone()[0]

            cur.execute("SHOW server_version_num;")
            version_num = int(cur.fetchone()[0])
            major_version = version_num // 10000

        conn.close()

        conn = psycopg2.connect(
            host=request.host,
            port=request.port,
            database="postgres",
            user=request.admin_user,
            password=request.admin_password,
            connect_timeout=5,
        )

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (request.database_name,))
            database_exists = cur.fetchone() is not None

        conn.close()

        return {
            "success": True,
            "status": "connected",
            "message": "Successfully connected to PostgreSQL",
            "postgresql_version": major_version,
            "version_string": version_string,
            "database_exists": database_exists,
        }

    except psycopg2.OperationalError as e:
        error_msg = str(e).lower()
        if "password authentication failed" in error_msg:
            raise HTTPException(
                status_code=401,
                detail="Invalid PostgreSQL admin password",
            ) from e
        if "could not connect" in error_msg or "connection refused" in error_msg:
            raise HTTPException(
                status_code=503,
                detail="Cannot connect to PostgreSQL server. Is PostgreSQL running?",
            ) from e
        logger.error("Database connection failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Connection failed. Check server logs.") from e

    except (ImportError, OSError, ValueError) as e:
        if isinstance(e, ImportError):
            raise HTTPException(status_code=500, detail="psycopg2 not installed") from None
        logger.error("Connection test failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Connection test failed. Check server logs.") from e


@router.post("/setup", dependencies=[Depends(require_setup_incomplete)])
async def setup_database(request: DatabaseSetupRequest) -> dict:
    """
    Set up PostgreSQL database for Giljo HQ.

    This endpoint:
    1. Tests connection to PostgreSQL with admin credentials
    2. Creates giljo_mcp database if it doesn't exist
    3. Creates database roles (giljo_owner, giljo_user)
    4. Runs Alembic migrations to create schema
    5. Updates config.yaml with validated credentials

    Args:
        request: Database setup parameters

    Returns:
        Setup result with success status, credentials, and any errors/warnings
    """
    from installer.core.database import DatabaseInstaller

    try:
        settings = {
            "pg_host": request.host,
            "pg_port": request.port,
            "pg_user": request.admin_user,
            "pg_password": request.admin_password,
        }

        db_installer = DatabaseInstaller(settings)

        logger.info(f"Setting up database {sanitize(request.database_name)}...")
        setup_result = db_installer.setup()

        if not setup_result.get("success"):
            errors = setup_result.get("errors", ["Unknown error during database setup"])
            logger.error("Database setup failed: %s", "; ".join(errors))
            raise HTTPException(
                status_code=500,
                detail="Database setup failed. Check server logs for details.",
            )

        logger.info("Running Alembic migrations...")
        alembic_ini = Path.cwd() / "alembic.ini"
        migration_result = db_installer.run_migrations(alembic_ini)

        if not migration_result.get("success"):
            logger.warning(f"Migrations failed: {migration_result.get('errors')}")

        logger.info("Updating config.yaml with database credentials...")
        config_path = get_config_path()

        if not config_path.exists():
            raise HTTPException(
                status_code=500,
                detail="config.yaml not found - cannot update credentials",
            )

        config_data = read_config(config_path)

        if "database" not in config_data:
            config_data["database"] = {}

        config_data["database"].update(
            {
                "type": "postgresql",
                "host": request.host,
                "port": request.port,
                "name": request.database_name,
                "user": "giljo_user",
                "password": setup_result["credentials"]["user_password"],
            }
        )

        if "setup_mode" in config_data:
            del config_data["setup_mode"]

        backup_path = config_path.with_suffix(f".yaml.backup_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}")
        shutil.copy(config_path, backup_path)

        write_config(config_data, config_path)

        logger.info("Database setup completed successfully")

        return {
            "success": True,
            "status": "completed",
            "message": "Database created and configured successfully",
            "database": request.database_name,
            "host": request.host,
            "port": request.port,
            "credentials_file": setup_result.get("credentials_file"),
            "migrations": migration_result.get("success", False),
            "warnings": setup_result.get("warnings", []) + migration_result.get("warnings", []),
            "config_backup": str(backup_path),
        }

    except (ImportError, OSError, ValueError) as e:
        logger.error("Database setup failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Database setup failed. Check server logs for details.") from e


@router.get("/verify", dependencies=[Depends(require_setup_incomplete)])
async def verify_database_setup() -> dict:
    """
    Verify database setup from CLI installation.

    Reads credentials from .env file (server-side only, never sent to client).
    Tests connection to verify database exists and is accessible.
    Checks schema migration status.

    This endpoint is called by the wizard DatabaseStep to verify what
    the CLI installer already created. NO credential input from user.

    Security: Credentials are read from environment variables (loaded from .env
    at startup) and NEVER sent to the frontend. Only non-sensitive metadata
    (database name, host, port, version, table count) is returned.

    Returns:
        Verification result with connection status and database info
    """
    try:
        import psycopg2

        db_host = os.getenv("POSTGRES_HOST") or os.getenv("DB_HOST")
        db_port = os.getenv("POSTGRES_PORT") or os.getenv("DB_PORT")
        db_name = os.getenv("POSTGRES_DB") or os.getenv("DB_NAME")
        db_user = os.getenv("POSTGRES_USER") or os.getenv("DB_USER")
        db_password = os.getenv("POSTGRES_PASSWORD") or os.getenv("DB_PASSWORD")

        if not all([db_host, db_port, db_name, db_user, db_password]):
            missing_vars = []
            if not db_host:
                missing_vars.append("POSTGRES_HOST/DB_HOST")
            if not db_port:
                missing_vars.append("POSTGRES_PORT/DB_PORT")
            if not db_name:
                missing_vars.append("POSTGRES_DB/DB_NAME")
            if not db_user:
                missing_vars.append("POSTGRES_USER/DB_USER")
            if not db_password:
                missing_vars.append("POSTGRES_PASSWORD/DB_PASSWORD")

            raise HTTPException(
                status_code=400,
                detail=f"Database credentials not found in .env file. Missing: {', '.join(missing_vars)}",
            )

        try:
            conn = psycopg2.connect(
                host=db_host,
                port=int(db_port),
                database=db_name,
                user=db_user,
                password=db_password,
                connect_timeout=5,
            )

            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version_string = cur.fetchone()[0]

                cur.execute("SHOW server_version_num;")
                version_num = int(cur.fetchone()[0])
                major_version = version_num // 10000

                cur.execute("""
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                """)
                tables_count = cur.fetchone()[0]

            conn.close()

            schema_migrated = tables_count >= 10

            logger.info(f"Database verification successful: {db_name}@{db_host}:{db_port}, {tables_count} tables")

            return {
                "success": True,
                "status": "verified",
                "message": "Database connection verified successfully",
                "database": db_name,
                "host": db_host,
                "port": int(db_port),
                "postgresql_version": major_version,
                "version_string": version_string,
                "schema_migrated": schema_migrated,
                "tables_count": tables_count,
            }

        except psycopg2.OperationalError as e:
            error_msg = str(e).lower()

            if "password authentication failed" in error_msg:
                raise HTTPException(
                    status_code=401,
                    detail="Database authentication failed. Credentials in .env may be incorrect.",
                ) from e
            if "database" in error_msg and "does not exist" in error_msg:
                raise HTTPException(
                    status_code=404,
                    detail=f"Database '{db_name}' does not exist. Please run CLI installer first.",
                ) from e
            if "could not connect" in error_msg or "connection refused" in error_msg:
                raise HTTPException(
                    status_code=503,
                    detail="Cannot connect to PostgreSQL server. Is PostgreSQL running?",
                ) from e
            logger.error("Database connection failed: %s", e, exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Database connection failed. Check server logs.",
            ) from e

    except (ImportError, OSError, ValueError) as e:
        if isinstance(e, ImportError):
            raise HTTPException(status_code=500, detail="psycopg2 not installed") from None
        logger.error("Database verification failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Database verification failed. Check server logs.") from e
