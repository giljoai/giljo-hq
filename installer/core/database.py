# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import contextlib
import logging
import os
import platform
import secrets
import socket
import string
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
except ImportError:
    psycopg2 = None
    sql = None
    ISOLATION_LEVEL_AUTOCOMMIT = None


class DatabaseInstaller:

    MIN_PG_VERSION = 16
    MAX_PG_VERSION = 18
    RECOMMENDED_VERSION = 18

    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.host = settings.get("host", "localhost")
        self.port = settings.get("port", 5432)
        self.password = settings.get("password")
        self.username = settings.get("username", "postgres")
        self.db_name = settings.get("db_name", "giljo_mcp")
        self.logger = logging.getLogger(self.__class__.__name__)

        self.owner_password = None
        self.user_password = None
        self.credentials_file = None

        self.pg_version = None
        self.pg_version_string = None

    def setup(self) -> Dict[str, Any]:
        result = {"success": False, "errors": [], "warnings": []}

        try:
            self.logger.info("Checking PostgreSQL connection...")
            if not check_postgresql_connection(self.host, self.port):
                result["errors"].append("Cannot connect to PostgreSQL")
                result["postgresql_guide"] = self.get_postgresql_install_guide()
                return result

            if not psycopg2:
                self.logger.warning("psycopg2 not installed, using fallback approach")
                return self.fallback_setup()

            self.logger.info("Detecting PostgreSQL version...")
            version_result = self.detect_postgresql_version()
            if not version_result["success"]:
                self.logger.warning(
                    "Could not detect PostgreSQL version at %s:%s: %s",
                    self.host,
                    self.port,
                    version_result.get("error", "Unknown"),
                )
                result["warnings"].append(
                    f"Could not detect PostgreSQL version: {version_result.get('error', 'Unknown')}"
                )
            else:
                self.pg_version = version_result["version"]
                self.pg_version_string = version_result["version_string"]
                self.logger.info(f"Detected PostgreSQL {self.pg_version_string}")

                if self.pg_version < self.MIN_PG_VERSION:
                    result["errors"].append(
                        f"PostgreSQL {self.pg_version} is not supported. "
                        f"Minimum version: {self.MIN_PG_VERSION}. "
                        f"Please upgrade to PostgreSQL {self.RECOMMENDED_VERSION}."
                    )
                    return result
                elif self.pg_version > self.MAX_PG_VERSION:
                    result["warnings"].append(
                        f"PostgreSQL {self.pg_version} is newer than tested version {self.MAX_PG_VERSION}. "
                        "Installation will proceed but compatibility is not guaranteed."
                    )
                elif self.pg_version < self.RECOMMENDED_VERSION:
                    result["warnings"].append(
                        f"PostgreSQL {self.pg_version} is supported but version {self.RECOMMENDED_VERSION} "
                        "is recommended for best compatibility."
                    )

            self.logger.info("Attempting direct database creation...")
            direct_result = self.create_database_direct()

            if direct_result["success"]:
                self.logger.info("Database created successfully via direct connection")
                result = direct_result
                result["warnings"] = result.get("warnings", [])
            else:
                direct_errors = direct_result.get("errors", [])
                for err in direct_errors:
                    self.logger.error("Direct database creation failed: %s", err)
                self.logger.info("Direct creation failed, generating fallback scripts...")

                result = self.fallback_setup()
                if not result.get("success"):
                    result["errors"] = direct_errors + result.get("errors", [])

            return result

        except Exception as e:
            result["errors"].append(str(e))
            self.logger.error(f"Database setup failed: {e}", exc_info=True)
            return result

    def detect_postgresql_version(self) -> Dict[str, Any]:
        result = {"success": False}

        try:
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database="postgres",
                user=self.username,
                password=self.password,
                connect_timeout=5,
            )

            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version_string = cur.fetchone()[0]

                cur.execute("SHOW server_version_num;")
                version_num = int(cur.fetchone()[0])

                major_version = version_num // 10000

            conn.close()

            result["success"] = True
            result["version"] = major_version
            result["version_string"] = version_string
            result["version_num"] = version_num

            return result

        except psycopg2.OperationalError as e:
            result["error"] = f"Connection failed: {str(e)}"
            return result
        except Exception as e:
            result["error"] = str(e)
            return result

    def create_database_direct(self) -> Dict[str, Any]:
        result = {"success": False, "errors": [], "warnings": []}

        try:
            self.owner_password = self.generate_password()
            self.user_password = self.generate_password()

            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database="postgres",
                user=self.username,
                password=self.password,
                connect_timeout=10,
            )
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (self.db_name,))
                db_exists = cur.fetchone() is not None

                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", ("giljo_owner",))
                owner_exists = cur.fetchone() is not None

                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", ("giljo_user",))
                user_exists = cur.fetchone() is not None

                if owner_exists != user_exists:
                    present = "giljo_owner" if owner_exists else "giljo_user"
                    missing = "giljo_user" if owner_exists else "giljo_owner"
                    self.logger.error(
                        "Partial PostgreSQL role state: %s exists but %s does not — aborting.", present, missing
                    )
                    result["errors"].append(
                        f"Inconsistent PostgreSQL role state: '{present}' exists but '{missing}' does not. "
                        f"This usually means a prior interrupted install. To recover, either drop the "
                        f"remaining role for a clean install (psql -U postgres -c 'DROP ROLE {present};') "
                        f"or recreate '{missing}' with the password recorded in your .env, then re-run "
                        f"install.py. The installer will not auto-create '{missing}' with a random "
                        f"password because it would not match the existing '{present}' credential."
                    )
                    result["partial_roles"] = True
                    conn.close()
                    return result

                self.logger.info("Setting up database roles...")

                if owner_exists:
                    self.logger.info("giljo_owner role already exists; leaving password unchanged (co-located-safe)")
                else:
                    self.logger.info("Creating giljo_owner role")
                    cur.execute(
                        sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier("giljo_owner")),
                        [self.owner_password],
                    )

                if user_exists:
                    self.logger.info("giljo_user role already exists; leaving password unchanged (co-located-safe)")
                else:
                    self.logger.info("Creating giljo_user role")
                    cur.execute(
                        sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier("giljo_user")),
                        [self.user_password],
                    )

                if not db_exists:
                    self.logger.info(f"Creating database {self.db_name}...")
                    cur.execute(
                        sql.SQL("CREATE DATABASE {} OWNER {}").format(
                            sql.Identifier(self.db_name), sql.Identifier("giljo_owner")
                        )
                    )
                    self.logger.info("Database created successfully")
                else:
                    self.logger.info(f"Database {self.db_name} already exists")
                    result["warnings"].append(f"Database {self.db_name} already exists, using existing database")

            conn.close()

            self.logger.info("Setting up database permissions...")
            conn_db = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.db_name,
                user=self.username,
                password=self.password,
            )
            conn_db.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

            with conn_db.cursor() as cur:
                cur.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(self.db_name), sql.Identifier("giljo_user")
                    )
                )

                cur.execute(
                    sql.SQL("GRANT CREATE ON DATABASE {} TO {}").format(
                        sql.Identifier(self.db_name), sql.Identifier("giljo_owner")
                    )
                )

                self.logger.info("Creating PostgreSQL extensions (Handover 0017)...")
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                self.logger.info("Extension pg_trgm created successfully")

                cur.execute("""
                    GRANT USAGE, CREATE ON SCHEMA public TO giljo_owner;
                    GRANT ALL ON SCHEMA public TO giljo_user;
                """)

                cur.execute("""
                    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO giljo_user;
                    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO giljo_user;
                """)
                cur.execute("""
                    ALTER DEFAULT PRIVILEGES FOR ROLE giljo_owner IN SCHEMA public
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO giljo_user;
                """)

                cur.execute("""
                    ALTER DEFAULT PRIVILEGES FOR ROLE giljo_owner IN SCHEMA public
                    GRANT USAGE, SELECT ON SEQUENCES TO giljo_user;
                """)

            conn_db.close()

            self.save_credentials()

            result["success"] = True
            result["credentials"] = {"owner_password": self.owner_password, "user_password": self.user_password}
            result["credentials_file"] = str(self.credentials_file)
            result["database_existed"] = db_exists
            result["roles_reused"] = owner_exists and user_exists

            return result

        except psycopg2.OperationalError as e:
            target = f"{self.host}:{self.port}"
            error_msg = str(e).lower()
            if "password authentication failed" in error_msg:
                result["errors"].append(
                    f"Invalid PostgreSQL password for user '{self.username}' at {target} "
                    "(is another PostgreSQL answering on that port?)"
                )
            elif "could not connect" in error_msg or "connection refused" in error_msg:
                result["errors"].append(f"Cannot connect to PostgreSQL server at {target}")
            elif "permission denied" in error_msg:
                result["errors"].append(f"Insufficient privileges at {target} - try fallback script")
            else:
                result["errors"].append(f"Database operation failed at {target}: {e}")
            return result

        except psycopg2.Error as e:
            result["errors"].append(f"PostgreSQL error: {e}")
            self.logger.error(f"PostgreSQL error during database creation: {e}")
            return result

        except Exception as e:
            result["errors"].append(str(e))
            self.logger.error(f"Direct database creation failed: {e}", exc_info=True)
            return result

    def reset_role_passwords(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"success": False, "errors": []}

        try:
            self.owner_password = self.generate_password()
            self.user_password = self.generate_password()

            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database="postgres",
                user=self.username,
                password=self.password,
                connect_timeout=10,
            )
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(sql.Identifier("giljo_owner")),
                    [self.owner_password],
                )
                cur.execute(
                    sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(sql.Identifier("giljo_user")),
                    [self.user_password],
                )

            conn.close()

            self.save_credentials()

            result["success"] = True
            result["credentials"] = {"owner_password": self.owner_password, "user_password": self.user_password}
            self.logger.info("Reset giljo_owner/giljo_user passwords (--repair recovery)")
            return result

        except psycopg2.Error as e:
            result["errors"].append(f"Failed to reset PostgreSQL role passwords: {e}")
            self.logger.error(f"reset_role_passwords PostgreSQL error: {e}")
            return result
        except Exception as e:  # pragma: no cover - defensive
            result["errors"].append(str(e))
            self.logger.error(f"reset_role_passwords failed: {e}", exc_info=True)
            return result

    def fallback_setup(self) -> Dict[str, Any]:
        result = {"success": False, "errors": []}

        try:
            self.owner_password = self.generate_password()
            self.user_password = self.generate_password()

            scripts_dir = Path("installer/scripts")
            scripts_dir.mkdir(parents=True, exist_ok=True)

            if platform.system() == "Windows":
                script_path = self.generate_windows_script(scripts_dir)
            else:
                script_path = self.generate_unix_script(scripts_dir)

            self.save_credentials()

            self.display_elevation_guide(script_path)

            _skip_prompt = (
                self.settings.get("batch") or self.settings.get("headless") or self.settings.get("unattended")
            )
            if not _skip_prompt:
                input("\nPress Enter after running the script...")

                if self.verify_database_exists():
                    result["success"] = True
                    result["credentials"] = {"owner_password": self.owner_password, "user_password": self.user_password}
                    result["credentials_file"] = str(self.credentials_file)
                    self.logger.info("Database verified after fallback script execution")
                else:
                    result["errors"].append("Database not found after script execution")
            else:
                if self.verify_database_exists():
                    result["success"] = True
                    result["credentials"] = {"owner_password": self.owner_password, "user_password": self.user_password}
                    result["credentials_file"] = str(self.credentials_file)
                else:
                    result["success"] = False
                    result["manual_step_required"] = True
                    result["script_path"] = str(script_path)
                    result["errors"].append(
                        "Database was not created. Run the generated script manually, then re-run the installer."
                    )

            return result

        except Exception as e:
            result["errors"].append(str(e))
            self.logger.error(f"Fallback setup failed: {e}")
            return result

    def generate_windows_script(self, scripts_dir: Path) -> Path:
        script_path = scripts_dir / "create_db.ps1"

        script_content = f'''# Giljo HQ Database Creation Script for Windows
# Generated: {datetime.now().isoformat()}
#
# INSTRUCTIONS:
# 1. Open PowerShell as Administrator:
#    - Press Win+X and select "Windows PowerShell (Admin)"
#    - Or right-click Start and select "Windows Terminal (Admin)"
# 2. Navigate to this directory
# 3. Run: .\\create_db.ps1
#
# This script will:
# - Create PostgreSQL roles (giljo_owner, giljo_user)
# - Create the giljo_mcp database
# - Set up all required permissions
# - Save credentials for the installer

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "   Giljo HQ - PostgreSQL Database Creation Script" -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host ""

# Configuration (pre-filled by installer)
$PgHost = "{self.host}"
$PgPort = {self.port}
$PgUser = "{self.username}"
$DbName = "{self.db_name}"
$OwnerRole = "giljo_owner"
$UserRole = "giljo_user"
$OwnerPassword = "{self.owner_password}"
$UserPassword = "{self.user_password}"

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  PostgreSQL Host: $PgHost" -ForegroundColor Gray
Write-Host "  PostgreSQL Port: $PgPort" -ForegroundColor Gray
Write-Host "  Database Name:   $DbName" -ForegroundColor Gray
Write-Host ""

# Function to run psql command
function Invoke-Psql {{
    param(
        [string]$Database = "postgres",
        [string]$Command,
        [switch]$IgnoreError
    )

    try {{
        $env:PGPASSWORD = $env:POSTGRES_PASSWORD
        $output = psql -h $PgHost -p $PgPort -U $PgUser -d $Database -c $Command 2>&1
        if ($LASTEXITCODE -ne 0 -and -not $IgnoreError) {{
            throw "psql command failed: $output"
        }}
        return $output
    }} finally {{
        $env:PGPASSWORD = $null
    }}
}}

# Prompt for PostgreSQL admin password
Write-Host "PostgreSQL Administration" -ForegroundColor Yellow
$SecurePassword = Read-Host "Enter password for PostgreSQL user '$PgUser'" -AsSecureString
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
$env:POSTGRES_PASSWORD = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)

Write-Host ""
Write-Host "Testing PostgreSQL connection..." -ForegroundColor Yellow

try {{
    $version = Invoke-Psql -Command "SELECT version();"
    Write-Host "  Connected successfully!" -ForegroundColor Green
}} catch {{
    Write-Host "  ERROR: Cannot connect to PostgreSQL" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please verify:" -ForegroundColor Yellow
    Write-Host "  1. PostgreSQL is installed and running"
    Write-Host "  2. The password is correct"
    Write-Host "  3. PostgreSQL is accepting connections on port $PgPort"
    Write-Host ""
    exit 1
}}

Write-Host ""
Write-Host "Creating database roles..." -ForegroundColor Yellow

# Create owner role (idempotent -- NEVER reset password on an existing role).
# Resetting a shared role's password would silently break any co-located live
# GiljoAI installation that authenticates with the current credential. (INF-6260)
$ownerExists = (Invoke-Psql -Command "SELECT 1 FROM pg_roles WHERE rolname='$OwnerRole';" -IgnoreError) -match "1"
if ($ownerExists) {{
    Write-Host "  Role '$OwnerRole' already exists; leaving password unchanged (co-located-safe)." -ForegroundColor Gray
}} else {{
    Write-Host "  Creating role '$OwnerRole'..." -ForegroundColor Gray
    Invoke-Psql -Command "CREATE ROLE $OwnerRole LOGIN PASSWORD '$OwnerPassword';"
}}

# Create user role (idempotent -- NEVER reset password on an existing role). (INF-6260)
$userExists = (Invoke-Psql -Command "SELECT 1 FROM pg_roles WHERE rolname='$UserRole';" -IgnoreError) -match "1"
if ($userExists) {{
    Write-Host "  Role '$UserRole' already exists; leaving password unchanged (co-located-safe)." -ForegroundColor Gray
}} else {{
    Write-Host "  Creating role '$UserRole'..." -ForegroundColor Gray
    Invoke-Psql -Command "CREATE ROLE $UserRole LOGIN PASSWORD '$UserPassword';"
}}

Write-Host "  Roles created successfully!" -ForegroundColor Green

Write-Host ""
Write-Host "Creating database..." -ForegroundColor Yellow

# Check if database exists
$dbExists = Invoke-Psql -Command "SELECT 1 FROM pg_database WHERE datname='$DbName';" -IgnoreError

if ($dbExists -match "1") {{
    Write-Host "  Database '$DbName' already exists" -ForegroundColor Yellow
}} else {{
    Write-Host "  Creating database '$DbName'..." -ForegroundColor Gray
    Invoke-Psql -Command "CREATE DATABASE $DbName OWNER $OwnerRole;"
    Write-Host "  Database created successfully!" -ForegroundColor Green
}}

Write-Host ""
Write-Host "Setting up permissions..." -ForegroundColor Yellow

# Grant permissions
Invoke-Psql -Database $DbName -Command "GRANT CONNECT ON DATABASE $DbName TO $UserRole;" -IgnoreError
Invoke-Psql -Database $DbName -Command "GRANT USAGE, CREATE ON SCHEMA public TO $OwnerRole;" -IgnoreError
Invoke-Psql -Database $DbName -Command "GRANT USAGE ON SCHEMA public TO $UserRole;" -IgnoreError

# Grant default privileges
Invoke-Psql -Database $DbName -Command @"
ALTER DEFAULT PRIVILEGES FOR ROLE $OwnerRole IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $UserRole;
"@ -IgnoreError

Invoke-Psql -Database $DbName -Command @"
ALTER DEFAULT PRIVILEGES FOR ROLE $OwnerRole IN SCHEMA public
GRANT USAGE, SELECT ON SEQUENCES TO $UserRole;
"@ -IgnoreError

Write-Host "  Permissions configured successfully!" -ForegroundColor Green

# Clear the password from environment
$env:POSTGRES_PASSWORD = $null

# Create verification flag for installer
Write-Host ""
Write-Host "Creating verification flag..." -ForegroundColor Yellow
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"DATABASE_CREATED=$timestamp" | Out-File -FilePath "..\\..\\database_created.flag" -Encoding UTF8

Write-Host ""
Write-Host "====================================================================" -ForegroundColor Green
Write-Host "   Database Setup Complete!" -ForegroundColor Green
Write-Host "====================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Database Details:" -ForegroundColor Yellow
Write-Host "  Database: $DbName" -ForegroundColor Gray
Write-Host "  Owner Role: $OwnerRole" -ForegroundColor Gray
Write-Host "  User Role: $UserRole" -ForegroundColor Gray
Write-Host ""
Write-Host "Credentials have been saved to:" -ForegroundColor Yellow
Write-Host "  installer\\credentials\\db_credentials.txt" -ForegroundColor Gray
Write-Host ""
Write-Host "You can now return to the installer and press Enter to continue." -ForegroundColor Cyan
Write-Host ""
'''

        # noqa: S105 — generated passwords are written into the elevation script for one-time use during install
        script_path.write_text(script_content, encoding="utf-8")
        self.logger.info(f"Generated Windows script: {script_path}")
        return script_path

    def generate_unix_script(self, scripts_dir: Path) -> Path:
        script_path = scripts_dir / "create_db.sh"

        script_content = f'''#!/bin/bash
# Giljo HQ Database Creation Script for Linux/macOS
# Generated: {datetime.now().isoformat()}
#
# INSTRUCTIONS:
# 1. Make sure you have the PostgreSQL admin password
# 2. Run this script with: bash create_db.sh
#    (On Linux, you may need: sudo bash create_db.sh)
#
# This script will:
# - Create PostgreSQL roles (giljo_owner, giljo_user)
# - Create the giljo_mcp database
# - Set up all required permissions
# - Save credentials for the installer

set -euo pipefail

echo ""
echo "====================================================================="
echo "   Giljo HQ - PostgreSQL Database Creation Script"
echo "====================================================================="
echo ""

# Configuration (pre-filled by installer)
PG_HOST="{self.host}"
PG_PORT={self.port}
PG_USER="{self.username}"
DB_NAME="{self.db_name}"
OWNER_ROLE="giljo_owner"
USER_ROLE="giljo_user"
OWNER_PASSWORD="{self.owner_password}"
USER_PASSWORD="{self.user_password}"

echo "Configuration:"
echo "  PostgreSQL Host: $PG_HOST"
echo "  PostgreSQL Port: $PG_PORT"
echo "  Database Name:   $DB_NAME"
echo ""

# Function to run psql command
run_psql() {{
    local database="${{1:-postgres}}"
    local command="$2"
    local ignore_error="${{3:-false}}"

    if [ "$ignore_error" = "true" ]; then
        PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$database" -c "$command" 2>/dev/null || true
    else
        PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$database" -c "$command"
    fi
}}

# Prompt for PostgreSQL admin password
echo "PostgreSQL Administration"
read -sp "Enter password for PostgreSQL user '$PG_USER': " POSTGRES_PASSWORD
echo ""
echo ""

echo "Testing PostgreSQL connection..."

if ! run_psql "postgres" "SELECT version();" "true" > /dev/null 2>&1; then
    echo "  ERROR: Cannot connect to PostgreSQL"
    echo ""
    echo "Please verify:"
    echo "  1. PostgreSQL is installed and running"
    echo "  2. The password is correct"
    echo "  3. PostgreSQL is accepting connections on port $PG_PORT"
    echo ""
    exit 1
fi

echo "  Connected successfully!"
echo ""

echo "Creating database roles..."

# Create owner role (idempotent -- NEVER reset password on an existing role).
# Resetting a shared role's password would silently break any co-located live
# GiljoAI installation that authenticates with the current credential. (INF-6260)
if run_psql "postgres" "SELECT 1 FROM pg_roles WHERE rolname='$OWNER_ROLE';" "true" | grep -q "1"; then
    echo "  Role '$OWNER_ROLE' already exists; leaving password unchanged (co-located-safe)."
else
    echo "  Creating role '$OWNER_ROLE'..."
    run_psql "postgres" "CREATE ROLE $OWNER_ROLE LOGIN PASSWORD '$OWNER_PASSWORD';"
fi

# Create user role (idempotent -- NEVER reset password on an existing role). (INF-6260)
if run_psql "postgres" "SELECT 1 FROM pg_roles WHERE rolname='$USER_ROLE';" "true" | grep -q "1"; then
    echo "  Role '$USER_ROLE' already exists; leaving password unchanged (co-located-safe)."
else
    echo "  Creating role '$USER_ROLE'..."
    run_psql "postgres" "CREATE ROLE $USER_ROLE LOGIN PASSWORD '$USER_PASSWORD';"
fi

echo "  Roles created successfully!"
echo ""

echo "Creating database..."

# Check if database exists
if run_psql "postgres" "SELECT 1 FROM pg_database WHERE datname='$DB_NAME';" "true" | grep -q "1"; then
    echo "  Database '$DB_NAME' already exists"
else
    echo "  Creating database '$DB_NAME'..."
    run_psql "postgres" "CREATE DATABASE $DB_NAME OWNER $OWNER_ROLE;"
    echo "  Database created successfully!"
fi

echo ""
echo "Setting up permissions..."

# Grant permissions (ignore errors if already granted)
run_psql "$DB_NAME" "GRANT CONNECT ON DATABASE $DB_NAME TO $USER_ROLE;" "true"
run_psql "$DB_NAME" "GRANT USAGE, CREATE ON SCHEMA public TO $OWNER_ROLE;" "true"
run_psql "$DB_NAME" "GRANT USAGE ON SCHEMA public TO $USER_ROLE;" "true"

# Grant default privileges
run_psql "$DB_NAME" "ALTER DEFAULT PRIVILEGES FOR ROLE $OWNER_ROLE IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $USER_ROLE;" "true"
run_psql "$DB_NAME" "ALTER DEFAULT PRIVILEGES FOR ROLE $OWNER_ROLE IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO $USER_ROLE;" "true"

echo "  Permissions configured successfully!"
echo ""

# Clear password from environment
unset POSTGRES_PASSWORD

# Create verification flag for installer
echo "Creating verification flag..."
timestamp=$(date '+%Y-%m-%d %H:%M:%S')
echo "DATABASE_CREATED=$timestamp" > ../../database_created.flag

echo ""
echo "====================================================================="
echo "   Database Setup Complete!"
echo "====================================================================="
echo ""
echo "Database Details:"
echo "  Database: $DB_NAME"
echo "  Owner Role: $OWNER_ROLE"
echo "  User Role: $USER_ROLE"
echo ""
echo "Credentials have been saved to:"
echo "  installer/credentials/db_credentials.txt"
echo ""
echo "You can now return to the installer and press Enter to continue."
echo ""
'''

        # noqa: S105 — generated passwords are written into the elevation script for one-time use during install
        script_path.write_text(script_content, encoding="utf-8")
        script_path.chmod(0o755)
        self.logger.info(f"Generated Unix script: {script_path}")
        return script_path

    def display_elevation_guide(self, script_path: Path):
        print("\n" + "=" * 60)
        print("Database Setup Required")
        print("=" * 60)
        print()
        print("Administrative privileges are needed to create the database.")
        print("A script has been generated with all necessary commands.")
        print()

        abs_script = Path(script_path).resolve()
        try:
            display_path = abs_script.relative_to(Path.cwd().resolve())
        except ValueError:
            display_path = abs_script

        if platform.system() == "Windows":
            print("Please run the following in an Administrator PowerShell:")
            print()
            print(f"  .\\{display_path}")
            print()
            print("To open Administrator PowerShell:")
            print("  1. Right-click Start button")
            print("  2. Select 'Windows PowerShell (Admin)'")
            print("  3. Navigate to this directory")
            print("  4. Run the script above")
        else:
            print("Please run the following command:")
            print()
            print(f"  sudo bash {display_path}")
            print()

        print()
        print("The script will:")
        print("  - Create the giljo_mcp database")
        print("  - Set up required roles and permissions")
        print("  - Save credentials securely")
        print()

    def verify_database_exists(self) -> bool:
        flag_file = Path("database_created.flag")
        if flag_file.exists():
            self.logger.info("Database creation flag found")
            flag_file.unlink()
            return True

        if psycopg2:
            with contextlib.suppress(Exception):
                conn = psycopg2.connect(
                    host=self.host,
                    port=self.port,
                    database=self.db_name,
                    user="giljo_user",
                    password=self.user_password,
                )
                conn.close()
                return True
            self.logger.debug("Connection test to %s failed", self.db_name)

        return False

    def create_default_admin_account(self) -> Dict[str, Any]:
        result = {"success": False, "errors": []}

        try:
            try:
                import bcrypt
            except ImportError:
                result["errors"].append("bcrypt not installed - cannot hash password")
                return result

            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.db_name,
                user="giljo_owner",
                password=self.owner_password,
                connect_timeout=10,
            )
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM users WHERE username = %s", ("admin",))
                if cur.fetchone():
                    self.logger.info("Admin user already exists, skipping creation")
                    result["success"] = True
                    result["already_exists"] = True
                    return result

                password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode("utf-8")

                import uuid

                admin_id = str(uuid.uuid4())

                cur.execute(
                    """
                    INSERT INTO users (
                        id, tenant_key, username, password_hash,
                        email, role, is_active, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                """,
                    (admin_id, "default", "admin", password_hash, "admin@localhost", "admin", True),
                )

                cur.execute("""
                    UPDATE setup_state
                    SET default_password_active = true
                    WHERE tenant_key = 'default'
                """)

                if cur.rowcount == 0:
                    setup_id = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO setup_state (
                            id, tenant_key, completed, default_password_active,
                            setup_version, created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, NOW()
                        )
                    """,
                        (setup_id, "default", False, True, "3.0.0"),
                    )

            conn.close()

            print("\n" + "=" * 60)
            print("Default Admin Credentials:")
            print("  Username: admin")
            print("  Password: admin")
            print("\n  IMPORTANT: Change this password on first login!")
            print("=" * 60 + "\n")

            self.logger.info("Default admin account created successfully")
            result["success"] = True
            result["username"] = "admin"
            return result

        except Exception as e:
            result["errors"].append(f"Failed to create admin account: {str(e)}")
            self.logger.error(f"Admin account creation failed: {e}", exc_info=True)
            return result

    def save_credentials(self):
        credentials_dir = Path("installer/credentials")
        credentials_dir.mkdir(parents=True, exist_ok=True)

        self.credentials_file = credentials_dir / "db_credentials.txt"

        content = f"""# Giljo HQ Database Credentials
