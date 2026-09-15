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


class LinuxPlatformHandler(PlatformHandler):

    @property
    def platform_name(self) -> str:
        return "Linux"

    def get_venv_python(self, venv_dir: Path) -> Path:
        return venv_dir / "bin" / "python"

    def get_venv_pip(self, venv_dir: Path) -> Path:
        return venv_dir / "bin" / "pip"

    def get_postgresql_scan_paths(self) -> List[Path]:
        paths = []

        paths.extend([Path("/usr/bin/psql"), Path("/usr/local/bin/psql")])

        pg_lib = Path("/usr/lib/postgresql")
        if pg_lib.exists():
            for version_dir in sorted(pg_lib.glob("*"), reverse=True):
                if version_dir.is_dir():
                    psql_path = version_dir / "bin" / "psql"
                    paths.append(psql_path)

        pgsql_base = Path("/usr")
        for version_dir in sorted(pgsql_base.glob("pgsql-*"), reverse=True):
            if version_dir.is_dir():
                psql_path = version_dir / "bin" / "psql"
                paths.append(psql_path)

        return paths

    def _detect_distribution(self) -> Dict[str, str]:
        with contextlib.suppress(Exception):
            return platform.freedesktop_os_release()
        return {"ID": "unknown", "VERSION_ID": "", "NAME": "Linux"}

    def get_postgresql_install_guide(self, recommended_version: int = 18) -> str:
        dist_info = self._detect_distribution()
        dist_id = dist_info.get("ID", "unknown")

        if dist_id in ["ubuntu", "debian"]:
            return self._get_ubuntu_install_guide(recommended_version)

        elif dist_id in ["fedora", "rhel", "centos"]:
            return self._get_fedora_install_guide(recommended_version)

        else:
            return self._get_generic_install_guide(recommended_version)

    def _get_ubuntu_install_guide(self, recommended_version: int) -> str:
        return f"""
{Fore.CYAN}Ubuntu/Debian PostgreSQL Installation:{Style.RESET_ALL}

  1. Add PostgreSQL repository:
     sudo apt-get update
     sudo apt-get install -y postgresql-common
     sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh

  2. Install PostgreSQL {recommended_version}:
     sudo apt-get update
     sudo apt-get install -y postgresql-{recommended_version}

  3. Start PostgreSQL service:
     sudo systemctl start postgresql
     sudo systemctl enable postgresql

  4. Set postgres user password:
     sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'your_password';"

  5. Re-run this installer

{Fore.YELLOW}Ubuntu Firewall Note:{Style.RESET_ALL} If accessing from other devices, configure UFW:
  sudo ufw allow 7272/tcp  # API port
  sudo ufw allow 7274/tcp  # Dashboard port
"""

    def _get_fedora_install_guide(self, recommended_version: int) -> str:
        return f"""
{Fore.CYAN}Fedora/RHEL PostgreSQL Installation:{Style.RESET_ALL}

  1. Install PostgreSQL {recommended_version}:
     sudo dnf install -y postgresql{recommended_version}-server

  2. Initialize database:
     sudo /usr/pgsql-{recommended_version}/bin/postgresql-{recommended_version}-setup initdb

  3. Start PostgreSQL service:
     sudo systemctl start postgresql-{recommended_version}
     sudo systemctl enable postgresql-{recommended_version}

  4. Set postgres user password:
     sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'your_password';"

  5. Re-run this installer

{Fore.YELLOW}Firewall Note:{Style.RESET_ALL} If accessing from other devices:
  sudo firewall-cmd --permanent --add-port=7272/tcp  # API
  sudo firewall-cmd --permanent --add-port=7274/tcp  # Dashboard
  sudo firewall-cmd --reload
"""

    def _get_generic_install_guide(self, recommended_version: int) -> str:
        return f"""
{Fore.CYAN}Generic Linux PostgreSQL Installation:{Style.RESET_ALL}

  1. Install PostgreSQL {recommended_version} using your package manager

  2. Start PostgreSQL service:
     sudo systemctl start postgresql
     sudo systemctl enable postgresql

  3. Set postgres user password:
     sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'your_password';"

  4. Re-run this installer

{Fore.YELLOW}Documentation:{Style.RESET_ALL}
  https://www.postgresql.org/download/linux/
"""

    def supports_desktop_shortcuts(self) -> bool:
        return True

    def create_desktop_shortcuts(self, install_dir: Path, venv_dir: Path) -> Dict[str, Any]:
        try:
            desktop_dir = Path.home() / ".local" / "share" / "applications"
            desktop_dir.mkdir(parents=True, exist_ok=True)

            shortcuts_created = []
            python_bin = str(venv_dir / "bin" / "python")
            startup_script = str(install_dir / "startup.py")

            main_desktop = desktop_dir / "giljoai-mcp.desktop"
            self._create_desktop_file(
                main_desktop,
                name="Giljo HQ",
                exec_path=f'"{python_bin}" "{startup_script}" --verbose',
                working_dir=install_dir,
                description="Start Giljo HQ (backend + frontend + browser)",
                terminal=True,
            )
            shortcuts_created.append(str(main_desktop))

            stop_desktop = desktop_dir / "giljoai-stop.desktop"
            self._create_desktop_file(
                stop_desktop,
                name="Stop GiljoAI",
                exec_path=f'"{python_bin}" "{startup_script}" --stop',
                working_dir=install_dir,
                description="Stop Giljo HQ services",
                terminal=True,
            )
            shortcuts_created.append(str(stop_desktop))

            for desktop_file in shortcuts_created:
                try:
                    subprocess.run(
                        ["gio", "set", desktop_file, "metadata::trusted", "true"], capture_output=True, timeout=5
                    )
                except (OSError, subprocess.SubprocessError):
                    continue

            return {
                "success": True,
                "method": "desktop",
                "shortcuts_created": shortcuts_created,
                "message": f"Created {len(shortcuts_created)} desktop launchers",
            }

        except Exception as e:
            return {"success": False, "error": str(e), "message": f"Failed to create desktop launchers: {e}"}

    def _create_desktop_file(
        self, path: Path, name: str, exec_path: str, working_dir: Path, description: str, terminal: bool = False
    ) -> None:
        terminal_str = "true" if terminal else "false"
        content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={name}
