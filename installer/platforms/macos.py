# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
macOS platform handler implementation.

Handles macOS-specific installation operations including:
- Virtual environment path resolution (bin/)
- PostgreSQL discovery (Homebrew Intel/ARM, Postgres.app)
- Desktop shortcuts (not currently supported, future: .app bundles)
- npm command execution with shell=False
"""

import contextlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from colorama import Fore, Style

from .base import PlatformHandler


class MacOSPlatformHandler(PlatformHandler):
    """
    macOS-specific platform handler.

    Key macOS behaviors:
    - venv executables in bin/ directory (POSIX)
    - PostgreSQL via Homebrew (Intel/ARM) or Postgres.app
    - No desktop shortcuts currently (future: .app bundles)
    - npm uses shell=False (direct execution)
    """

    @property
    def platform_name(self) -> str:
        """Return 'macOS'"""
        return "macOS"

    def get_venv_python(self, venv_dir: Path) -> Path:
        """
        Get macOS Python executable path.

        Args:
            venv_dir: Virtual environment directory

        Returns:
            Path to venv/bin/python (POSIX)
        """
        return venv_dir / "bin" / "python"

    def get_venv_pip(self, venv_dir: Path) -> Path:
        """
        Get macOS pip executable path.

        Args:
            venv_dir: Virtual environment directory

        Returns:
            Path to venv/bin/pip (POSIX)
        """
        return venv_dir / "bin" / "pip"

    def get_postgresql_scan_paths(self) -> List[Path]:
        """
        Get macOS PostgreSQL scan paths.

        Covers:
        - Homebrew Intel: /usr/local/opt/postgresql@*/bin/psql
        - Homebrew ARM (M1/M2): /opt/homebrew/opt/postgresql@*/bin/psql
        - Postgres.app: /Applications/Postgres.app/Contents/Versions/*/bin/psql
        - Standard paths: /usr/local/bin/psql

        Returns:
            List of potential psql paths (sorted by version, newest first)
        """
        paths = []

        # Homebrew Intel paths
        homebrew_intel = Path("/usr/local/opt")
        if homebrew_intel.exists():
            # Version-specific
            for pg_dir in sorted(homebrew_intel.glob("postgresql@*"), reverse=True):
                psql_path = pg_dir / "bin" / "psql"
                paths.append(psql_path)

            # Generic postgresql
            generic_pg = homebrew_intel / "postgresql" / "bin" / "psql"
            paths.append(generic_pg)

        # Homebrew ARM paths (M1/M2 Macs)
        homebrew_arm = Path("/opt/homebrew/opt")
        if homebrew_arm.exists():
            # Version-specific
            for pg_dir in sorted(homebrew_arm.glob("postgresql@*"), reverse=True):
                psql_path = pg_dir / "bin" / "psql"
                paths.append(psql_path)

            # Generic postgresql
            generic_pg = homebrew_arm / "postgresql" / "bin" / "psql"
            paths.append(generic_pg)

        # Standard Homebrew bin paths
        paths.extend(
            [
                Path("/usr/local/bin/psql"),  # Intel
                Path("/opt/homebrew/bin/psql"),  # ARM
            ]
        )

        # Postgres.app paths
        postgres_app_base = Path("/Applications/Postgres.app/Contents/Versions")
        if postgres_app_base.exists():
            # Check all versions
            for version_dir in sorted(postgres_app_base.glob("*"), reverse=True):
                psql_path = version_dir / "bin" / "psql"
                paths.append(psql_path)

            # Latest symlink
            latest_psql = postgres_app_base / "latest" / "bin" / "psql"
            paths.append(latest_psql)

        return paths

    def get_postgresql_install_guide(self, recommended_version: int = 18) -> str:
        """
        Get macOS PostgreSQL installation guide.

        Provides instructions for:
        - Homebrew (recommended)
        - Postgres.app
        - Official installer

        Args:
            recommended_version: Recommended version (default: 18)

        Returns:
            Multi-line installation instructions
        """
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
        """macOS supports shell script launchers on Desktop."""
        return True

    def create_desktop_shortcuts(self, install_dir: Path, venv_dir: Path) -> Dict[str, Any]:
        """
        Create macOS desktop launchers as executable shell scripts.

        Args:
            install_dir: Installation directory
            venv_dir: Virtual environment directory

        Returns:
            Result dictionary with success status
        """
        try:
            desktop = Path.home() / "Desktop"
            shortcuts_created = []
            python_bin = str(venv_dir / "bin" / "python")
            startup_script = str(install_dir / "startup.py")

            # Start script
            # BE-9361: frozen on-disk name (already shipped to users' desktops);
            # renaming it strands the existing launcher. Display text is rebranded.
            start_sh = desktop / "GiljoAI MCP.command"
            start_sh.write_text(f'#!/bin/bash\ncd "{install_dir}"\n"{python_bin}" "{startup_script}" --verbose\n')
            start_sh.chmod(0o755)
            shortcuts_created.append(str(start_sh))

            # Stop script
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
        """
        Run npm command with macOS-specific handling.

        macOS uses shell=False for direct execution (POSIX behavior).

        Args:
            cmd: Command list (e.g., ['npm', 'install'])
            cwd: Working directory
            timeout: Timeout in seconds

        Returns:
            Result dictionary with success status and output
        """
        try:
            # macOS uses shell=False (POSIX, direct execution)
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                shell=False,  # Direct execution for macOS
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
        """
        Get non-localhost IPv4 addresses on macOS.

        Returns:
            List of IPv4 address strings
        """
        with contextlib.suppress(Exception):
            import psutil

            ips = []
            for addresses in psutil.net_if_addrs().values():
                for addr in addresses:
                    if addr.family == 2:  # AF_INET (IPv4)
                        ip = addr.address
                        # Filter out localhost and link-local
                        if not ip.startswith("127.") and not ip.startswith("169.254."):
                            ips.append(ip)

            return sorted(set(ips))  # Deduplicate and sort

        return []

    def welcome_screen(self) -> None:
        """
        Print macOS-specific welcome screen.
        """
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

        # macOS platform info with architecture
        macos_version = platform.mac_ver()[0]
        machine = platform.machine()  # x86_64 or arm64

        # Detect Apple Silicon
        if machine == "arm64":
            arch_info = "Apple Silicon (M1/M2/M3)"
        else:
            arch_info = "Intel"

        print(f"{Fore.YELLOW}Platform: macOS {macos_version} ({arch_info}){Style.RESET_ALL}")
        print(
            f"{Fore.YELLOW}Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}{Style.RESET_ALL}\n"
        )

    def get_platform_specific_warnings(self) -> List[str]:
        """
        Get macOS-specific warnings.

        macOS firewall is user-friendly and prompts automatically,
        so no explicit warnings needed.

        Returns:
            Empty list (no warnings needed)
        """
        return []
