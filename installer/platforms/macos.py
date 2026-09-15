# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import contextlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from colorama import Fore, Style

from .base import PlatformHandler


class MacOSPlatformHandler(PlatformHandler):

    @property
    def platform_name(self) -> str:
        return "macOS"

    def get_venv_python(self, venv_dir: Path) -> Path:
        return venv_dir / "bin" / "python"

    def get_venv_pip(self, venv_dir: Path) -> Path:
        return venv_dir / "bin" / "pip"

    def get_postgresql_scan_paths(self) -> List[Path]:
        paths = []

        homebrew_intel = Path("/usr/local/opt")
        if homebrew_intel.exists():
            for pg_dir in sorted(homebrew_intel.glob("postgresql@*"), reverse=True):
                psql_path = pg_dir / "bin" / "psql"
                paths.append(psql_path)

            generic_pg = homebrew_intel / "postgresql" / "bin" / "psql"
            paths.append(generic_pg)

        homebrew_arm = Path("/opt/homebrew/opt")
        if homebrew_arm.exists():
            for pg_dir in sorted(homebrew_arm.glob("postgresql@*"), reverse=True):
                psql_path = pg_dir / "bin" / "psql"
                paths.append(psql_path)

            generic_pg = homebrew_arm / "postgresql" / "bin" / "psql"
            paths.append(generic_pg)

        paths.extend(
            [
                Path("/usr/local/bin/psql"),
                Path("/opt/homebrew/bin/psql"),
            ]
        )

        postgres_app_base = Path("/Applications/Postgres.app/Contents/Versions")
        if postgres_app_base.exists():
            for version_dir in sorted(postgres_app_base.glob("*"), reverse=True):
                psql_path = version_dir / "bin" / "psql"
                paths.append(psql_path)

            latest_psql = postgres_app_base / "latest" / "bin" / "psql"
            paths.append(latest_psql)

        return paths

    def get_postgresql_install_guide(self, recommended_version: int = 18) -> str:
        return f"""
{Fore.CYAN}macOS PostgreSQL Installation:{Style.RESET_ALL}

{Fore.WHITE}Option 1 - Homebrew (Recommended):{Style.RESET_ALL}

  1. Install Homebrew (if not already installed):
     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  2. Install PostgreSQL {recommended_version}:
     brew install postgresql@{recommended_version}

  3. Start PostgreSQL service:
     brew services start postgresql@{recommended_version}

  4. Set postgres user password (if needed):
     psql postgres -c "ALTER USER postgres PASSWORD 'your_password';"

  5. Re-run this installer

{Fore.WHITE}Option 2 - Postgres.app:{Style.RESET_ALL}

  1. Download Postgres.app from:
     https://postgresapp.com/

  2. Move to Applications folder and launch

  3. Click "Initialize" to create default database

  4. Add to PATH (in ~/.zshrc or ~/.bash_profile):
     export PATH="/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"

  5. Re-run this installer

{Fore.WHITE}Option 3 - Official Installer:{Style.RESET_ALL}

  1. Download from:
     https://www.postgresql.org/download/macosx/

  2. Run the installer package

  3. Remember the postgres password

  4. Re-run this installer

{Fore.YELLOW}Note:{Style.RESET_ALL} Homebrew is recommended for easy version management and updates.
"""

    def supports_desktop_shortcuts(self) -> bool:
        return True

    def create_desktop_shortcuts(self, install_dir: Path, venv_dir: Path) -> Dict[str, Any]:
        try:
            desktop = Path.home() / "Desktop"
            shortcuts_created = []
            python_bin = str(venv_dir / "bin" / "python")
            startup_script = str(install_dir / "startup.py")

            start_sh = desktop / "GiljoAI MCP.command"
            start_sh.write_text(f'#!/bin/bash\ncd "{install_dir}"\n"{python_bin}" "{startup_script}" --verbose\n')
            start_sh.chmod(0o755)
            shortcuts_created.append(str(start_sh))

            stop_sh = desktop / "Stop GiljoAI.command"
            stop_sh.write_text(f'#!/bin/bash\ncd "{install_dir}"\n"{python_bin}" "{startup_script}" --stop\n')
            stop_sh.chmod(0o755)
            shortcuts_created.append(str(stop_sh))

            return {
                "success": True,
                "method": "command",
                "shortcuts_created": shortcuts_created,
                "message": f"Created {len(shortcuts_created)} desktop launchers",
            }

        except Exception as e:
            return {"success": False, "error": str(e), "message": f"Failed to create launchers: {e}"}

    def run_npm_command(self, cmd: List[str], cwd: Path, timeout: int = 300) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out", "timeout": timeout}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_network_ips(self) -> List[str]:
        with contextlib.suppress(Exception):
            import psutil

            ips = []
            for addresses in psutil.net_if_addrs().values():
                for addr in addresses:
                    if addr.family == 2:
                        ip = addr.address
                        if not ip.startswith("127.") and not ip.startswith("169.254."):
                            ips.append(ip)

            return sorted(set(ips))

        return []

    def welcome_screen(self) -> None:
        separator = "=" * 70

        print(f"\n{Fore.YELLOW}{Style.BRIGHT}{separator}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{Style.BRIGHT}  Giljo HQ - macOS Installer v3.0{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{Style.BRIGHT}{separator}{Style.RESET_ALL}\n")

        print(f"{Fore.CYAN}Welcome to Giljo HQ!{Style.RESET_ALL}")
        print(f"{Fore.CYAN}This installer will set up your coding orchestrator.{Style.RESET_ALL}\n")

        print(f"{Fore.WHITE}What will be installed:{Style.RESET_ALL}")
        print("  • PostgreSQL database (giljo_mcp)")
        print("  • Python dependencies (FastAPI, SQLAlchemy, etc.)")
        print("  • Configuration files (.env, config.yaml)")
        print("  • API server + Frontend dashboard")
        print("  • MCP server integration\n")

        macos_version = platform.mac_ver()[0]
        machine = platform.machine()

        if machine == "arm64":
            arch_info = "Apple Silicon (M1/M2/M3)"
        else:
            arch_info = "Intel"

        print(f"{Fore.YELLOW}Platform: macOS {macos_version} ({arch_info}){Style.RESET_ALL}")
        print(
            f"{Fore.YELLOW}Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}{Style.RESET_ALL}\n"
        )

    def get_platform_specific_warnings(self) -> List[str]:
        return []
