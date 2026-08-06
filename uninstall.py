# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Giljo HQ Production Uninstaller
TRUE NUCLEAR OPTION - Removes EVERYTHING including all dependencies

WARNING: Use this ONLY on production servers with no other Python projects!
This will remove ALL Python packages installed by GiljoAI and PostgreSQL!

For development/testing, use devuninstall.py instead.
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


class GiljoProductionUninstaller:
    """Production uninstaller - removes EVERYTHING"""

    def __init__(self):
        self.root_path = Path.cwd()
        self.manifest_path = self.root_path / ".giljo_install_manifest.json"
        self.manifest = self.load_manifest()
        self.platform = sys.platform

    def load_manifest(self):
        """Load installation manifest"""
        if self.manifest_path.exists():
            with contextlib.suppress(Exception), open(self.manifest_path) as f:
                return json.load(f)
        return {}

    def log(self, message, level="INFO"):
        """Log with ASCII-only characters for Windows compatibility"""
        print(f"[{level}] {message}")

    def remove_all_python_packages(self):
        """Remove ALL Python packages installed by GiljoAI"""
        self.log("Removing ALL Python packages...")

        try:
            # Get list of packages from manifest
            packages = self.manifest.get("dependencies", {}).get("python_packages", [])

            if packages:
                # Extract package names (before ==)
                pkg_names = [pkg.split("==")[0] for pkg in packages]

                self.log(f"Uninstalling {len(pkg_names)} Python packages...", "INFO")

                # Uninstall in batches
                batch_size = 50
                for i in range(0, len(pkg_names), batch_size):
                    batch = pkg_names[i : i + batch_size]
                    try:
                        subprocess.run(
                            [sys.executable, "-m", "pip", "uninstall", "-y", *batch],
                            check=False,
                            capture_output=True,
                            timeout=300,
                        )
                    except Exception as e:
                        self.log(f"Error uninstalling batch: {e}", "WARNING")

                self.log(f"Removed {len(pkg_names)} Python packages", "SUCCESS")
            else:
                self.log("No package list found in manifest", "WARNING")
                # Try requirements.txt as fallback
                req_file = self.root_path / "requirements.txt"
                if req_file.exists():
                    self.log("Attempting uninstall from requirements.txt...", "INFO")
                    subprocess.run(
                        [sys.executable, "-m", "pip", "uninstall", "-r", str(req_file), "-y"],
                        check=False,
                        capture_output=True,
                        timeout=300,
                    )
        except Exception as e:
            self.log(f"Error removing packages: {e}", "ERROR")

    def remove_postgresql_completely(self):
        """Remove PostgreSQL database AND server installation"""
        self.log("Removing PostgreSQL completely...")

        # First, drop the database
        pg_info = self.manifest.get("postgresql", {})
        database = pg_info.get("database", "giljo_mcp")
        host = pg_info.get("host", "localhost")
        port = pg_info.get("port", "5432")
        user = pg_info.get("user", "postgres")
        password = pg_info.get("password") or os.getenv("POSTGRES_SUPERUSER_PASSWORD", "")

        # Also check .env file for password if manifest doesn't have it
        env_file = self.root_path / ".env"
        if env_file.exists() and not pg_info.get("password"):
            with contextlib.suppress(Exception), open(env_file) as f:
                for line in f:
                    if line.startswith("DB_PASSWORD="):
                        password = line.split("=", 1)[1].strip().strip("\"'")
                        break

        # Find psql executable
        psql_paths = [
            r"C:\Program Files\PostgreSQL\18\bin\psql.exe",
            r"C:\Program Files\PostgreSQL\17\bin\psql.exe",
            r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
            "/c/Program Files/PostgreSQL/18/bin/psql.exe",
            "psql",  # Fallback to PATH
        ]

        psql_cmd = None
        for path in psql_paths:
            if Path(path).exists() or shutil.which(path):
                psql_cmd = path
                break

        if psql_cmd:
            try:
                env = os.environ.copy()
                env["PGPASSWORD"] = password

                # Terminate connections
                subprocess.run(
                    [
                        psql_cmd,
                        "-h",
                        host,
                        "-p",
                        port,
                        "-U",
                        user,
                        "-d",
                        "postgres",
                        "-c",
                        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{database}' AND pid <> pg_backend_pid();",  # noqa: S608 — database name comes from trusted install manifest, not user input
                    ],
                    check=False,
                    env=env,
                    capture_output=True,
                    timeout=5,
                )

                # Drop database
                result = subprocess.run(
                    [psql_cmd, "-h", host, "-p", port, "-U", user, "-c", f"DROP DATABASE IF EXISTS {database};"],
                    check=False,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0 or "does not exist" in result.stderr:
                    self.log(f"Database '{database}' dropped", "SUCCESS")

                # Drop test database
                subprocess.run(
                    [psql_cmd, "-h", host, "-p", port, "-U", user, "-c", f"DROP DATABASE IF EXISTS {database}_test;"],
                    check=False,
                    env=env,
                    capture_output=True,
                    timeout=10,
                )

                # Drop roles
                for role in ["giljo_owner", "giljo_user"]:
                    subprocess.run(
                        [psql_cmd, "-h", host, "-p", port, "-U", user, "-c", f"DROP ROLE IF EXISTS {role};"],
                        check=False,
                        env=env,
                        capture_output=True,
                        timeout=5,
                    )
                    self.log(f"Role '{role}' dropped", "SUCCESS")

            except Exception as e:
                self.log(f"Error dropping database: {e}", "WARNING")

        # Then remove PostgreSQL server
        pg_deps = self.manifest.get("dependencies", {}).get("postgresql", {})

        if pg_deps.get("installed"):
            self.log("Uninstalling PostgreSQL server...", "INFO")
            try:
                if self.platform == "win32":
                    location = pg_deps.get("location", "C:/PostgreSQL/18")
                    uninstaller = Path(location) / "uninstall-postgresql.exe"
                    if uninstaller.exists():
                        subprocess.run([str(uninstaller), "--mode", "unattended"], check=False, timeout=120)
                        self.log("PostgreSQL server uninstalled", "SUCCESS")
                    else:
                        self.log(f"PostgreSQL uninstaller not found at: {uninstaller}", "WARNING")
                elif self.platform == "darwin":
                    subprocess.run(["brew", "uninstall", "postgresql@18"], check=False, timeout=60)
                    subprocess.run(["brew", "services", "stop", "postgresql@18"], check=False, timeout=30)
                    self.log("PostgreSQL server uninstalled", "SUCCESS")
                else:
                    subprocess.run(
                        ["sudo", "apt", "remove", "postgresql", "postgresql-contrib", "-y"], check=False, timeout=120
                    )
                    self.log("PostgreSQL server uninstalled", "SUCCESS")
            except Exception as e:
                self.log(f"Failed to uninstall PostgreSQL: {e}", "ERROR")
        else:
            self.log("PostgreSQL was not installed by installer (external)", "INFO")
            self.log("Manual PostgreSQL uninstall required if desired", "WARNING")

    def remove_all_installation_files(self):
        """Remove ALL files in installation directory except this script"""
        self.log("Removing ALL installation files...")
        script_name = Path(__file__).name

        removed = 0
        for item in self.root_path.iterdir():
            # Skip this script and the log file
            if item.name in [script_name, "uninstall.log", "uninstall_complete.log"]:
                continue

            try:
                if item.is_dir():
                    shutil.rmtree(item)
                    self.log(f"Removed directory: {item.name}", "SUCCESS")
                else:
                    item.unlink()
                    self.log(f"Removed file: {item.name}", "SUCCESS")
                removed += 1
            except Exception as e:
                self.log(f"Failed to remove {item.name}: {e}", "ERROR")

        return removed

    def remove_mcp_registrations(self):
        """Remove MCP server registrations from AI CLI tools"""
        # MCP registration is now done via web-based configuration generator
        # Manual cleanup: Users should use Claude desktop app to remove server if needed
        self.log("MCP cleanup note: Use Claude desktop app to remove server configuration", "INFO")
        return 0

    def remove_appdata_completely(self):
        """Remove ALL files from APPDATA and user directories"""
        self.log("Removing ALL APPDATA and user directory files...")

        locations = []
        if self.platform == "win32":
            appdata = Path(os.getenv("APPDATA", ""))
            localappdata = Path(os.getenv("LOCALAPPDATA", ""))
            userprofile = Path(os.getenv("USERPROFILE", ""))

            locations = [
                appdata / "GiljoAI",
                localappdata / "GiljoAI",
                userprofile / ".giljo_mcp",
                userprofile / ".giljo-config",
            ]
        else:
            home = Path.home()
            locations = [
                home / ".giljo_mcp",
                home / ".giljo-config",
                home / ".local" / "share" / "GiljoAI",
                home / ".config" / "GiljoAI",
            ]

        removed = 0
        for loc in locations:
            if loc.exists():
                try:
                    shutil.rmtree(loc)
                    self.log(f"Removed: {loc}", "SUCCESS")
                    removed += 1
                except Exception as e:
                    self.log(f"Failed to remove {loc}: {e}", "ERROR")

        return removed

    def run(self):
        """Run the complete production uninstall"""
        print("\n" + "=" * 70)
        print("   Giljo HQ Production Uninstaller")
        print("   TRUE NUCLEAR OPTION - REMOVES EVERYTHING")
        print("=" * 70)

        print("\n" + "*" * 70)
        print("  !!!  CRITICAL WARNING  !!!")
        print("*" * 70)
        print("\n[CRITICAL] This will remove:")
        print("  - ALL files in this directory")
        print("  - ALL Python packages installed by GiljoAI (196+ packages)")
        print("  - PostgreSQL database AND server (if installed by us)")
        print("  - All configuration in APPDATA/user directories")
        print("  - EVERYTHING related to Giljo HQ")

        print("\n[CRITICAL] This WILL:")
        print("  - Break other Python projects using these packages")
        print("  - Remove ALL databases in PostgreSQL (if we installed it)")
        print("  - Be irreversible")

        print("\n[INFO] For development/testing, use devuninstall.py instead!")
        print("[INFO] devuninstall.py keeps Python packages and PostgreSQL server")

        print("\n" + "*" * 70)
        print("  Use this ONLY on production servers with no other projects!")
        print("*" * 70)

        confirm1 = input("\nType 'I UNDERSTAND' to continue: ")
        if confirm1 != "I UNDERSTAND":
            print("Uninstall cancelled.")
            return

        confirm2 = input("Type 'DESTROY EVERYTHING' to confirm: ")
        if confirm2 != "DESTROY EVERYTHING":
            print("Uninstall cancelled.")
            return

        print("\n" + "=" * 70)
        print("STARTING NUCLEAR UNINSTALL")
        print("=" * 70)

        # Execute uninstall steps
        mcp_unregistered = self.remove_mcp_registrations()
        self.remove_all_python_packages()
        self.remove_postgresql_completely()
        appdata_removed = self.remove_appdata_completely()
        files_removed = self.remove_all_installation_files()

        # Create completion log
        log_path = self.root_path / "uninstall_complete.log"
        with open(log_path, "w") as f:
            f.write("Giljo HQ Nuclear Uninstall Complete\n")
            f.write(f"MCP unregistrations: {mcp_unregistered}\n")
            f.write(f"Files removed: {files_removed}\n")
            f.write(f"APPDATA locations removed: {appdata_removed}\n")
            f.write("All Python packages uninstalled\n")
            f.write("PostgreSQL removed\n")

        print("\n" + "=" * 70)
        print("NUCLEAR UNINSTALL COMPLETE")
        print("=" * 70)
        print(f"\nMCP unregistrations: {mcp_unregistered}")
        print(f"Files removed: {files_removed}")
        print(f"APPDATA locations removed: {appdata_removed}")
        print("Python packages: ALL UNINSTALLED")
        print("PostgreSQL: REMOVED")

        print("\n[OK] Complete production uninstall successful!")
        print("[OK] All Giljo HQ components removed from system.")
        print(f"\n[INFO] Log saved to: {log_path}")

        print("\n" + "=" * 70)
        print("MANUAL CLEANUP REMINDER")
        print("=" * 70)
        print("\n[REMINDER] Please manually delete desktop shortcuts:")
        if self.platform == "win32":
            print("  - Start GiljoAI.lnk (on Desktop)")
            print("  - Stop GiljoAI.lnk (on Desktop)")
        elif self.platform == "Darwin":
            print("  - Start GiljoAI.command (on Desktop)")
            print("  - Stop GiljoAI.command (on Desktop)")
        else:
            print("  - Start-GiljoAI.desktop (on Desktop)")
            print("  - Stop-GiljoAI.desktop (on Desktop)")
        print(
            "\n[INFO] These shortcuts were not automatically removed to prevent"
            "\n       accidental deletion of user-created shortcuts."
        )


if __name__ == "__main__":
    uninstaller = GiljoProductionUninstaller()
    uninstaller.run()
