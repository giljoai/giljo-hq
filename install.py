#!/usr/bin/env python3

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Giljo HQ v3.0 - Unified Installer

Single-file installer that replaces the entire installer/cli/ system.
Handles cross-platform PostgreSQL discovery, dependency management,
database setup, config generation, and service launching.

Usage:
    python install.py              # Interactive installation
    python install.py --headless   # Non-interactive (CI/CD)
    python install.py --help       # Show help

Architecture:
    1. Welcome screen with yellow branding
    2. Check Python version (3.10+)
    3. Discover PostgreSQL (cross-platform)
    4. Install dependencies (venv + requirements.txt)
    5. Generate configs (.env + config.yaml v3.0) - BEFORE table creation!
    6. Setup database (create DB, roles, tables via DatabaseManager) - needs .env from step 5
    7. Launch services (API + Frontend)
    8. Open browser (http://localhost:7272)

Cross-platform: Windows, Linux, macOS
"""

import subprocess
import sys


def _bootstrap_dependencies():
    """Ensure click and colorama are available before main imports.

    This solves the bootstrap problem where install.py needs these packages
    to run, but is also responsible for installing them.

    On Ubuntu 24.04+, system Python is externally-managed (PEP 668),
    so we use --user flag when not inside a virtual environment.
    """
    required = ["click", "colorama"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if not missing:
        return

    print(f"Installing bootstrap dependencies: {', '.join(missing)}...")
    use_user = sys.prefix == sys.base_prefix  # Not in a venv

    cmd = [sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", *missing]
    if use_user:
        cmd.insert(5, "--user")

    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("\nERROR: Could not install bootstrap dependencies.")
        print("Please install manually:")
        print("  pip install click colorama")
        sys.exit(1)

    # After --user install, the packages may not be on sys.path yet.
    # Add the user site-packages directory so the import below succeeds.
    if use_user:
        import site

        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.insert(0, user_site)


_bootstrap_dependencies()

# Standard library imports
import atexit
import contextlib
import io
import logging
import os
import platform
import re
import shutil
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Third-party imports (safe after bootstrap)
import click
from colorama import Fore, Style, init

# BE-9060 mechanical split: the python-env, frontend(npm), and database phases
# of UnifiedInstaller moved verbatim into installer/core/ mixins. They remain
# regular methods of UnifiedInstaller via inheritance -- no behavior change,
# and instance-level monkeypatching in tests keeps working unchanged.
from installer.core.database_setup import DatabaseSetupMixin
from installer.core.frontend_setup import FrontendSetupMixin
from installer.core.python_env import PythonEnvSetupMixin

# Import unified platform handlers and core modules
from installer.platforms import get_platform_handler


# Initialize colorama for cross-platform colored output
init(autoreset=True)


# ---------------------------------------------------------------------------
# Install logger — writes to install.log in the working directory
# ---------------------------------------------------------------------------
_log_path = Path.cwd() / "install.log"
_logger = logging.getLogger("giljoai_install")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False
_file_handler = logging.FileHandler(_log_path, mode="a", encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_logger.addHandler(_file_handler)
_logger.info("=" * 60)
_logger.info("Giljo HQ Installer started")
_logger.info("=" * 60)

# Patterns that look like credentials — redact before writing to install.log
_SENSITIVE_PATTERNS = re.compile(r"(password|passwd|secret|token|key|credential)[=:\s]+\S+", re.IGNORECASE)


def _sanitize_log(text: str) -> str:
    """Redact potential credentials before writing to log file."""
    return _SENSITIVE_PATTERNS.sub(r"\1=***REDACTED***", text)


# ---------------------------------------------------------------------------
# TTY-aware input — reads from /dev/tty when stdin is piped (curl | bash)
# ---------------------------------------------------------------------------
_tty_file: io.TextIOWrapper | None = None
_tty_stack = contextlib.ExitStack()
atexit.register(_tty_stack.close)


def _get_tty() -> io.TextIOWrapper | None:
    """Open /dev/tty once and cache the handle."""
    global _tty_file  # noqa: PLW0603  # reason: cached TTY file handle deliberately module-scoped
    if _tty_file is not None:
        return _tty_file
    if sys.stdin.isatty():
        return None  # stdin is fine, no override needed
    try:
        _tty_file = _tty_stack.enter_context(open("/dev/tty"))  # noqa: SIM115
        return _tty_file
    except OSError:
        return None


def tty_input(prompt: str = "") -> str:
    """Drop-in replacement for input() that reads from /dev/tty when piped."""
    tty = _get_tty()
    if tty is None:
        # stdin is a real terminal — use normal input()
        result = input(prompt)
    else:
        # stdin is piped — print prompt to stderr (visible) and read from tty
        print(prompt, end="", flush=True)
        result = tty.readline().rstrip("\n")
    _logger.debug("User input for %r → %r", prompt.strip(), _sanitize_log(result))
    return result


# Constants
RECOMMENDED_POSTGRESQL_VERSION = 18
DEFAULT_API_PORT = 7272
DEFAULT_FRONTEND_PORT = 7274
POSTGRESQL_DOWNLOAD_URL = "https://www.postgresql.org/download/"


def getpass_with_asterisks(prompt: str = "Password: ") -> str:
    """Cross-platform password input that shows asterisks as user types.

    Works on Windows (msvcrt) and Unix/Linux/Mac (termios).

    Args:
        prompt: The prompt to display before password input

    Returns:
        The entered password as a string
    """
    print(prompt, end="", flush=True)
    password = []

    if platform.system() == "Windows":
        import msvcrt

        while True:
            char = msvcrt.getch()
            # Enter key
            if char in (b"\r", b"\n"):
                print()
                break
            # Backspace
            if char == b"\x08":
                if password:
                    password.pop()
                    # Move cursor back, overwrite with space, move back again
                    print("\b \b", end="", flush=True)
            # Ctrl+C
            elif char == b"\x03":
                raise KeyboardInterrupt
            # Regular character
            else:
                try:
                    password.append(char.decode("utf-8"))
                    print("*", end="", flush=True)
                except UnicodeDecodeError:
                    pass  # Ignore non-UTF8 characters
    else:
        # Unix/Linux/Mac — use /dev/tty if stdin is piped
        import termios
        import tty

        with contextlib.ExitStack() as stack:
            if sys.stdin.isatty():
                tty_stream = sys.stdin
            else:
                tty_stream = stack.enter_context(open("/dev/tty"))

            fd = tty_stream.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                while True:
                    char = tty_stream.read(1)
                    # Enter key
                    if char in ("\r", "\n"):
                        # Raw mode: \n only moves down, need \r to return to column 0
                        sys.stdout.write("\r\n")
                        sys.stdout.flush()
                        break
                    # Backspace (DEL or BS)
                    if char in ("\x7f", "\x08"):
                        if password:
                            password.pop()
                            print("\b \b", end="", flush=True)
                    # Ctrl+C
                    elif char == "\x03":
                        raise KeyboardInterrupt
                    # Regular character
                    else:
                        password.append(char)
                        print("*", end="", flush=True)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    return "".join(password)


class UnifiedInstaller(PythonEnvSetupMixin, FrontendSetupMixin, DatabaseSetupMixin):
    """
    Unified installer for Giljo HQ v3.0

    Handles complete installation workflow:
    - PostgreSQL discovery
    - Dependency management
    - Database setup
    - Configuration generation
    - Service launching
    """

    def __init__(self, settings: dict[str, Any] | None = None):
        """
        Initialize installer with settings

        Args:
            settings: Installation settings (defaults applied if not provided)
        """
        self.settings = settings or {}

        # Apply defaults
        self.settings.setdefault("install_dir", str(Path.cwd()))
        self.settings.setdefault("pg_host", "localhost")
        self.settings.setdefault("pg_port", 5432)
        self.settings.setdefault("api_port", DEFAULT_API_PORT)
        self.settings.setdefault("dashboard_port", DEFAULT_FRONTEND_PORT)
        # Bind address derived from network choice: localhost → 127.0.0.1, LAN/WAN → 0.0.0.0
        self.settings.setdefault("bind", "0.0.0.0")
        # INF-6241: CE installs always configure plain HTTP; HTTPS is an opt-in
        # bring-your-own-cert toggle in Settings -> Network (never set at install).
        self.settings.setdefault("ssl_enabled", False)

        # Initialize platform handler (auto-detects Windows/Linux/macOS)
        self.platform = get_platform_handler()

        # Paths
        self.install_dir = Path(self.settings["install_dir"])
        self.venv_dir = self.install_dir / "venv"
        self.requirements_file = self.install_dir / "requirements.txt"
        # INF-9057: requirements.txt carries human-readable >= floors; the
        # shipped requirements.lock pins the full resolved tree. Passing it as
        # a pip CONSTRAINTS file (-c) pins every package pip decides to
        # install without forcing platform-specific entries (a constraint for
        # a package that is not being installed, e.g. uvloop on Windows, is
        # simply ignored) — so one breaking upstream release can no longer
        # break fresh CE installs.
        self.constraints_file = self.install_dir / "requirements.lock"

        # State
        self.postgresql_found = False
        self.psql_path: Path | None = None
        self.venv_created = False
        self.database_credentials: dict[str, str] | None = None
        # True when discover_nodejs() winget/apt/brew-installed Node during
        # this run. Triggers an end-of-install "shell restart required"
        # notice so users don't hit "npm: WinError 2" on first startup.py
        # invocation in the same shell.
        self._node_freshly_installed = False

    def run(self) -> dict[str, Any]:
        """
        Execute complete installation workflow

        Returns:
            Result dictionary with success status and details
        """
        result = {"success": False, "steps": []}

        try:
            repair = self.settings.get("repair", False)
            # --repair re-runs setup idempotently to recover an interrupted install; it
            # implies --setup-only (skip prereqs/deps, just re-configure + re-seed).
            setup_only = self.settings.get("setup_only", False) or repair

            _logger.info(
                "Installation run started | Python %s.%s.%s | Platform: %s %s | setup_only=%s | repair=%s",
                sys.version_info.major,
                sys.version_info.minor,
                sys.version_info.micro,
                platform.system(),
                platform.release(),
                setup_only,
                repair,
            )

            if repair:
                self._print_header("Repair Mode")
                self._print_info("Re-running installation steps idempotently to recover an interrupted install.")

            # Step 1: Welcome screen
            self.welcome_screen()
            result["steps"].append("welcome_shown")

            # Step 1.5: Ask installation questions (NEW)
            if self.settings.get("unattended"):
                self._apply_unattended_settings()
                result["steps"].append("configuration_gathered")
                _logger.info(
                    "Unattended configuration applied | network_mode=%s | bind=%s | api_port=%s",
                    self.settings.get("network_mode", "unknown"),
                    self.settings.get("bind", "unknown"),
                    self.settings.get("api_port", "unknown"),
                )
            elif not self.settings.get("headless"):
                self._print_header("Installation Configuration")
                self.ask_installation_questions()
                result["steps"].append("configuration_gathered")
                _logger.info(
                    "User configuration gathered | network_mode=%s | bind=%s | api_port=%s",
                    self.settings.get("network_mode", "unknown"),
                    self.settings.get("bind", "unknown"),
                    self.settings.get("api_port", "unknown"),
                )

            if not setup_only:
                # Step 2: Check Python version
                self._print_header("Checking Python Version")
                if not self.check_python_version():
                    self._print_error("Python version check failed")
                    _logger.error("Python version check FAILED (requires 3.12+)")
                    result["error"] = "Python 3.12+ required"
                    return result
                result["steps"].append("python_verified")
                _logger.info(
                    "Python version OK: %s.%s.%s",
                    sys.version_info.major,
                    sys.version_info.minor,
                    sys.version_info.micro,
                )

                # Step 3: Discover PostgreSQL
                self._print_header("Discovering PostgreSQL")
                pg_result = self.discover_postgresql()
                if not pg_result["found"]:
                    self._print_error("PostgreSQL not found")
                    self._print_postgresql_install_guide()
                    _logger.error("PostgreSQL discovery FAILED")
                    result["error"] = "PostgreSQL 18 required"
                    return result
                result["steps"].append("postgresql_found")
                _logger.info(
                    "PostgreSQL discovered: version=%s path=%s",
                    pg_result.get("version", "unknown"),
                    _sanitize_log(str(pg_result.get("path", "unknown"))),
                )

                # Step 3.5: Discover Node.js (soft requirement for frontend)
                self._print_header("Discovering Node.js")
                node_result = self.discover_nodejs()
                if node_result["found"]:
                    result["steps"].append("nodejs_found")
                    _logger.info("Node.js discovered: version=%s", node_result.get("version", "unknown"))
                else:
                    self._print_warning("Continuing without Node.js - frontend will be unavailable")
                    _logger.warning("Node.js NOT found — frontend will be unavailable")

                # Step 4: Install dependencies
                self._print_header("Installing Dependencies")
                dep_result = self.install_dependencies()
                if not dep_result["success"]:
                    self._print_error("Dependency installation failed")
                    _logger.error("Dependency installation FAILED: %s", dep_result.get("error", "Unknown"))
                    result["error"] = dep_result.get("error", "Unknown error")
                    return result
                result["steps"].append("dependencies_installed")
                _logger.info("Dependencies installed successfully")

            # Step 4.5: resolve the real PostgreSQL port BEFORE anything writes it
            # down. Outside the `not setup_only` block on purpose: --repair and
            # --setup-only skip discovery but still rewrite .env/config.yaml, so
            # they must not re-stamp a wrong port. (INF-9321)
            self._print_header("Detecting PostgreSQL Port")
            _logger.info("PostgreSQL port resolved: %s", self.detect_postgresql_port())

            # Step 5: Generate configs (MUST happen before database setup!)
            # Table creation in step 6 needs .env file with DATABASE_URL
            self._print_header("Generating Configuration Files")
            config_result = self.generate_configs()
            if not config_result["success"]:
                self._print_error("Configuration generation failed")
                _logger.error("Config generation FAILED: %s", "; ".join(config_result.get("errors", ["Unknown"])))
                result["error"] = "; ".join(config_result.get("errors", ["Unknown error"]))
                return result
            result["steps"].append("configs_generated")
            _logger.info("Configuration files generated (config.yaml)")

            # Step 6: Setup database (create DB, roles, tables, admin user, setup_state)
            self._print_header("Setting Up Database")
            db_result = self.setup_database()
            if not db_result["success"]:
                self._print_error("Database setup failed")
                result["error"] = "; ".join(db_result.get("errors", ["Unknown error"]))
                return result
            self.database_credentials = db_result.get("credentials", {})
            result["steps"].append("database_created")
            result["steps"].append("tables_created")  # Added by inline table creation
            _logger.info("Database setup completed successfully")

            # Step 6.5: Run Alembic migrations (CRITICAL - applies constraints & backfills)
            self._print_header("Applying Database Migrations")
            migration_result = self.run_database_migrations()
            if not migration_result["success"]:
                # A failed migration means the schema cannot be trusted and
                # startup.py will hit the identical failure on first boot.
                # Fail the install loudly (non-zero exit) instead of printing
                # a false "Installation Complete!" over a wedged database
                # (INF-9113: the old "continue - manual migration may be
                # required" swallow shipped unusable installs as successes).
                self._print_error("Database migration failed - installation cannot continue")
                self._print_error(f"Error: {migration_result.get('error', 'Unknown error')}")
                _logger.error(
                    "Migration FAILED: %s",
                    _sanitize_log(str(migration_result.get("error", "Unknown"))),
                )
                result["error"] = migration_result.get("error", "Unknown migration error")
                return result

            _logger.info("Database migrations applied successfully")
            result["steps"].append("migrations_applied")

            # Demo data seeding happens inside setup_database() — no duplicate call here

            if not setup_only:
                # Step 7: Install frontend dependencies
                self._print_header("Installing Frontend Dependencies")
                frontend_result = self.install_frontend_dependencies()
                if not frontend_result["success"] and not frontend_result.get("skipped", False):
                    self._print_error("Frontend dependency installation failed")
                    _logger.error(
                        "Frontend dependency install FAILED: %s",
                        frontend_result.get("error", "Unknown"),
                    )
                    result["error"] = frontend_result.get("error", "Frontend dependencies failed")
                    return result
                result["steps"].append("frontend_dependencies_installed")
                _logger.info(
                    "Frontend dependencies: %s",
                    "installed" if frontend_result["success"] else "skipped",
                )

                # Step 7.1: Production / Development mode prompt
                if frontend_result["success"] and not frontend_result.get("skipped", False):
                    self._prompt_frontend_mode()

            if not setup_only and self.settings.get("create_shortcuts", False):
                # Step 8: Create desktop shortcuts (if requested - Windows only)
                self._print_header("Creating Desktop Shortcuts")
                self.create_desktop_shortcuts()
                result["steps"].append("shortcuts_created")

            # Step 8.5: SaaS-only Redis provisioning
            # Only runs when GILJO_MODE=saas; CE paths are byte-identical to before.
            import os as _os

            if _os.environ.get("GILJO_MODE") == "saas":
                self._print_header("SaaS Redis Provisioning")
                redis_result = self._provision_saas_redis()
                if redis_result.get("success"):
                    result["steps"].append("saas_redis_provisioned")
                else:
                    self._print_warning(
                        f"Redis provisioning incomplete: {redis_result.get('error', 'unknown')}. "
                        "Start Redis manually and ensure REDIS_URL is set before starting the server."
                    )

            # Success
            result["success"] = True
            self._print_success_summary()
            _logger.info("=" * 60)
            _logger.info("Installation status: SUCCESS")
            _logger.info("Steps completed: %s", ", ".join(result["steps"]))
            _logger.info("=" * 60)

            return result

        except KeyboardInterrupt:
            self._print_warning("\nInstallation cancelled by user")
            result["error"] = "User cancelled"
            _logger.warning("Installation CANCELLED by user (KeyboardInterrupt)")
            return result

        except Exception as e:
            self._print_error(f"Installation failed: {e}")
            result["error"] = str(e)
            _logger.exception("Installation status: FAILED | Error: %s", _sanitize_log(str(e)))  # noqa: TRY401  # reason: sanitized error preserved for log searchability alongside traceback
            return result

    def welcome_screen(self) -> None:
        """Display welcome screen with yellow branding"""
        separator = "=" * 70

        print(f"\n{Fore.YELLOW}{Style.BRIGHT}{separator}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{Style.BRIGHT}  Giljo HQ - Unified Installer v3.0{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{Style.BRIGHT}{separator}{Style.RESET_ALL}\n")

        print(f"{Fore.CYAN}Welcome to Giljo HQ, a GiljoAI product!{Style.RESET_ALL}")
        print(f"{Fore.CYAN}This installer will set up your coding orchestrator.{Style.RESET_ALL}\n")

        print(f"{Fore.WHITE}What will be installed:{Style.RESET_ALL}")
        db_display = self.settings.get("db_name", "giljo_mcp")
        print(f"  • PostgreSQL database setup ({db_display})")  # CodeQL: db_name is not sensitive
        print("  • Python dependencies (FastAPI, SQLAlchemy, etc.)")
        print("  • Configuration files (.env, config.yaml)")
        print("  • API server + Frontend dashboard")
        print("  • MCP server integration\n")

        print(f"{Fore.YELLOW}Platform: {platform.system()} {platform.release()}{Style.RESET_ALL}")
        print(
            f"{Fore.YELLOW}Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}{Style.RESET_ALL}\n"
        )

    def _apply_unattended_settings(self) -> None:
        """Populate installation settings from environment variables.

        Activated by GILJO_UNATTENDED=1 (set in main()). This is the no-TTY
        counterpart to ask_installation_questions() — it reads the same choices
        from the environment instead of prompting, so install.sh / install.ps1
        and CI/automation can drive a full install without a console.

        Environment contract:
            GILJO_NETWORK_MODE   "localhost" (default) | "lan" | "wan" | "auto"
                                 ("lan-http" accepted as a deprecated alias for "lan")
            GILJO_PG_PASSWORD    PostgreSQL admin password — REQUIRED, no default
            GILJO_DB_NAME        database name (default "giljo_mcp")

        INF-6241: every non-localhost mode configures plain HTTP and binds
        0.0.0.0. HTTPS is an opt-in bring-your-own-cert upgrade in
        Settings → Network after install.
        """
        self._print_header("Installation Configuration (unattended)")

        mode = (os.environ.get("GILJO_NETWORK_MODE") or "localhost").strip().lower()
        if mode in ("lan-http", "lan", "wan", "auto"):
            # LAN/WAN: bind all interfaces, auto-detect external IP, always plain HTTP.
            from installer.shared.network import get_network_adapters, is_private_lan_host

            adapters = get_network_adapters()
            if adapters:
                best = adapters[0]
                self.settings["external_host"] = best["ip"]
                self.settings["selected_adapter"] = best["name"]
                self.settings["initial_ip"] = best["ip"]
            else:
                self.settings["external_host"] = "localhost"
            # network_mode "auto" => re-detect IP each startup (matches interactive)
            self.settings["network_mode"] = "auto"
            self.settings["bind"] = "0.0.0.0"
            host = self.settings["external_host"]
            if is_private_lan_host(host):
                self._print_info(f"Unattended LAN mode — bind 0.0.0.0, host {host} (plain HTTP)")
                self._print_cleartext_lan_notice(host)
            else:
                self._print_info(f"Unattended WAN mode — bind 0.0.0.0, host {host} (plain HTTP)")
                self._print_cleartext_wan_notice(host)
        else:
            self.settings["external_host"] = "localhost"
            self.settings["network_mode"] = "localhost"
            self.settings["bind"] = "127.0.0.1"
            self._print_info("Unattended localhost mode — HTTP, bind 127.0.0.1")

        # PostgreSQL password — required, never defaulted.
        pg_password = self.settings.get("pg_password") or os.environ.get("GILJO_PG_PASSWORD")
        if not pg_password:
            raise ValueError(
                "Unattended install requires a PostgreSQL password. Set GILJO_PG_PASSWORD (or pass --pg-password)."
            )
        self.settings["pg_password"] = pg_password

        # On Linux/macOS the interactive path sets the postgres account password
        # via local peer auth. Mirror that (best-effort — if it fails the password
        # is assumed to be the already-configured one).
        if platform.system() != "Windows":
            try:
                self._set_postgres_password_via_peer(pg_password)
            except Exception as exc:  # pragma: no cover - defensive
                self._print_warning(f"Could not set postgres password via peer auth: {exc}")

        # Database name (default giljo_mcp).
        self.settings.setdefault("db_name", os.environ.get("GILJO_DB_NAME") or "giljo_mcp")

        # Non-interactive defaults (mirror the tail of ask_installation_questions).
        self.settings["register_mcp_tools"] = False
        self.settings["enable_serena"] = False
        self.settings["create_shortcuts"] = False

    def _print_cleartext_lan_notice(self, host: str) -> None:
        """Loud, repeated warning that LAN traffic is unencrypted over plain HTTP.

        INF-6236: HTTP-on-LAN sends the login password, the auth cookie, the CSRF
        token and any MCP API keys across the LAN in cleartext. Acceptable only on
        a trusted single-room network behind a trusted router, never port-forwarded.
        """
        print(f"\n{Fore.YELLOW}{'=' * 64}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}  CLEARTEXT ON YOUR LAN — read this{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{'=' * 64}{Style.RESET_ALL}")
        print(f"  The server will serve plain HTTP on http://{host} (no encryption).")
        print("  Login password, auth cookie, CSRF token and any MCP API keys")
        print("  travel your LAN in CLEARTEXT — a rogue device on the network can")
        print("  sniff them. Acceptable on a trusted home/single-room LAN behind a")
        print("  trusted router. Do NOT port-forward this box to the internet.")
        print("  Enable HTTPS anytime in Settings > Network (bring your own cert).")
        print(f"{Fore.YELLOW}{'=' * 64}{Style.RESET_ALL}")

    def _print_cleartext_wan_notice(self, host: str) -> None:
        """Warning that a public/WAN address with plain HTTP is unsafe."""
        print(f"\n{Fore.RED}{'=' * 64}{Style.RESET_ALL}")
        print(f"{Fore.RED}  PUBLIC / WAN ADDRESS — PLAIN HTTP IS NOT SAFE HERE{Style.RESET_ALL}")
        print(f"{Fore.RED}{'=' * 64}{Style.RESET_ALL}")
        print(f"  The server will serve plain HTTP on http://{host}. On a public or")
        print("  internet-facing address this sends logins and data in cleartext.")
        print("  Before exposing it, put a TLS-terminating reverse proxy or tunnel in")
        print("  front of it (nginx, Caddy, Cloudflare Tunnel), or add your own")
        print("  certificate later in Settings > Network. Continuing with HTTP.")
        print(f"{Fore.RED}{'=' * 64}{Style.RESET_ALL}")

    def ask_installation_questions(self) -> None:
        """Gather user preferences for installation"""
        # Network Configuration
        print(f"\n{Fore.CYAN}[Network Configuration]{Style.RESET_ALL}")
        print("The server runs over plain HTTP by default (localhost or LAN).")
        print("HTTPS is an opt-in upgrade in Settings > Network (bring your own cert).")
        print("Choose your installation:\n")

        # Detect network adapters (with names for tracking)
        from installer.shared.network import get_network_adapters, is_private_lan_host

        network_adapters = get_network_adapters()

        # Build options list — localhost first (the fork), then LAN/WAN options
        print(f"  {Fore.CYAN}Localhost access:{Style.RESET_ALL}")
        print(f"  1. {Fore.WHITE}Localhost only{Style.RESET_ALL} (HTTP, this machine only)")

        print(f"\n  {Fore.CYAN}LAN access (HTTP — no certificates):{Style.RESET_ALL}")
        print(f"  2. {Fore.GREEN}Auto-detect (recommended){Style.RESET_ALL}")
        print("     → Dynamically detects IP on each startup")

        # Add detected adapters with their IPs
        for i, adapter in enumerate(network_adapters, 3):
            virtual_tag = " (virtual)" if adapter.get("is_virtual") else ""
            print(f"  {i}. {adapter['ip']} [{adapter['name']}{virtual_tag}]")

        # Add custom option
        custom_option = len(network_adapters) + 3
        print(f"  {custom_option}. Enter custom address (domain or IP)")

        # Get user choice
        while True:
            choice = tty_input(f"\n{Fore.YELLOW}Select installation type [1]: {Style.RESET_ALL}").strip()

            if not choice or choice == "1":
                # Localhost mode — bind 127.0.0.1 (HTTP only, no HTTPS needed)
                self.settings["external_host"] = "localhost"
                self.settings["network_mode"] = "localhost"
                self.settings["bind"] = "127.0.0.1"
                self._print_info("Localhost only — HTTP, bind 127.0.0.1")
                break

            try:
                choice_num = int(choice)
                if choice_num == 2:
                    # Auto-detect mode — always plain HTTP.
                    if network_adapters:
                        best_adapter = network_adapters[0]
                        self.settings["external_host"] = best_adapter["ip"]
                        self.settings["network_mode"] = "auto"
                        self.settings["bind"] = "0.0.0.0"
                        self.settings["selected_adapter"] = best_adapter["name"]
                        self.settings["initial_ip"] = best_adapter["ip"]
                        self._print_success(f"Auto-detect mode: Using {best_adapter['name']} ({best_adapter['ip']})")
                        self._print_info("IP will be re-detected on each server startup")
                        if is_private_lan_host(best_adapter["ip"]):
                            self._print_cleartext_lan_notice(best_adapter["ip"])
                        else:
                            self._print_cleartext_wan_notice(best_adapter["ip"])
                    else:
                        self.settings["external_host"] = "localhost"
                        self.settings["network_mode"] = "localhost"
                        self.settings["bind"] = "127.0.0.1"
                        self._print_warning("No network adapters detected, falling back to localhost")
                    break
                if 3 <= choice_num < custom_option:
                    # Specific adapter selected — always plain HTTP.
                    selected = network_adapters[choice_num - 3]
                    self.settings["external_host"] = selected["ip"]
                    self.settings["network_mode"] = "static"
                    self.settings["bind"] = "0.0.0.0"
                    self.settings["selected_adapter"] = selected["name"]
                    self.settings["initial_ip"] = selected["ip"]
                    self._print_success(f"Using {selected['ip']} [{selected['name']}]")
                    if is_private_lan_host(selected["ip"]):
                        self._print_cleartext_lan_notice(selected["ip"])
                    else:
                        self._print_cleartext_wan_notice(selected["ip"])
                    break
                if choice_num == custom_option:
                    custom_addr = tty_input(
                        f"{Fore.YELLOW}Enter custom address (IP or domain): {Style.RESET_ALL}"
                    ).strip()
                    if custom_addr:
                        self.settings["external_host"] = custom_addr
                        self.settings["network_mode"] = "custom"
                        self.settings["bind"] = "0.0.0.0"
                        self._print_success(f"Using {custom_addr}")
                        if is_private_lan_host(custom_addr):
                            self._print_cleartext_lan_notice(custom_addr)
                        else:
                            self._print_cleartext_wan_notice(custom_addr)
                        break
                    self._print_warning("Empty address provided")
                else:
                    self._print_warning(f"Invalid choice. Please select 1-{custom_option}")
            except ValueError:
                self._print_warning(f"Invalid input. Please enter a number 1-{custom_option}")

        # PostgreSQL password (with verification)
        print(f"\n{Fore.CYAN}[PostgreSQL Configuration]{Style.RESET_ALL}")

        if platform.system() == "Windows":
            # Windows: PostgreSQL installer already set a password
            print(f"\n{Fore.WHITE}PostgreSQL Admin Password Required{Style.RESET_ALL}")
            print("This is the password for the 'postgres' superuser account")
            print("(The password you set when you first installed PostgreSQL)")
            print(f"{Fore.RED}Required - no defaults allowed{Style.RESET_ALL}")

            max_attempts = 3
            for attempt in range(max_attempts):
                pg_pass = getpass_with_asterisks(f"{Fore.YELLOW}Password: {Style.RESET_ALL}")
                if not pg_pass:
                    self._print_error("Password cannot be empty.")
                    continue
                pg_pass_confirm = getpass_with_asterisks(f"{Fore.YELLOW}Confirm password: {Style.RESET_ALL}")
                if pg_pass == pg_pass_confirm:
                    self.settings["pg_password"] = pg_pass
                    self._print_success("Password confirmed")
                    break
                remaining = max_attempts - attempt - 1
                if remaining > 0:
                    self._print_error(f"Passwords do not match. {remaining} attempt(s) remaining.")
                else:
                    raise ValueError("PostgreSQL password required for installation")
        else:
            # Linux/macOS: PostgreSQL likely has no TCP password set
            # Try to set one automatically via peer/trust auth
            print(f"\n{Fore.WHITE}PostgreSQL Password Setup{Style.RESET_ALL}")
            print("Setting up a password for the PostgreSQL 'postgres' account...")
            print(f"{Fore.RED}Required - no defaults allowed{Style.RESET_ALL}")

            max_attempts = 3
            for attempt in range(max_attempts):
                pg_pass = getpass_with_asterisks(f"{Fore.YELLOW}Choose a PostgreSQL password: {Style.RESET_ALL}")
                if not pg_pass:
                    self._print_error("Password cannot be empty.")
                    continue
                pg_pass_confirm = getpass_with_asterisks(f"{Fore.YELLOW}Confirm password: {Style.RESET_ALL}")
                if pg_pass != pg_pass_confirm:
                    remaining = max_attempts - attempt - 1
                    if remaining > 0:
                        self._print_error(f"Passwords do not match. {remaining} attempt(s) remaining.")
                        continue
                    raise ValueError("PostgreSQL password required for installation")

                # Try setting the password via peer auth (local socket)
                if self._set_postgres_password_via_peer(pg_pass):
                    self.settings["pg_password"] = pg_pass
                    self._print_success("PostgreSQL password set and confirmed")
                    break
                # Peer auth failed — maybe user already set a password manually
                print(f"\n{Fore.YELLOW}Could not set password automatically.{Style.RESET_ALL}")
                print("If you already set a PostgreSQL password, enter it now.")
                pg_pass = getpass_with_asterisks(f"{Fore.YELLOW}Existing password: {Style.RESET_ALL}")
                if pg_pass:
                    self.settings["pg_password"] = pg_pass
                    self._print_success("Password accepted")
                    break
                self._print_error("Password cannot be empty.")
            else:
                raise ValueError("PostgreSQL password required for installation")

        # Database name (allows multiple installations on same PostgreSQL)
        print(f"\n{Fore.CYAN}[Database Name]{Style.RESET_ALL}")
        print(f"Default database name is {Fore.WHITE}giljo_mcp{Style.RESET_ALL}.")
        print("Change this if you run multiple installations on the same PostgreSQL server.")
        print(f"{Fore.WHITE}Press Enter to accept the default, or type a new name.{Style.RESET_ALL}")
        db_name_input = tty_input(f"{Fore.YELLOW}Database name [giljo_mcp]: {Style.RESET_ALL}").strip()
        if db_name_input:
            self.settings["db_name"] = db_name_input
            self._print_info(f"Database name: {db_name_input}")
        else:
            self.settings["db_name"] = "giljo_mcp"

        # REMOVED: Start services prompt - services will not auto-start

        # REMOVED: Database table creation prompt - table creation is now MANDATORY

        # Set defaults for MCP and Serena (will be configured in setup wizard)
        self.settings["register_mcp_tools"] = False
        self.settings["enable_serena"] = False

        # Create desktop shortcuts
        if platform.system() == "Windows":
            print(f"\n{Fore.CYAN}[Post-Installation Options]{Style.RESET_ALL}")
            print("Would you like to create desktop shortcuts?")
            shortcuts_response = tty_input(f"{Fore.YELLOW}Create shortcuts? (Y/n): {Style.RESET_ALL}").strip().lower()
            self.settings["create_shortcuts"] = shortcuts_response != "n"
        else:
            self.settings["create_shortcuts"] = False

        # Summary
        print(f"\n{Fore.GREEN}Configuration Summary:{Style.RESET_ALL}")
        network_mode = self.settings.get("network_mode", "localhost")
        if network_mode == "auto":
            adapter = self.settings.get("selected_adapter", "unknown")
            print(
                f"  • Network mode: {Fore.GREEN}Auto-detect{Style.RESET_ALL} ({adapter})"
            )  # CodeQL: adapter name is not sensitive
            print("    → IP will be re-detected on each startup")
        elif network_mode == "static":
            adapter = self.settings.get("selected_adapter", "")
            print(f"  • Network mode: Static [{adapter}]")  # CodeQL: adapter name is not sensitive
        else:
            print(f"  • Network mode: {network_mode}")  # CodeQL: network_mode is not sensitive
        print(
            f"  • External access host: {self.settings.get('external_host', 'localhost')}"
        )  # CodeQL: hostname is not sensitive
        print(f"  • PostgreSQL password: {'*' * 8} (secured)")
        db_name = self.settings.get("db_name", "giljo_mcp")
        if db_name != "giljo_mcp":
            print(
                f"  • Database name: {Fore.YELLOW}{db_name}{Style.RESET_ALL} (custom)"
            )  # CodeQL: db_name is not sensitive
        if platform.system() == "Windows":
            print(
                f"  • Create shortcuts: {self.settings['create_shortcuts']}"
            )  # CodeQL: shortcut setting is not sensitive

    def discover_postgresql(self) -> dict[str, Any]:
        """
        Discover PostgreSQL installation across platforms

        Checks:
        1. psql in PATH
        2. Platform-specific common locations
        3. User-provided custom path (if auto-discovery fails)

        Returns:
            Discovery result with found status and paths
        """
        result = {"found": False, "psql_path": None, "scanned_paths": []}

        # Method 1: Check PATH
        self._print_info("Checking PATH for psql...")
        psql_path = shutil.which("psql")

        if psql_path:
            self._print_success(f"PostgreSQL detected in PATH: {psql_path}")
            result["found"] = True
            result["psql_path"] = psql_path
            self.psql_path = Path(psql_path)
            self.postgresql_found = True

            # Store PostgreSQL paths in settings for config.yaml persistence
            psql_path_obj = Path(psql_path)
            self.settings["postgresql_psql_path"] = str(psql_path_obj)
            self.settings["postgresql_bin_path"] = str(psql_path_obj.parent)
            self.settings["postgresql_installation_path"] = (
                str(psql_path_obj.parent.parent) if psql_path_obj.parent.name == "bin" else str(psql_path_obj.parent)
            )
            self.settings["postgresql_discovered_at"] = datetime.now(UTC).isoformat()
            self.settings["postgresql_custom_path"] = False
            self.settings["postgresql_discovery_method"] = "PATH"

            return result

        # Method 2: Scan platform-specific locations
        self._print_info("Scanning common installation locations...")
        scan_paths = self._get_postgresql_scan_paths()

        for path in scan_paths:
            result["scanned_paths"].append(str(path))
            print(f"{Fore.WHITE}  Checking: {path}{Style.RESET_ALL}")

            if path.exists():
                self._print_success(f"PostgreSQL detected: {path}")
                result["found"] = True
                result["psql_path"] = str(path)
                self.psql_path = path
                self.postgresql_found = True

                # Store PostgreSQL paths in settings for config.yaml persistence
                bin_dir = path.parent
                self.settings["postgresql_psql_path"] = str(path)
                self.settings["postgresql_bin_path"] = str(bin_dir)
                self.settings["postgresql_installation_path"] = (
                    str(bin_dir.parent) if bin_dir.name == "bin" else str(bin_dir)
                )
                self.settings["postgresql_discovered_at"] = datetime.now(UTC).isoformat()
                self.settings["postgresql_custom_path"] = False
                self.settings["postgresql_discovery_method"] = "COMMON_LOCATION"

                # Add to PATH for session
                os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

                return result

        # Method 3: Ask for custom path
        self._print_warning("PostgreSQL not found in common locations")

        # Skip prompt in headless / unattended mode
        if self.settings.get("headless") or self.settings.get("unattended"):
            return result

        print(f"\n{Fore.YELLOW}Do you have PostgreSQL installed at a custom location? (y/n): {Style.RESET_ALL}", end="")
        response = tty_input().strip().lower()

        if response not in ["y", "yes"]:
            return result

        # Prompt for custom path (max 3 attempts)
        max_attempts = 3
        for attempt in range(max_attempts):
            print(f"\n{Fore.YELLOW}Enter the full path to your PostgreSQL bin directory{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Example: C:\\custom\\postgres\\bin or /opt/custom/postgres/bin{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Path: {Style.RESET_ALL}", end="")

            custom_path = tty_input().strip()

            if not custom_path:
                self._print_warning("Empty path provided")
                continue

            # Validate custom path
            if self.check_custom_postgresql_path(custom_path):
                # Custom path is valid
                if self.platform.platform_name == "Windows":
                    psql_path = Path(custom_path) / "psql.exe"
                else:
                    psql_path = Path(custom_path) / "psql"

                result["found"] = True
                result["psql_path"] = str(psql_path)
                self.psql_path = psql_path
                self.postgresql_found = True

                # Store PostgreSQL paths in settings for config.yaml persistence
                custom_path_obj = Path(custom_path)
                self.settings["postgresql_psql_path"] = str(psql_path)
                self.settings["postgresql_bin_path"] = str(custom_path_obj)
                self.settings["postgresql_installation_path"] = (
                    str(custom_path_obj.parent) if custom_path_obj.name == "bin" else str(custom_path_obj)
                )
                self.settings["postgresql_discovered_at"] = datetime.now(UTC).isoformat()
                self.settings["postgresql_custom_path"] = True
                self.settings["postgresql_discovery_method"] = "CUSTOM"

                # Add to PATH for session
                os.environ["PATH"] = f"{custom_path}{os.pathsep}{os.environ['PATH']}"

                return result

            # Invalid path - show remaining attempts
            remaining = max_attempts - attempt - 1
            if remaining > 0:
                self._print_warning(f"Invalid path. {remaining} attempt(s) remaining.")
            else:
                self._print_error("Maximum attempts exceeded.")

        # All attempts failed
        return result

    def discover_nodejs(self) -> dict[str, Any]:
        """
        Discover Node.js and npm installation across platforms

        This is a soft requirement - installation continues even if Node.js is
        not found, but frontend functionality will be unavailable.

        Checks:
        1. node and npm in PATH
        2. Attempt auto-install on Linux/macOS if missing
        3. Prompt user before auto-installing (unless headless mode)

        Returns:
            Discovery result with found status: {"found": bool}
        """
        result: dict[str, Any] = {"found": False}

        # Check if node and npm are already available
        node_path = shutil.which("node")
        npm_path = shutil.which("npm")

        if node_path and npm_path:
            self._print_success(f"Node.js detected: {node_path} ({self._get_node_version()})")
            self._print_success(f"npm detected: {npm_path}")
            result["found"] = True
            return result

        # Node.js not found - attempt auto-install based on platform
        self._print_warning("Node.js / npm not found in PATH")

        platform_name = self.platform.platform_name

        # Linux or macOS - offer auto-install
        # Unattended installs skip the y/n prompt and proceed to auto-install.
        headless = self.settings.get("headless") or self.settings.get("unattended")

        if platform_name == "Windows":
            # Mirror the Linux/macOS auto-install pattern: detect winget,
            # prompt the user (unless headless), winget-install Node LTS,
            # refresh PATH from registry so the shutil.which() re-check
            # below succeeds without requiring a new shell.
            #
            # Prior to this branch, Windows users running `python install.py`
            # standalone (clone-and-run) hit a hard dead-end: the script
            # printed "Please install Node.js from https://nodejs.org/" and
            # fell back to backend-only. install.ps1 (one-liner path) DID
            # winget-install Node, leaving the standalone path asymmetric
            # vs Linux (NodeSource auto-install) and macOS (Homebrew
            # auto-install).
            winget_path = shutil.which("winget")
            if not winget_path:
                self._print_info(
                    "Please install Node.js from https://nodejs.org/ "
                    "(winget not detected — required for automatic install)"
                )
                self._print_warning("Frontend will not be available. Backend-only installation will continue.")
                return result

            if not headless:
                print(
                    f"\n{Fore.YELLOW}Install Node.js LTS automatically via winget? [Y/n]: {Style.RESET_ALL}",
                    end="",
                    flush=True,
                )
                response = tty_input().strip().lower()
                if response not in ("", "y", "yes"):
                    self._print_warning("Skipping Node.js installation")
                    self._print_warning("Frontend will not be available. Backend-only installation will continue.")
                    return result

            self._print_info("Installing Node.js LTS via winget...")
            try:
                subprocess.run(
                    [
                        "winget",
                        "install",
                        "--id",
                        "OpenJS.NodeJS.LTS",
                        "-e",
                        "--silent",
                        "--accept-source-agreements",
                        "--accept-package-agreements",
                    ],
                    check=True,
                    timeout=300,
                )
                self._print_success("Node.js LTS installed via winget")
                self._node_freshly_installed = True
                # Refresh PATH so subsequent shutil.which() finds the new node
                self._refresh_windows_path()
            except subprocess.CalledProcessError as e:
                self._print_error(f"winget install failed: {e}")
            except subprocess.TimeoutExpired:
                self._print_error("winget install timed out after 300 seconds")
            # Fall through to the existing re-check at the end of this method

        if platform_name == "Linux":
            if not headless:
                print(
                    f"\n{Fore.YELLOW}Install Node.js automatically? [Y/n]: {Style.RESET_ALL}",
                    end="",
                    flush=True,
                )
                response = tty_input().strip().lower()
                if response not in ("", "y", "yes"):
                    self._print_warning("Skipping Node.js installation")
                    self._print_warning("Frontend will not be available. Backend-only installation will continue.")
                    return result

            self._print_info("Installing Node.js 22 LTS via NodeSource...")
            try:
                # NodeSource provides Node 22 LTS; Ubuntu apt only has v18
                subprocess.run(
                    ["bash", "-c", "curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -"],
                    check=True,
                    timeout=120,
                )
                subprocess.run(
                    ["sudo", "apt", "install", "-y", "nodejs"],
                    check=True,
                    timeout=120,
                )
                self._print_success("Node.js 22 LTS installed via NodeSource")
                self._node_freshly_installed = True
            except subprocess.CalledProcessError as e:
                self._print_error(f"apt install failed: {e}")
            except subprocess.TimeoutExpired:
                self._print_error("apt install timed out after 120 seconds")

        elif platform_name == "Darwin":
            brew_path = shutil.which("brew")
            if not brew_path:
                self._print_info("Homebrew not found. Please install Node.js from https://nodejs.org/")
                self._print_warning("Frontend will not be available. Backend-only installation will continue.")
                return result

            if not headless:
                print(
                    f"\n{Fore.YELLOW}Install Node.js automatically via Homebrew? [Y/n]: {Style.RESET_ALL}",
                    end="",
                    flush=True,
                )
                response = tty_input().strip().lower()
                if response not in ("", "y", "yes"):
                    self._print_warning("Skipping Node.js installation")
                    self._print_warning("Frontend will not be available. Backend-only installation will continue.")
                    return result

            self._print_info("Installing Node.js via Homebrew...")
            try:
                subprocess.run(
                    ["brew", "install", "node"],
                    check=True,
                    timeout=300,
                )
                self._print_success("Node.js installed via Homebrew")
                self._node_freshly_installed = True
            except subprocess.CalledProcessError as e:
                self._print_error(f"brew install failed: {e}")
            except subprocess.TimeoutExpired:
                self._print_error("brew install timed out after 300 seconds")

        # Re-check after auto-install attempt
        node_path = shutil.which("node")
        npm_path = shutil.which("npm")

        if node_path and npm_path:
            self._print_success(f"Node.js detected: {node_path} ({self._get_node_version()})")
            self._print_success(f"npm detected: {npm_path}")
            result["found"] = True
            return result

        self._print_warning("Node.js not found after install attempt")
        self._print_warning("Frontend will not be available. Backend-only installation will continue.")
        return result

    def _refresh_windows_path(self) -> None:
        """
        Refresh the current process PATH from the Windows registry.

        winget appends installed binary directories to
        ``HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment\\Path``
        (system scope) and/or ``HKCU\\Environment\\Path`` (user scope), but
        already-running processes only see the launch-time PATH snapshot.
        Without this refresh, ``shutil.which()`` calls right after a winget
        install fail even when the install succeeded — the user sees a
        false "not found after install attempt" warning.

        No-op on non-Windows platforms.
        """
        if platform.system() != "Windows":
            return
        try:
            import winreg

            machine_path = ""
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ) as key:
                machine_path, _ = winreg.QueryValueEx(key, "Path")

            user_path = ""
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                    user_path, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                pass  # No user PATH override — fine, machine PATH is enough

            # Prepend registry PATH so newly-installed binaries take precedence
            # over whatever the launching shell had at process start.
            new_path = machine_path
            if user_path:
                new_path = user_path + os.pathsep + new_path
            existing = os.environ.get("PATH", "")
            if existing:
                new_path = new_path + os.pathsep + existing
            os.environ["PATH"] = new_path
        except Exception as exc:  # pragma: no cover - defensive
            self._print_warning(f"Could not refresh PATH from registry: {exc}")

    def generate_configs(self) -> dict[str, Any]:
        """
        Generate configuration files (config.yaml ONLY)

        .env generation happens AFTER database setup when real credentials exist.

        Returns:
            Configuration generation result
        """
        try:
            # Ensure venv site-packages are available before imports
            self._ensure_venv_site_packages()
            from installer.core.config import ConfigManager

            # Prepare settings for ConfigManager (v3.0: NO mode field)
            config_settings = {
                "pg_host": self.settings.get("pg_host", "localhost"),
                "pg_port": self.settings.get("pg_port", 5432),
                "api_port": self.settings.get("api_port", DEFAULT_API_PORT),
                "dashboard_port": self.settings.get("dashboard_port", DEFAULT_FRONTEND_PORT),
                "install_dir": str(self.install_dir),
                "bind": self.settings.get("bind", "0.0.0.0"),
                "external_host": self.settings.get("external_host", "localhost"),
                "network_mode": self.settings.get("network_mode", "localhost"),
                "selected_adapter": self.settings.get("selected_adapter"),
                "initial_ip": self.settings.get("initial_ip"),
                "db_name": self.settings.get("db_name", "giljo_mcp"),
            }

            config_manager = ConfigManager(settings=config_settings)

            # Generate config.yaml ONLY (no .env yet)
            self._print_info("Generating config.yaml...")
            yaml_result = config_manager.generate_config_yaml()

            if yaml_result["success"]:
                self._print_success("Configuration file generated (config.yaml)")
            else:
                self._print_error("Configuration generation failed")
                for error in yaml_result.get("errors", []):
                    self._print_error(f"  • {error}")

            return yaml_result

        except Exception as e:
            self._print_error(f"Config generation failed: {e}")
            return {"success": False, "errors": [str(e)]}

    def update_env_with_real_credentials(self) -> dict[str, Any]:
        """
        Update .env file with real database credentials after database setup

        This fixes the password synchronization bug where .env was generated
        with admin password instead of the randomly-generated database passwords.

        Returns:
            Update result with success status
        """
        try:
            # Ensure venv site-packages are available before imports
            self._ensure_venv_site_packages()
            # Import ConfigManager from existing module
            from installer.core.config import ConfigManager

            # Prepare settings with REAL database credentials
            config_settings = {
                "pg_host": self.settings.get("pg_host", "localhost"),
                "pg_port": self.settings.get("pg_port", 5432),
                "pg_password": self.settings.get("pg_password"),
                "db_name": self.settings.get("db_name", "giljo_mcp"),
                "api_port": self.settings.get("api_port", DEFAULT_API_PORT),
                "dashboard_port": self.settings.get("dashboard_port", DEFAULT_FRONTEND_PORT),
                "install_dir": str(self.install_dir),
                "owner_password": self.database_credentials.get("owner_password"),
                "user_password": self.database_credentials.get("user_password"),
                "default_tenant_key": getattr(
                    self, "default_tenant_key", None
                ),  # Pass generated tenant key (from seed_initial_data)
                "bind": self.settings.get("bind", "0.0.0.0"),
                # Network/SSL fields must be forwarded too -- without them the .env
                # template falls back to localhost/HTTP defaults, so a LAN/HTTPS
                # install wrote http://localhost frontend URLs while the page loaded
                # over https://<lan-ip>, breaking every API call (CSP + mixed content).
                "external_host": self.settings.get("external_host", "localhost"),
                "network_mode": self.settings.get("network_mode", "localhost"),
                "ssl_enabled": self.settings.get("ssl_enabled", False),
                # Frontend-mode choice drives ENVIRONMENT (INF-9155). Absent on the
                # first write (database setup, before the prompt) -> defaults to
                # development; _prompt_frontend_mode() re-stamps once the user chooses.
                "frontend_mode": self.settings.get("frontend_mode", "development"),
                # ssl_cert/ssl_key intentionally omitted here: generate_env_file()
                # never writes SSL cert paths to .env (no SSL_CERT_FILE variable).
                # Cert paths are written by Settings → Network (bring-your-own HTTPS)
                # and read at runtime from config.yaml paths.ssl_cert/ssl_key.
                # Forwarding them to this dict was dead code (INF-6040 cosmetic item 3).
            }

            # Create config manager
            config_manager = ConfigManager(settings=config_settings)

            # Regenerate .env with real credentials
            self._print_info("Regenerating .env with real database passwords...")
            env_result = config_manager.generate_env_file()

            if env_result["success"]:
                self._print_success("Configuration updated with database credentials")
                # Log keys written to .env (NEVER values)
                _logger.info(
                    ".env regenerated with keys: %s",
                    ", ".join(sorted(k for k in config_settings if config_settings[k] is not None)),
                )
            else:
                self._print_error("Failed to update configuration")
                for error in env_result.get("errors", []):
                    self._print_error(f"  • {error}")
                _logger.error(".env regeneration FAILED: %s", "; ".join(env_result.get("errors", [])))

            return env_result

        except Exception as e:
            self._print_error(f"Credential update failed: {e}")
            _logger.exception("Credential update exception: %s", _sanitize_log(str(e)))  # noqa: TRY401  # reason: sanitized error preserved for log searchability alongside traceback
            return {"success": False, "errors": [str(e)]}

    def _ensure_logs_dir(self) -> Path:
        """
        Ensure logs directory exists and return its path.

        Returns:
            Path object pointing to logs directory
        """
        logs_dir = self.install_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    def _prompt_frontend_mode(self) -> None:
        """Prompt user to choose Production or Contributor/Dev mode for the frontend.

        Production builds the frontend to frontend/dist/ so FastAPI can serve it
        on a single port. Contributor/Dev removes any stale dist/ so the Vite dev
        server is used instead.

        Skipped silently in headless mode (defaults to Production).
        """
        frontend_dir = self.install_dir / "frontend"
        dist_dir = frontend_dir / "dist"

        headless = self.settings.get("headless") or self.settings.get("unattended")
        mode = "1"

        if not headless:
            print()
            self._print_header("Frontend Mode")
            self._print_info("How will you use GiljoAI?")
            self._print_info("  1. Production (recommended) - Single port, optimized build")
            self._print_info("  2. Contributor / Dev mode - Two ports, hot-reload for code changes")
            try:
                mode = tty_input("\nSelect [1/2] (default: 1): ").strip() or "1"
            except EOFError:
                mode = "1"

        # Record the choice so the .env ENVIRONMENT stamp matches it (INF-9155).
        self.settings["frontend_mode"] = "production" if mode == "1" else "development"

        if mode == "1":
            self._print_info("Building production frontend...")
            npm_executable = shutil.which("npm")
            try:
                subprocess.run(
                    [npm_executable, "run", "build"],
                    cwd=str(frontend_dir),
                    check=True,
                    timeout=300,
                )
                self._print_success("Frontend built to frontend/dist/")
                self._print_info("startup.py will serve the frontend on the API port")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                self._print_warning(f"Frontend build failed: {e}")
                self._print_info("You can build later with: cd frontend && npm run build")
                self._print_info("Without a build, startup.py will use the Vite dev server")
        else:
            if dist_dir.exists():
                shutil.rmtree(dist_dir)
                self._print_info("Removed stale frontend/dist/ directory")
            self._print_success("Development mode selected")
            self._print_info("startup.py will launch the Vite dev server on port 7274")

        # The .env was first written during database setup, before this choice, so it
        # still carries the default ENVIRONMENT=development. Re-stamp it through the
        # owning writer now that frontend_mode is known (INF-9155). Idempotent — the
        # regenerate preserves existing secrets and DB credentials.
        if self.database_credentials:
            self.update_env_with_real_credentials()

    def launch_services(self) -> dict[str, Any]:
        """
        Launch API and Frontend services

        Returns:
            Launch result with process IDs
        """
        result = {"success": False}

        try:
            # Check port availability
            api_port = self.settings.get("api_port", DEFAULT_API_PORT)
            frontend_port = self.settings.get("dashboard_port", DEFAULT_FRONTEND_PORT)

            if not self._is_port_available(api_port):
                self._print_warning(f"Port {api_port} is in use - finding alternative...")
                api_port = self._find_available_port(api_port)
                if not api_port:
                    result["error"] = "No available port for API"
                    return result
                self._print_info(f"Using alternative API port: {api_port}")

            if not self._is_port_available(frontend_port):
                self._print_warning(f"Port {frontend_port} is in use - finding alternative...")
                frontend_port = self._find_available_port(frontend_port)
                if not frontend_port:
                    self._print_warning("No available port for frontend - skipping")
                    frontend_port = None

            # Determine Python executable (platform-specific)
            python_executable = self.platform.get_venv_python(self.venv_dir)

            # Get ports from settings
            api_port = self.settings.get("api_port", DEFAULT_API_PORT)
            frontend_port = self.settings.get("dashboard_port", DEFAULT_FRONTEND_PORT)

            # Launch API server
            api_script = self.install_dir / "api" / "run_api.py"

            if not api_script.exists():
                self._print_error(f"API script not found: {api_script}")
                result["error"] = "API script missing"
                return result

            self._print_info("Starting API server...")

            api_process = subprocess.Popen(
                [str(python_executable), str(api_script), "--port", str(api_port)],
                cwd=str(self.install_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._print_success(f"API server started (PID: {api_process.pid})")

            result["api_pid"] = api_process.pid

            # Launch frontend (if npm available)
            frontend_process = None
            if shutil.which("npm"):
                frontend_dir = self.install_dir / "frontend"

                if frontend_dir.exists():
                    # Verify dependencies were installed during installation phase
                    if not self._verify_npm_dependencies(frontend_dir):
                        self._print_error("Frontend dependencies not found!")
                        self._print_error("Dependencies should have been installed during 'python install.py'")
                        self._print_error("Please run installation again:")
                        self._print_error("  python install.py")
                        result["error"] = "Frontend dependencies missing - run python install.py first"
                        result["success"] = False
                        return result

                    self._print_info("Starting frontend server...")

                    # Delegate to platform handler for npm command execution
                    # Note: For background processes, we still use subprocess.Popen directly
                    # but use platform handler to determine shell setting
                    npm_cmd = ["npm", "run", "dev", "--", "--port", str(frontend_port), "--strictPort"]

                    # No shell needed - using array of predefined args (secure)

                    frontend_process = subprocess.Popen(
                        npm_cmd,
                        cwd=str(frontend_dir),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=False,  # nosec B602 - Safe: using array of predefined args
                    )
                    self._print_success(f"Frontend server started (PID: {frontend_process.pid})")

                    result["frontend_pid"] = frontend_process.pid
                else:
                    self._print_warning("Frontend directory not found")
            else:
                self._print_warning("npm not found - frontend not started")

            # Wait for services to initialize
            self._print_info("Waiting for services to initialize...")
            time.sleep(3)

            result["success"] = True
            return result

        except Exception as e:
            self._print_error(f"Service launch failed: {e}")
            result["error"] = str(e)
            return result

    def create_desktop_shortcuts(self) -> None:
        """Create desktop shortcuts (delegates to platform handler)"""
        # Check if platform supports shortcuts
        if not self.platform.supports_desktop_shortcuts():
            self._print_info(f"Desktop shortcuts not supported on {self.platform.platform_name}")
            return

        # Delegate to platform handler
        result = self.platform.create_desktop_shortcuts(install_dir=self.install_dir, venv_dir=self.venv_dir)

        if result["success"]:
            for shortcut in result.get("shortcuts_created", []):
                self._print_success(f"Created shortcut: {shortcut}")
        else:
            self._print_warning(f"Shortcut creation: {result.get('message', 'Unknown result')}")

    def _provision_saas_redis(self) -> dict[str, Any]:
        """Provision Redis for SaaS mode (GILJO_MODE=saas only).

        This method is a no-op on CE paths — it is called only when
        os.environ['GILJO_MODE'] == 'saas'.  CE installer code above never
        reaches this call.

        Responsibilities:
          1. Install the redis-server daemon (platform-specific).
          2. Enable/start the service.
          3. Write REDIS_URL to .env if not already set.
          4. Run redis-cli ping to confirm the daemon is up.

        NOTE: macOS branch uses brew; this branch is NOT validated (no macOS
        validation box exists at GiljoAI as of 2026-05-14).
        """
        import subprocess as _subprocess

        result: dict[str, Any] = {"success": False}
        plat = platform.system()

        # -----------------------------------------------------------------
        # 1. Install + start Redis daemon
        # -----------------------------------------------------------------
        try:
            if plat == "Linux":
                self._print_info("Installing redis-server via apt-get...")
                _subprocess.run(
                    ["sudo", "apt-get", "update", "-qq"],
                    check=True,
                    stdin=_subprocess.DEVNULL,
                    capture_output=True,
                )
                _subprocess.run(
                    ["sudo", "apt-get", "install", "-y", "-qq", "redis-server"],
                    check=True,
                    stdin=_subprocess.DEVNULL,
                    capture_output=True,
                )
                self._print_success("redis-server installed")
                self._print_info("Enabling and starting redis-server via systemctl...")
                _subprocess.run(
                    ["sudo", "systemctl", "enable", "--now", "redis-server"],
                    check=True,
                    stdin=_subprocess.DEVNULL,
                    capture_output=True,
                )
                self._print_success("redis-server enabled and started")

            elif plat == "Windows":
                # Prefer scoop; if absent, guide operator to WSL Redis.
                # Do NOT auto-install scoop — too invasive for a server OS.
                if shutil.which("scoop"):
                    self._print_info("Installing Redis via scoop...")
                    _subprocess.run(["scoop", "install", "redis"], check=True, capture_output=True)
                    self._print_success("Redis installed via scoop")
                    self._print_info("Start Redis manually: redis-server  (or add to Windows Task Scheduler).")
                else:
                    self._print_warning(
                        "scoop not found. Redis is not installed automatically on Windows SaaS servers "
                        "without scoop. Options:\n"
                        "  1. Install scoop (https://scoop.sh) then re-run install.py with GILJO_MODE=saas.\n"
                        "  2. Use WSL2 and run: sudo apt-get install -y redis-server && "
                        "sudo systemctl enable --now redis-server\n"
                        "  3. Use Memurai (https://www.memurai.com/) — Windows-native Redis."
                    )
                    result["error"] = (
                        "scoop absent; Redis not provisioned on Windows. See installer output for options."
                    )
                    # Still write REDIS_URL — operator must start Redis manually.

            elif plat == "Darwin":
                # macOS: brew install redis + brew services start redis.
                # NOTE: macOS branch is NOT validated (no macOS validation box at
                # GiljoAI as of 2026-05-14).  Proceed best-effort.
                self._print_info("Installing Redis via brew (macOS — NOT validated)...")
                _subprocess.run(["brew", "install", "redis"], check=True, capture_output=True)
                _subprocess.run(["brew", "services", "start", "redis"], check=True, capture_output=True)
                self._print_success("Redis installed and started via brew (macOS — unvalidated path)")

            else:
                self._print_warning(f"Unknown platform '{plat}' — skipping Redis daemon install.")
                result["error"] = f"Unknown platform: {plat}"

        except _subprocess.CalledProcessError as exc:
            self._print_error(f"Redis daemon install/start failed: {exc}")
            _logger.exception("saas_redis_provision daemon failed")
            result["error"] = str(exc)
            # Continue to write REDIS_URL — operator can fix daemon manually.

        # -----------------------------------------------------------------
        # 2. Write REDIS_URL to .env (if not already set)
        # -----------------------------------------------------------------
        default_redis_url = "redis://127.0.0.1:6379/0"
        env_file = self.install_dir / ".env"

        if env_file.exists():
            env_text = env_file.read_text(encoding="utf-8")
            if "REDIS_URL=" not in env_text:
                self._print_info("Writing REDIS_URL to .env...")
                redis_line = (
                    "\n# =============================================================================\n"
                    "# REDIS (SaaS Edition — per-tenant rate limiting)\n"
                    "# =============================================================================\n"
                    f"REDIS_URL={default_redis_url}\n"
                )
                env_file.write_text(env_text + redis_line, encoding="utf-8")
                self._print_success(f"REDIS_URL={default_redis_url} written to .env")
            else:
                current_url = next(
                    (line.split("=", 1)[1].strip() for line in env_text.splitlines() if line.startswith("REDIS_URL=")),
                    default_redis_url,
                )
                self._print_info(f"REDIS_URL already set in .env: {current_url}")
        else:
            self._print_warning(
                ".env not found — REDIS_URL not written. "
                f"Add REDIS_URL={default_redis_url} manually before starting the SaaS server."
            )

        # -----------------------------------------------------------------
        # 3. Post-install redis-cli ping
        # -----------------------------------------------------------------
        try:
            ping_proc = _subprocess.run(
                ["redis-cli", "ping"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if ping_proc.returncode == 0 and "PONG" in ping_proc.stdout.upper():
                self._print_success("redis-cli ping → PONG (Redis is up)")
                result["success"] = True
            else:
                self._print_warning(
                    f"redis-cli ping returned: {ping_proc.stdout.strip() or ping_proc.stderr.strip() or '(no output)'}. "
                    "Redis may not be running yet. Start it manually and verify before launching the server."
                )
                result.setdefault("error", "redis-cli ping did not return PONG")
        except (FileNotFoundError, _subprocess.TimeoutExpired) as exc:
            self._print_warning(
                f"redis-cli not found or timed out ({exc}). Verify Redis is running before starting the SaaS server."
            )
            result.setdefault("error", f"redis-cli check failed: {exc}")

        return result

    def _get_all_network_ips(self) -> list[str]:
        """Get all non-loopback IPv4 addresses"""
        # Delegate to platform handler for network interface detection
        return self.platform.get_network_ips()

    def _print_success_summary(self) -> None:
        """Print installation success summary with startup instructions"""
        separator = "=" * 60

        print(f"\n{Fore.GREEN}{Style.BRIGHT}{separator}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{Style.BRIGHT}  Installation Complete!{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{Style.BRIGHT}{separator}{Style.RESET_ALL}\n")

        # Shell-restart notice when Node.js was installed mid-session.
        # winget/apt/brew updates the system PATH but the parent shell that
        # launched install.py still has the pre-install snapshot. Children
        # of that shell (including the next "python startup.py") inherit
        # the stale PATH and crash on `npm` lookup. Tell the user up front.
        # Windows-only: winget updates registry PATH but the parent
        # PowerShell keeps its snapshot. Linux/macOS package managers drop
        # binaries into /usr/bin or /usr/local/bin which are already on
        # PATH, so new child processes find npm without a shell restart.
        if self._node_freshly_installed and platform.system() == "Windows":
            print(f"{Fore.YELLOW}{Style.BRIGHT}{separator}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}{Style.BRIGHT}  Action required: restart your shell{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}{Style.BRIGHT}{separator}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Node.js was installed during this run. Your current{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}shell still has the pre-install PATH and will not find{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}npm. Close this window and open a new one before{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}running startup.py:{Style.RESET_ALL}\n")
            print(f"  {Fore.WHITE}cd {self.install_dir}{Style.RESET_ALL}")
            print(f"  {Fore.GREEN}python startup.py{Style.RESET_ALL}\n")

        # Database credentials
        if self.database_credentials:
            db_display = self.settings.get("db_name", "giljo_mcp")
            # INF-9321: DETECTED port -- hardcoding 5432 here recreated the bug in the one line users act on.
            db_port = self.settings.get("pg_port", 5432)
            print(  # CodeQL: db_name and role names are not sensitive
                f"{Fore.YELLOW}Database: {Fore.WHITE}{db_display} @ localhost:{db_port} (owner: giljo_owner, user: giljo_user){Style.RESET_ALL}\n"
            )

        # Detect protocol and ports
        # In production mode (frontend/dist exists), frontend is served on the API port
        api_port = self.settings.get("api_port", DEFAULT_API_PORT)
        is_production = (self.install_dir / "frontend" / "dist").exists()
        frontend_port = api_port if is_production else self.settings.get("dashboard_port", DEFAULT_FRONTEND_PORT)
        protocol = "https" if self.settings.get("ssl_enabled") else "http"

        # How to start
        print(f"{Fore.CYAN}{Style.BRIGHT}Start the application:{Style.RESET_ALL}")
        print(f"  {Fore.GREEN}python startup.py{Style.RESET_ALL}")
        print()

        # Where to go
        print(f"{Fore.CYAN}{Style.BRIGHT}Then open your browser:{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}{protocol}://localhost:{frontend_port}{Style.RESET_ALL}")  # CodeQL: URL is not sensitive

        # Show network IPs only if not in localhost mode
        network_mode = self.settings.get("network_mode", "localhost")
        if network_mode != "localhost":
            network_ips = self._get_all_network_ips()
            if network_ips:
                for ip in network_ips:
                    print(
                        f"  {Fore.WHITE}{protocol}://{ip}:{frontend_port}  (LAN){Style.RESET_ALL}"
                    )  # CodeQL: LAN IP is not sensitive
        print()

        # API docs
        print(
            f"{Fore.WHITE}API docs: {Fore.CYAN}{protocol}://localhost:{api_port}/docs{Style.RESET_ALL}"
        )  # CodeQL: URL is not sensitive
        print()

        print(f"{Fore.GREEN}Create your administrator account on first visit.{Style.RESET_ALL}\n")

    def _print_postgresql_install_guide(self) -> None:
        """Print platform-specific PostgreSQL installation guide"""
        print(f"\n{Fore.YELLOW}PostgreSQL Installation Required{Style.RESET_ALL}\n")

        # Delegate to platform handler for OS-specific instructions
        guide = self.platform.get_postgresql_install_guide(recommended_version=RECOMMENDED_POSTGRESQL_VERSION)
        print(guide)
        print()

    async def _verify_essential_tables(self) -> dict[str, Any]:
        """
        Verify that essential tables were created by migrations.

        This catches the scenario where alembic upgrade succeeds but no tables
        were actually created (e.g., empty migrations/versions folder).

        Essential tables checked:
        - setup_state: Required for installation tracking
        - users: Required for authentication
        - products: Core business entity
        - projects: Core business entity
        - messages: Agent communication

        Returns:
            Dict with success status and details about missing tables
        """
        result = {"success": False, "tables_found": 0, "missing_tables": []}

        # Essential tables that MUST exist for a valid installation
        essential_tables = [
            "setup_state",
            "users",
            "products",
            "projects",
            "messages",
            "agent_jobs",  # 0371: renamed from mcp_agent_jobs
            "agent_executions",
        ]

        try:
            import os

            from sqlalchemy import text

            from giljo_mcp.database import DatabaseManager

            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                result["error"] = "DATABASE_URL not found"
                return result

            db_manager = DatabaseManager(db_url, is_async=True)

            async with db_manager.get_session_async() as session:
                # Query information_schema for existing tables
                check_query = text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_type = 'BASE TABLE'
                """)
                query_result = await session.execute(check_query)
                existing_tables = {row[0] for row in query_result.fetchall()}

            await db_manager.close_async()

            # Check which essential tables exist
            for table in essential_tables:
                if table in existing_tables:
                    result["tables_found"] += 1
                else:
                    result["missing_tables"].append(table)

            # Success if all essential tables exist
            result["success"] = len(result["missing_tables"]) == 0
            result["existing_tables"] = list(existing_tables)

            return result

        except Exception as e:
            result["error"] = str(e)
            return result

    def _is_port_available(self, port: int, host: str = "127.0.0.1") -> bool:
        """Check if port is available"""
        with contextlib.suppress(Exception), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            return result != 0
        return False

    def _find_available_port(self, start_port: int, max_attempts: int = 10) -> int | None:
        """Find available port starting from start_port"""
        for offset in range(max_attempts):
            port = start_port + offset
            if self._is_port_available(port):
                return port
        return None

    # Output helpers
    def _print_header(self, text: str) -> None:
        """Print section header"""
        separator = "=" * 70
        print(f"\n{Fore.CYAN}{Style.BRIGHT}{separator}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{Style.BRIGHT}  {text}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{Style.BRIGHT}{separator}{Style.RESET_ALL}\n")
        _logger.info("--- %s ---", _sanitize_log(text))

    def _print_success(self, text: str) -> None:
        """Print success message"""
        print(f"{Fore.GREEN}[OK]{Style.RESET_ALL} {text}")
        _logger.info("[OK] %s", _sanitize_log(text))

    def _print_error(self, text: str) -> None:
        """Print error message (status only, never passwords/credentials)."""
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {text}")
        _logger.error("[ERROR] %s", _sanitize_log(text))

    def _print_warning(self, text: str) -> None:
        """Print warning message (status only, never passwords/credentials)."""
        print(f"{Fore.YELLOW}[!]{Style.RESET_ALL} {text}")
        _logger.warning("[!] %s", _sanitize_log(text))

    def _print_info(self, text: str) -> None:
        """Print info message (status only, never passwords/credentials)."""
        print(f"{Fore.BLUE}[INFO]{Style.RESET_ALL} {text}")
        _logger.info("[INFO] %s", _sanitize_log(text))