# Generated: {datetime.now().isoformat()}
# KEEP THIS FILE SECURE!

DATABASE_NAME={self.db_name}
DATABASE_HOST={self.host}
DATABASE_PORT={self.port}

OWNER_ROLE=giljo_owner
OWNER_PASSWORD={self.owner_password}

USER_ROLE=giljo_user
USER_PASSWORD={self.user_password}

# Connection strings:
OWNER_URL=postgresql://giljo_owner:{self.owner_password}@{self.host}:{self.port}/{self.db_name}
USER_URL=postgresql://giljo_user:{self.user_password}@{self.host}:{self.port}/{self.db_name}
"""

        # noqa: S105 — credentials file written with restricted permissions (0o600), required for installer handoff
        self.credentials_file.write_text(content, encoding="utf-8")

        if platform.system() != "Windows":
            os.chmod(self.credentials_file, 0o600)

        self.logger.info(f"Credentials saved to: {self.credentials_file}")

    def generate_password(self, length: int = 20) -> str:
        alphabet = string.ascii_letters + string.digits
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        return password

    def get_postgresql_install_guide(self) -> str:
        system = platform.system()

        if system == "Windows":
            return """
PostgreSQL Installation Guide for Windows:

1. Download PostgreSQL 18 from:
   https://www.postgresql.org/download/windows/