Comment={description}
Exec={exec_path}
Path={working_dir}
Terminal={terminal_str}
Categories=Development;
"""
        path.write_text(content)
        path.chmod(0o755)

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
        print(f"{Fore.YELLOW}{Style.BRIGHT}  Giljo HQ - Linux Installer v3.0{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{Style.BRIGHT}{separator}{Style.RESET_ALL}\n")

        print(f"{Fore.CYAN}Welcome to Giljo HQ!{Style.RESET_ALL}")
        print(f"{Fore.CYAN}This installer will set up your coding orchestrator.{Style.RESET_ALL}\n")

        print(f"{Fore.WHITE}What will be installed:{Style.RESET_ALL}")
        print("  • PostgreSQL database (giljo_mcp)")
        print("  • Python dependencies (FastAPI, SQLAlchemy, etc.)")
        print("  • Configuration files (.env, config.yaml)")
        print("  • API server + Frontend dashboard")
        print("  • MCP server integration\n")

        dist_info = self._detect_distribution()
        platform_info = f"Platform: Linux {platform.release()}"

        if dist_info.get("ID") == "ubuntu":
            ubuntu_version = dist_info.get("VERSION_ID", "")
            ubuntu_name = dist_info.get("NAME", "Ubuntu")
            platform_info = f"Platform: {ubuntu_name} {ubuntu_version} ({platform.machine()})"
            print(f"{Fore.GREEN}Ubuntu detected - installer optimized for your system{Style.RESET_ALL}")

        elif dist_info.get("ID") in ["fedora", "rhel", "centos"]:
            distro_name = dist_info.get("NAME", "Fedora/RHEL")
            distro_version = dist_info.get("VERSION_ID", "")
            platform_info = f"Platform: {distro_name} {distro_version} ({platform.machine()})"
            print(f"{Fore.GREEN}{distro_name} detected - installer optimized for your system{Style.RESET_ALL}")

        print(f"{Fore.YELLOW}{platform_info}{Style.RESET_ALL}")
        print(
            f"{Fore.YELLOW}Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}{Style.RESET_ALL}\n"
        )

    def get_platform_specific_warnings(self) -> List[str]:
        warnings = []

        dist_info = self._detect_distribution()

        if dist_info.get("ID") == "ubuntu":
            warnings.append(
                "Ubuntu UFW Firewall: If accessing from other devices, configure firewall rules. "
                "See docs/guides/FIREWALL_CONFIGURATION.md for details."
            )

        return warnings