@click.command()
@click.option("--headless", is_flag=True, help="Non-interactive mode (use defaults)")
@click.option("--dev", is_flag=True, help="Developer install (adds pre-commit hooks)")
@click.option("--pg-password", default=None, help="PostgreSQL admin password (REQUIRED)")
@click.option("--api-port", default=DEFAULT_API_PORT, type=int, help="API server port")
@click.option("--frontend-port", default=DEFAULT_FRONTEND_PORT, type=int, help="Frontend port")
@click.option("--setup-only", is_flag=True, help="Setup-only mode (skip prereqs and deps, just configure)")
@click.option(
    "--repair",
    is_flag=True,
    help=(
        "Repair an interrupted install: re-run every setup step idempotently (implies "
        "--setup-only). May reset the giljo_owner/giljo_user passwords if .env is missing "
        "— do not use if another co-located install shares those roles."
    ),
)
def main(
    headless: bool, dev: bool, pg_password: str, api_port: int, frontend_port: int, setup_only: bool, repair: bool
) -> None:
    """
    Giljo HQ v3.0 - Unified Installer

    Single-command installation for all platforms.
    Use --dev to include developer tools (pre-commit hooks).
    Use --setup-only when called from installer scripts (prereqs and deps already handled).
    Use --repair to idempotently re-run setup and recover an interrupted install.
    """
    try:
        # Unattended (env-driven) mode for scripted / no-TTY installs.
        # Activated by GILJO_UNATTENDED=1. Distinct from --headless (CI defaults)
        # so existing headless behavior stays byte-identical. See
        # _apply_unattended_settings() for the env-var contract.
        unattended = os.environ.get("GILJO_UNATTENDED", "").strip() == "1"
        # Env fallbacks let install.sh / install.ps1 pass config without a TTY.
        pg_password = pg_password or os.environ.get("GILJO_PG_PASSWORD")

        # Prepare settings
        settings = {
            "install_dir": os.environ.get("GILJO_INSTALL_DIR") or str(Path.cwd()),
            "pg_password": pg_password,
            "api_port": api_port,
            "dashboard_port": frontend_port,
            "headless": headless,
            "unattended": unattended,
            "dev": dev,
            "setup_only": setup_only,
            "repair": repair,
        }
        if os.environ.get("GILJO_DB_NAME"):
            settings["db_name"] = os.environ["GILJO_DB_NAME"]

        # Create installer
        installer = UnifiedInstaller(settings=settings)

        # Run installation
        result = installer.run()

        # Exit with appropriate code
        sys.exit(0 if result["success"] else 1)

    except KeyboardInterrupt:
        _logger.info("Installation cancelled by user")
        print(f"\n{Fore.YELLOW}Installation cancelled{Style.RESET_ALL}")
        sys.exit(0)

    except Exception as e:
        _logger.exception("Installation failed")
        print(f"\n{Fore.RED}Installation failed: {e}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}See install.log for details{Style.RESET_ALL}")
        sys.exit(1)


if __name__ == "__main__":
    main()