2. Run the installer as Administrator

3. During installation:
   - Remember the password for 'postgres' user
   - Default port is 5432
   - Allow the installer to configure PATH

4. After installation, return here and run the installer again
"""
        elif system == "Darwin":
            return """
PostgreSQL Installation Guide for macOS:

Using Homebrew:
  brew install postgresql@18
  brew services start postgresql@18

Using official installer:
  1. Download from https://www.postgresql.org/download/macosx/
  2. Run the installer
  3. Remember the 'postgres' user password

After installation, return here and run the installer again
"""
        else:
            return """
PostgreSQL Installation Guide for Linux:

Ubuntu/Debian:
  sudo apt-get update
  sudo apt-get install postgresql-18

RHEL/CentOS/Fedora:
  sudo dnf install postgresql18-server
  sudo postgresql-18-setup initdb
  sudo systemctl enable --now postgresql-18

Arch:
  sudo pacman -S postgresql
  sudo -u postgres initdb -D /var/lib/postgres/data
  sudo systemctl enable --now postgresql

After installation, return here and run the installer again
"""

    async def create_database_async(self) -> Dict[str, Any]:
        return self.create_database_direct()

    async def create_tables_async(self) -> Dict[str, Any]:
        result = {"success": False, "errors": [], "warnings": []}

        deprecation_msg = (
            "DEPRECATED: create_tables_async() is deprecated in v3.1.0+. "
            "Use Alembic migrations (run_database_migrations) for production installs. "
            "This method is kept only for test compatibility and will be removed in v4.0."
        )
        result["warnings"].append(deprecation_msg)
        self.logger.warning(deprecation_msg)

        try:
            from giljo_mcp.database_manager import DatabaseManager

            from giljo_mcp.models import Base

            db_url = f"postgresql://giljo_owner:{self.owner_password}@{self.host}:{self.port}/{self.db_name}"
            db_manager = DatabaseManager(db_url)

            self.logger.info("Creating database tables from SQLAlchemy models (DEPRECATED)...")
            Base.metadata.create_all(db_manager.engine)

            table_count = len(Base.metadata.tables)
            self.logger.info(f"Created {table_count} tables successfully")

            result["success"] = True
            result["tables_created"] = table_count
            return result

        except Exception as e:
            result["errors"].append(f"Table creation failed: {str(e)}")
            self.logger.error(f"Failed to create tables: {e}", exc_info=True)
            return result

    def _generate_password(self, length: int = 20) -> str:
        return self.generate_password(length=length)

    def run_migrations(self, alembic_ini_path: Optional[Path] = None) -> Dict[str, Any]:
        result = {"success": False, "errors": [], "warnings": []}

        try:
            try:
                from alembic import command
                from alembic.config import Config
            except ImportError:
                result["errors"].append("Alembic not installed - cannot run migrations")
                self.logger.warning("Alembic not available for migrations")
                return result

            if alembic_ini_path is None:
                search_paths = [
                    Path.cwd() / "alembic.ini",
                    Path.cwd().parent / "alembic.ini",
                    Path.cwd().parent.parent / "alembic.ini",
                ]
                for path in search_paths:
                    if path.exists():
                        alembic_ini_path = path
                        break

            if alembic_ini_path is None or not alembic_ini_path.exists():
                result["warnings"].append("alembic.ini not found - skipping migrations")
                self.logger.warning("No alembic.ini found, skipping migrations")
                result["success"] = True
                return result

            self.logger.info(f"Running migrations using {alembic_ini_path}")

            alembic_cfg = Config(str(alembic_ini_path))

            db_url = f"postgresql://{self.settings.get('pg_user', 'giljo_owner')}:{self.owner_password}@{self.host}:{self.port}/{self.db_name}"
            alembic_cfg.set_main_option("sqlalchemy.url", db_url)

            self.logger.info("Upgrading database schema to latest version...")
            command.upgrade(alembic_cfg, "head")

            self.logger.info("Migrations completed successfully")
            result["success"] = True
            return result

        except Exception as e:
            result["errors"].append(f"Migration failed: {str(e)}")
            self.logger.error(f"Failed to run migrations: {e}", exc_info=True)
            return result


def check_postgresql_connection(host: str, port: int, timeout: int = 5) -> bool:
    with contextlib.suppress(Exception):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    return False


def detect_postgresql_cli() -> Optional[str]:
    try:
        result = subprocess.run(["psql", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return None
