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


class WindowsPlatformHandler(PlatformHandler):

    @property
    def platform_name(self) -> str:
        return "Windows"

    def get_venv_python(self, venv_dir: Path) -> Path:
        return venv_dir / "Scripts" / "python.exe"

    def get_venv_pip(self, venv_dir: Path) -> Path:
        return venv_dir / "Scripts" / "pip.exe"

    def get_postgresql_scan_paths(self) -> List[Path]:
        paths = []

        program_files_locations = [Path("C:/Program Files/PostgreSQL"), Path("C:/Program Files (x86)/PostgreSQL")]

        for base in program_files_locations:
            if base.exists():
                for version_dir in sorted(base.glob("*"), reverse=True):
                    if version_dir.is_dir():
                        psql_path = version_dir / "bin" / "psql.exe"
                        paths.append(psql_path)

        return paths

    def get_postgresql_install_guide(self, recommended_version: int = 18) -> str:
        return f"""
{Fore.CYAN}Windows PostgreSQL Installation:{Style.RESET_ALL}

  1. Download PostgreSQL {recommended_version} from:
     https://www.postgresql.org/download/windows/

  2. Run the installer as Administrator

  3. During installation:
     • Remember the 'postgres' user password
     • Accept default port (5432)
     • Install to default location (C:\\Program Files\\PostgreSQL\\{recommended_version})

  4. After installation, re-run this installer

{Fore.YELLOW}Important:{Style.RESET_ALL} You will need the postgres password you set during installation.
"""

    def supports_desktop_shortcuts(self) -> bool:
        return True

    def create_desktop_shortcuts(self, install_dir: Path, venv_dir: Path) -> Dict[str, Any]:
        try:
            try:
                import win32com.client  # noqa: F401 — availability check

                result = self._create_shortcuts_win32com(install_dir, venv_dir)
                return result

            except ImportError:
                result = self._create_shortcuts_batch(install_dir, venv_dir)
                return result

        except Exception as e:
            return {"success": False, "error": str(e), "message": f"Failed to create shortcuts: {e}"}

    def _create_shortcuts_win32com(self, install_dir: Path, venv_dir: Path) -> Dict[str, Any]:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        desktop = Path(shell.SpecialFolders("Desktop"))

        shortcuts_created = []
        python_exe = str(venv_dir / "Scripts" / "python.exe")
        icons_dir = install_dir / "frontend" / "public"

        start_path = desktop / "GiljoAI MCP.lnk"
        start_shortcut = shell.CreateShortcut(str(start_path))
        start_shortcut.TargetPath = python_exe
        start_shortcut.Arguments = f'"{install_dir / "startup.py"}" --verbose'
        start_shortcut.WorkingDirectory = str(install_dir)
        start_ico = icons_dir / "Start.ico"
        if start_ico.exists():
            start_shortcut.IconLocation = str(start_ico)
        start_shortcut.Description = "Start Giljo HQ (backend + frontend + browser)"
        start_shortcut.save()
        shortcuts_created.append(str(start_path))

        stop_path = desktop / "Stop GiljoAI.lnk"
        stop_shortcut = shell.CreateShortcut(str(stop_path))
        stop_shortcut.TargetPath = python_exe
        stop_shortcut.Arguments = f'"{install_dir / "startup.py"}" --stop'
        stop_shortcut.WorkingDirectory = str(install_dir)
        stop_ico = icons_dir / "Stop.ico"
        if stop_ico.exists():
            stop_shortcut.IconLocation = str(stop_ico)
        stop_shortcut.Description = "Stop Giljo HQ services"
        stop_shortcut.save()
        shortcuts_created.append(str(stop_path))

        return {
            "success": True,
            "method": "win32com",
            "shortcuts_created": shortcuts_created,
            "message": f"Created {len(shortcuts_created)} desktop shortcuts",
        }

    def _create_shortcuts_batch(self, install_dir: Path, venv_dir: Path) -> Dict[str, Any]:
        desktop = Path.home() / "Desktop"
        shortcuts_created = []
        python_exe = str(venv_dir / "Scripts" / "python.exe")
        icons_dir = install_dir / "frontend" / "public"

        shortcuts = [
            {
                "name": "GiljoAI MCP.lnk",
                "args": f'"{install_dir / "startup.py"}" --verbose',
                "icon": icons_dir / "Start.ico",
                "desc": "Start Giljo HQ (backend + frontend + browser)",
            },
            {
                "name": "Stop GiljoAI.lnk",
                "args": f'"{install_dir / "startup.py"}" --stop',
                "icon": icons_dir / "Stop.ico",
                "desc": "Stop Giljo HQ services",
            },
        ]

        for sc in shortcuts:
            lnk_path = desktop / sc["name"]
            icon_loc = str(sc["icon"]) if sc["icon"].exists() else ""
            ps_script = (
                f"$ws = New-Object -ComObject WScript.Shell; "
                f'$s = $ws.CreateShortcut("{lnk_path}"); '
                f'$s.TargetPath = "{python_exe}"; '
                f"$s.Arguments = '{sc['args']}'; "
                f'$s.WorkingDirectory = "{install_dir}"; '
                f'$s.Description = "{sc["desc"]}"; '
            )
            if icon_loc:
                ps_script += f'$s.IconLocation = "{icon_loc}"; '
            ps_script += "$s.Save()"

            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                )
                shortcuts_created.append(str(lnk_path))
            except Exception as _exc:
                bat_path = desktop / sc["name"].replace(".lnk", ".bat")
                with open(bat_path, "w") as f:
                    f.write("@echo off\n")
                    f.write(f'cd /d "{install_dir}"\n')
                    f.write(f'"{python_exe}" {sc["args"]}\n')
                    f.write("pause\n")
                shortcuts_created.append(str(bat_path))

        return {
            "success": True,
            "method": "powershell",
            "shortcuts_created": shortcuts_created,
            "message": f"Created {len(shortcuts_created)} desktop shortcuts",
        }

    def run_npm_command(self, cmd: List[str], cwd: Path, timeout: int = 300) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                shell=True,
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
        print(f"{Fore.YELLOW}{Style.BRIGHT}  Giljo HQ - Windows Installer v3.0{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{Style.BRIGHT}{separator}{Style.RESET_ALL}\n")

        print(f"{Fore.CYAN}Welcome to Giljo HQ!{Style.RESET_ALL}")
        print(f"{Fore.CYAN}This installer will set up your coding orchestrator.{Style.RESET_ALL}\n")

        print(f"{Fore.WHITE}What will be installed:{Style.RESET_ALL}")
        print("  • PostgreSQL database (giljo_mcp)")
        print("  • Python dependencies (FastAPI, SQLAlchemy, etc.)")
        print("  • Configuration files (.env, config.yaml)")
        print("  • API server + Frontend dashboard")
        print("  • MCP server integration\n")

        windows_version = platform.win32_ver()[0] if hasattr(platform, "win32_ver") else platform.release()
        print(f"{Fore.YELLOW}Platform: Windows {windows_version}{Style.RESET_ALL}")
        print(
            f"{Fore.YELLOW}Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}{Style.RESET_ALL}\n"
        )

    def get_platform_specific_warnings(self) -> List[str]:
        return []
