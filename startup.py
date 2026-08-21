#!/usr/bin/env python3

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Giljo HQ - Unified Startup Script

This is the primary entry point for running Giljo HQ.
It handles:
- PostgreSQL detection and validation
- Python version checking
- Database connectivity verification
- First-run detection
- Service startup (API + Frontend)
- Browser launching (setup wizard or dashboard)

Usage:
    python startup.py              # Start services
    python startup.py --help       # Show help
    python startup.py --check-only # Only check dependencies

Cross-platform: Works on Windows, Linux, and macOS
"""

import atexit
import contextlib
import os
import platform
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import IO


# NOTE: Third-party imports (click, colorama) are deferred until AFTER
# ensure_project_virtualenv() runs below. Otherwise `python startup.py`
# from a fresh shell (no venv activated) crashes with ModuleNotFoundError
# before the venv-relaunch guard ever fires. Keep this module's top section
# stdlib-only.


# ExitStack for managing log file handles that must outlive the function scope
# (passed to subprocess.Popen). Registered with atexit so handles close on exit.
_log_file_stack = contextlib.ExitStack()
atexit.register(_log_file_stack.close)

# Holds the Windows Job Object for the API child process (set by start_api_server).
_api_job_object: object = None


# ---------------------------------------------------------------------------
# Virtualenv guard: always relaunch inside the project-managed interpreter
# ---------------------------------------------------------------------------


def ensure_project_virtualenv() -> None:
    """Re-exec inside the installer-managed virtualenv when available.

    Uses subprocess.run() instead of os.execv() for cross-platform compatibility.

    Why not os.execv()?
    - On Unix: os.execv() replaces the current process (works correctly)
    - On Windows: os.execv() spawns a new process and exits immediately,
      losing the child's exit code and running the child in "background"

    The subprocess.run() + sys.exit() pattern works identically on all platforms:
    parent waits for child, then exits with child's return code.

    References:
    - https://github.com/python/cpython/issues/101191
    - https://bugs.python.org/issue19124
    """
    try:
        project_root = Path(__file__).resolve().parent
        venv_dir = project_root / "venv"

        if not venv_dir.exists():
            return

        # If we're already inside the project virtualenv, no action needed
        if Path(sys.prefix).resolve() == venv_dir.resolve():
            return

        # Find venv Python executable (platform-specific paths)
        if platform.system() == "Windows":
            venv_python = venv_dir / "Scripts" / "python.exe"
        else:
            # Try python first, fallback to python3
            venv_python = venv_dir / "bin" / "python"
            if not venv_python.exists():
                venv_python = venv_dir / "bin" / "python3"

        if not venv_python.exists():
            return

        print("Re-launching Giljo HQ startup inside project virtual environment...")

        # Cross-platform process replacement:
        # subprocess.run() waits for child and captures exit code
        # sys.exit() propagates the exit code to parent/shell
        result = subprocess.run([str(venv_python), *sys.argv], check=False)
        sys.exit(result.returncode)

    except Exception as e:
        # Log error but continue - don't block startup entirely
        print(f"Warning: Could not activate venv: {e}", file=sys.stderr)
        return


if "pytest" not in sys.modules:
    ensure_project_virtualenv()

# Third-party imports — safe now that the venv guard above has re-executed
# us inside the project venv (when one exists). E402 is intentional: these
# MUST stay below ensure_project_virtualenv() or fresh-shell installs crash
# with ModuleNotFoundError before the relaunch guard can fire.
import click
from colorama import init


# Initialize colorama for cross-platform colored output
init(autoreset=True)

# BE-9060 mechanical split: self-contained helper groups moved verbatim to the
# startup_support package. Every moved name is re-imported here so
# `startup.<name>` remains a stable seam -- tests monkeypatch
# `startup.<name>` and the orchestration functions below resolve these
# through this module's globals, so patching still intercepts.
from startup_support.checks import (  # noqa: F401 -- re-exported seam
    MIN_PYTHON_VERSION,
    check_database_connectivity,
    check_dependencies,
    check_first_run,
    check_npm_available,
    check_pip_available,
    check_postgresql_installed,
    check_python_version,
    install_requirements,
    load_postgresql_config,
    seed_default_settings,
)
from startup_support.console import (
    print_error,
    print_header,
    print_info,
    print_success,
    print_warning,
)
from startup_support.migration_stamp import (  # noqa: F401 -- re-exported seam
    _check_and_stamp_migration_version,
    _get_database_url,
    _heal_schema_to_v37,
)
from startup_support.services import (
    _choose_browser_target,
    _launch_log_viewer,
    _single_instance_lock,
    open_browser,
    wait_for_api_ready,
)


# Constants
REQUIRED_POSTGRESQL_VERSION = 18
DEFAULT_API_PORT = 7272
DEFAULT_FRONTEND_PORT = 7274
POSTGRESQL_DOWNLOAD_URL = "https://www.postgresql.org/download/"


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """
    Check if a port is available.

    Args:
        port: Port number to check
        host: Host to check on

    Returns:
        True if port is available, False otherwise
    """
    with contextlib.suppress(Exception), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        return result != 0  # Non-zero means port is available
    return False


def find_available_port(preferred_port: int, max_attempts: int = 10) -> int | None:
    """
    Find an available port starting from preferred port.

    Args:
        preferred_port: Preferred port number
        max_attempts: Maximum number of ports to try

    Returns:
        Available port number or None if none found
    """
    for offset in range(max_attempts):
        port = preferred_port + offset
        if is_port_available(port):
            return port

    return None


def get_config_ports() -> tuple[int, int]:
    """
    Get API and Frontend ports from config.yaml.

    Returns:
        Tuple of (api_port, frontend_port)
    """
    try:
        import yaml

        config_path = Path.cwd() / "config.yaml"

        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)

            api_port = config.get("services", {}).get("api", {}).get("port", DEFAULT_API_PORT)
            frontend_port = config.get("services", {}).get("frontend", {}).get("port", DEFAULT_FRONTEND_PORT)

            return api_port, frontend_port

    except Exception as e:
        print_warning(f"Could not read config.yaml: {e}")

    # Fallback to defaults
    return DEFAULT_API_PORT, DEFAULT_FRONTEND_PORT


def _get_network_mode() -> str:
    """Read security.network.mode from config.yaml. Returns 'localhost' if not set."""
    with contextlib.suppress(Exception):
        import yaml

        config_path = Path.cwd() / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
            return config.get("security", {}).get("network", {}).get("mode", "localhost")
    return "localhost"


def get_deployment_context() -> str:
    """Read top-level `deployment_context` from config.yaml.

    Returns one of: 'localhost' (default), 'lan', 'saas-production'.
    Controls browser auto-open host and status banner content.
    """
    with contextlib.suppress(Exception):
        import yaml

        config_path = Path.cwd() / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
            return config.get("deployment_context", "localhost")
    return "localhost"


def _get_external_host() -> str:
    """Read services.external_host from config.yaml. Empty string if absent."""
    with contextlib.suppress(Exception):
        import yaml

        config_path = Path.cwd() / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
            return config.get("services", {}).get("external_host", "") or ""
    return ""


def get_ssl_enabled() -> bool:
    """
    Check if SSL is enabled in config.yaml AND cert files exist on disk.
    Always returns False for localhost mode — SSL is only for LAN/WAN.

    Cert-existence check (R5/INF-6040): if ssl_enabled is True in config but the
    cert files have been moved or deleted since installation, returns False with a
    warning rather than advertising https to health probes while run_api silently
    serves http (MISMATCH). A missing cert at runtime falls back to HTTP; we align
    the probe scheme to what run_api will actually serve.

    Returns:
        True if ssl_enabled is set in features config AND not localhost mode
        AND cert files referenced in paths.ssl_cert/ssl_key both exist on disk.
    """
    if _get_network_mode() == "localhost":
        return False
    with contextlib.suppress(Exception):
        import yaml

        config_path = Path.cwd() / "config.yaml"

        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)

            ssl_enabled = bool(config.get("features", {}).get("ssl_enabled", False))
            if not ssl_enabled:
                return False

            # Cert-existence check: align startup health-probe scheme with
            # what run_api will actually serve (run_api also falls back to HTTP
            # when certs are absent, but startup would probe https -> mismatch).
            ssl_cert = config.get("paths", {}).get("ssl_cert")
            ssl_key = config.get("paths", {}).get("ssl_key")
            if ssl_cert and ssl_key and (not Path(ssl_cert).exists() or not Path(ssl_key).exists()):
                print_warning(
                    "SSL cert/key files not found — startup falling back to HTTP probe. "
                    "Restore certs or re-run install to fix HTTPS."
                )
                return False
            return True

    return False


def get_network_ip() -> str | None:
    """
    Get network IP address for display purposes.

    Respects the user's install-time network mode choice:
    - localhost mode → always returns None (caller falls back to "localhost")
    - auto/static/custom → reads from config or detects at runtime

    Returns:
        Network IP address or None if localhost mode
    """
    network_mode = _get_network_mode()

    # Localhost mode: honor the user's choice, don't detect LAN IPs
    if network_mode == "localhost":
        return None

    # LAN/WAN modes: try config.yaml first
    try:
        import yaml

        config_path = Path.cwd() / "config.yaml"

        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)

            # Prefer installer-configured external host for browser launch
            external_host = config.get("services", {}).get("external_host")
            if external_host and external_host not in ("localhost", "127.0.0.1", "0.0.0.0"):
                return external_host

            # Try server.ip first (legacy), then security.network.initial_ip
            network_ip = config.get("server", {}).get("ip")
            if not network_ip:
                network_ip = config.get("security", {}).get("network", {}).get("initial_ip")

            if network_ip:
                return network_ip

    except Exception as e:
        print_warning(f"Could not read network IP from config.yaml: {e}")

    # Fallback: Detect primary network IP at runtime (for LAN/WAN installs)
    try:
        import psutil

        # Virtual adapter patterns (reuse from api/endpoints/network.py)
        virtual_patterns = [
            "docker",
            "veth",
            "br-",
            "vmnet",
            "vboxnet",
            "virbr",
            "tun",
            "tap",
            "vEthernet",
            "Hyper-V",
            "WSL",
        ]
        loopback_patterns = ["lo", "Loopback"]

        interfaces = psutil.net_if_addrs()
        interface_stats = psutil.net_if_stats()

        candidates = []

        for interface_name, addresses in interfaces.items():
            # Check if virtual or loopback
            is_virtual = any(pattern.lower() in interface_name.lower() for pattern in virtual_patterns)
            is_loopback = any(pattern.lower() in interface_name.lower() for pattern in loopback_patterns)

            # Check if interface is active
            stats = interface_stats.get(interface_name)
            is_active = stats.isup if stats else False

            # Get IPv4 addresses
            for addr in addresses:
                if addr.family == 2:  # AF_INET (IPv4)
                    ip = addr.address

                    # Filter out loopback and link-local
                    if not ip.startswith("127.") and not ip.startswith("169.254.") and is_active and not is_loopback:
                        candidates.append({"name": interface_name, "ip": ip, "is_virtual": is_virtual})

        if candidates:
            # Prefer physical adapters over virtual ones
            physical = [c for c in candidates if not c["is_virtual"]]

            if physical:
                selected = physical[0]
                print_info(f"Detected primary network adapter: {selected['name']} ({selected['ip']})")
                return selected["ip"]
            # Fall back to first virtual adapter if no physical found
            selected = candidates[0]
            print_info(f"Detected network adapter: {selected['name']} ({selected['ip']})")
            return selected["ip"]

    except ImportError:
        print_warning("psutil not available for network detection")
    except Exception as e:
        print_warning(f"Could not detect network IP: {e}")

    return None


def start_api_server(
    verbose: bool = False,
    api_port: int | None = None,
) -> subprocess.Popen | None:  # file-redirect always (INF-5092); verbose gates the live-log viewer window
    """
    Start the API server.

    stdout/stderr are always redirected to logs/api_stdout.log and
    logs/api_stderr.log via OS-level file descriptors (os.open -> fd int passed
    to Popen).  Using fd integers instead of Python file objects means Popen
    inherits OS-duplicated handles; the parent fds are closed immediately after
    Popen returns so the child fully owns the handles.

    On Windows the child is assigned to a Job Object with
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, so the API process is killed
    automatically when the launcher (this process) exits -- even on crash or
    Ctrl+C.

    When verbose=True on CE (GILJO_MODE in ("", "ce")), a separate colorized
    viewer window auto-opens tailing api_stdout.log (see _launch_log_viewer);
    SaaS never opens a window. api_port, when provided, is passed to run_api as
    ``--port N --strict-port`` so it binds exactly that port or exits instead of
    roaming to an alternative and lingering as a 2nd writer on api_stdout.log.

    Manual live log tailing (always available)::

        Get-Content -Wait logs\api_stdout.log   # PowerShell
        tail -f logs/api_stdout.log              # bash

    Returns:
        Popen process object or None if failed
    """
    try:
        api_script = Path.cwd() / "api" / "run_api.py"

        if not api_script.exists():
            print_error(f"API script not found: {api_script}")
            return None

        # Determine Python executable (prefer venv)
        venv_python = Path.cwd() / "venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            venv_python = Path.cwd() / "venv" / "bin" / "python"

        if venv_python.exists():
            python_executable = str(venv_python)
        else:
            python_executable = sys.executable

        # Always redirect to log files via OS-level fd integers so the parent
        # can close its end immediately after Popen and the child retains its
        # own OS-duplicated handles.  This avoids the "stalled stdout blocks
        # the event loop" failure mode (INF-5092).
        logs_dir = Path.cwd() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = logs_dir / "api_stdout.log"
        stderr_path = logs_dir / "api_stderr.log"

        # Each run starts with fresh, empty log files (O_TRUNC below). No
        # archive/retention: the INF-6023 archive-on-start was built on a
        # disproven crash theory (no WinError 32 rollover ever occurred);
        # giljo_mcp.log is bounded by SafeRotatingFileHandler (10 MB x 5,
        # BE-6030). A run-stamp is computed for the live-viewer window title.
        giljo_mode = os.environ.get("GILJO_MODE", "")
        _run_stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")  # noqa: DTZ005 -- local wall-clock time for the viewer title

        # O_TRUNC guarantees each run starts from a clean, empty file even if
        # a prior run left content behind (no archive step runs anymore).
        stdout_fd = os.open(str(stdout_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        stderr_fd = os.open(str(stderr_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)

        # Defensive: keep the child's stdout/stderr unbuffered (INF-6022).
        # logging.StreamHandler already flushes per record, so api_stdout.log is
        # live without this -- PYTHONUNBUFFERED is belt-and-suspenders for any
        # plain print()/third-party write that bypasses the logging path. The
        # O_TRUNC reset above means the viewer always reads from the top of a
        # clean file with only the current session's output.
        # Buffering mode only, NOT the async-safe logging path (QueueHandler/
        # QueueListener), so it does not reintroduce the INF-5092 wedge.
        child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        popen_kwargs: dict = {
            "cwd": str(Path.cwd()),
            "stdout": stdout_fd,
            "stderr": stderr_fd,
            "env": child_env,
        }

        # Start API server. Pass the launcher-chosen port with --strict-port so
        # run_api binds exactly that port or exits -- it never roams to 7273 and
        # lingers as a 2nd writer on api_stdout.log (the INF-6023b corruption).
        api_cmd = [python_executable, str(api_script)]
        if api_port is not None:
            api_cmd += ["--port", str(api_port), "--strict-port"]
        process = subprocess.Popen(api_cmd, **popen_kwargs)

        # Close parent-side fds -- child has OS-duplicated copies and fully
        # owns the file from this point forward.
        os.close(stdout_fd)
        os.close(stderr_fd)

        # On Windows: assign child to a Job Object so it is killed when the
        # launcher (this process) exits for any reason.
        if platform.system() == "Windows":
            try:
                from giljo_mcp.process.win_job_object import WindowsJobObject

                _job = WindowsJobObject()
                _job.assign(process.pid)
                # Hold a module-level reference so the job handle stays open
                # for the launcher's lifetime (atexit will call _job.close()).
                global _api_job_object  # noqa: PLW0603
                _api_job_object = _job
            except Exception as job_err:
                print_warning(f"Job Object containment unavailable: {job_err}")

        print_success(f"API server started (PID: {process.pid})")
        print_info(f"API logs: {stdout_path.resolve()!s}")
        print_info(f"API errors: {stderr_path.resolve()!s}")

        # Live log viewer: --verbose-gated, CE-only. Opens a SEPARATE colorized
        # window that tails api_stdout.log (read-only); closing it never touches
        # the running server (INF-5092 decoupling). SaaS/Railway: no window --
        # logs are consumed by the platform.
        if verbose and giljo_mode in ("", "ce"):
            _launch_log_viewer(stdout_path, _run_stamp)

        return process

    except Exception as e:
        print_error(f"Failed to start API server: {e}")
        return None


def start_frontend_server(verbose: bool = False) -> subprocess.Popen | None:
    """
    Start the frontend development server.

    In production mode (frontend/dist/ exists and --dev not set), returns None
    so FastAPI serves the pre-built frontend. In development mode, launches
    the Vite dev server as before.

    Args:
        verbose: If True, show console window with output (Windows only)

    Returns:
        Popen process object, or None if production mode or failed
    """
    dev_mode = "--dev" in sys.argv

    if dev_mode:
        print_info("Development mode (--dev): launching Vite dev server")
    else:
        dist_index = Path.cwd() / "frontend" / "dist" / "index.html"
        if dist_index.exists():
            api_port, _ = get_config_ports()
            print_success("Production frontend detected (frontend/dist/)")
            print_info(f"Frontend served by FastAPI on port {api_port}")
            return None

    try:
        frontend_dir = Path.cwd() / "frontend"

        if not frontend_dir.exists():
            print_warning("Frontend directory not found - skipping frontend")
            return None

        # Get full path to npm executable (required for Windows subprocess)
        npm_executable = shutil.which("npm")
        if not npm_executable:
            print_warning("npm not found in PATH - skipping frontend server")
            return None

        # Run `npm ci` if node_modules is missing OR package-lock.json is newer than
        # the install marker (deps were updated since the last install). `npm ci`
        # is read-only against package-lock.json: it installs exactly what's locked
        # and refuses to mutate the lockfile, so a `git pull` of new deps never
        # leaves a dirty working tree on a shared clone. If package.json
        # and the lockfile drift apart, `npm ci` errors out -- that's the desired
        # signal to fix upstream, not a silent local mutation.
        node_modules_marker = frontend_dir / "node_modules" / ".package-lock.json"
        package_lock = frontend_dir / "package-lock.json"
        needs_install = not node_modules_marker.exists() or (
            package_lock.exists() and package_lock.stat().st_mtime > node_modules_marker.stat().st_mtime
        )
        if needs_install:
            print_info("Installing frontend dependencies (npm ci)...")
            subprocess.run([npm_executable, "ci"], cwd=str(frontend_dir), check=True)

        # Configure process creation for verbose mode
        popen_kwargs = {
            "cwd": str(frontend_dir),
        }

        if verbose:
            if platform.system() == "Windows":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
                print_success("Frontend server will open in new console window")
            else:
                print_success("Frontend output will stream to this terminal (verbose mode)")
        else:
            # Background mode: hide output for quiet startup
            logs_dir = Path.cwd() / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            fe_stdout: IO[str] = _log_file_stack.enter_context(
                open(logs_dir / "frontend_stdout.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115
            )
            fe_stderr: IO[str] = _log_file_stack.enter_context(
                open(logs_dir / "frontend_stderr.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115
            )
            popen_kwargs["stdout"] = fe_stdout
            popen_kwargs["stderr"] = fe_stderr

        # Start frontend server (use full path to npm on Windows)
        process = subprocess.Popen([npm_executable, "run", "dev"], **popen_kwargs)

        print_success(f"Frontend server started (PID: {process.pid})")
        if not verbose:
            print_info(f"Frontend logs: {(Path.cwd() / 'logs' / 'frontend_stdout.log').resolve()!s}")
            print_info(f"Frontend errors: {(Path.cwd() / 'logs' / 'frontend_stderr.log').resolve()!s}")
        return process

    except FileNotFoundError:
        print_warning("npm not found - skipping frontend server")
        return None
    except Exception as e:
        print_error(f"Failed to start frontend server: {e}")
        return None


def _patch_env_from_config() -> None:
    """Reconcile network-derived .env vars from config.yaml on every startup.

    config.yaml is authoritative. For LAN/WAN installs this heals both the
    MISSING and the PRESENT-BUT-WRONG cases of GILJO_PUBLIC_URL (scheme/host/
    port) and VITE_API_URL/VITE_WS_URL (emptied so the frontend resolver uses
    same-origin window.location.origin). Runs before the frontend rebuild so the
    corrected VITE_* values are baked into the bundle. No-op for localhost
    installs and when config.yaml is absent (e.g. SaaS/Railway).
    """
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    try:
        env_text = env_path.read_text(encoding="utf-8")
    except OSError:
        return

    # Only LAN/WAN (non-localhost) installs need reconciliation. config.yaml is
    # authoritative: the installer rewrites it AFTER HTTPS setup (and the admin
    # Network settings update it), whereas .env is written once during install
    # BEFORE HTTPS exists -- so on a LAN/WAN box it can carry a stale http://
    # GILJO_PUBLIC_URL and (on pre-fix installs) an absolute VITE_API_URL pointing
    # at localhost. We heal BOTH the missing and the present-but-wrong cases here,
    # before the frontend is (re)built, so the corrected VITE_* values bake into
    # the bundle. No-op for localhost installs and when config.yaml is absent
    # (e.g. SaaS/Railway runs uvicorn api.app:app directly and never calls this).
    external_host = _get_external_host()
    if not external_host or external_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return

    ssl_enabled = get_ssl_enabled()
    api_port, _ = get_config_ports()
    proto = "https" if ssl_enabled else "http"
    desired = {
        # Agent-facing MCP/download links must match the served scheme/host/port.
        "GILJO_PUBLIC_URL": f"{proto}://{external_host}:{api_port}",
        # Empty -> the frontend resolver uses same-origin window.location.origin
        # (ADR-001), which is correct and immune to host/scheme drift on LAN.
        "VITE_API_URL": "",
        "VITE_WS_URL": "",
    }

    lines = env_text.splitlines()
    seen = set()
    changed = False
    for idx, line in enumerate(lines):
        for key, want in desired.items():
            if line.startswith(key + "="):
                seen.add(key)
                if line[len(key) + 1 :].strip() != want:
                    lines[idx] = key + "=" + want
                    os.environ[key] = want
                    changed = True
                    print_info(f"Reconciled .env {key} -> {want or '(empty: same-origin)'}")
    for key in (k for k in desired if k not in seen):
        lines.append(key + "=" + desired[key])
        os.environ[key] = desired[key]
        changed = True
        print_info(f"Added .env {key} -> {desired[key] or '(empty: same-origin)'}")

    if changed:
        try:
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print_success("Reconciled .env network URLs from config.yaml")
        except OSError as e:
            print_warning(f"Could not patch .env: {e}")


def run_database_migrations() -> bool:
    """
    Run database migrations using Alembic.

    Returns:
        True if migrations are successful, False otherwise
    """
    print_header("Running Database Migrations")

    # Bridge old migration revisions to baseline_v36 before running alembic
    _check_and_stamp_migration_version()

    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=True,
            timeout=300,  # 5 minute timeout
        )
        print_success("Database migrations successful")
        return True
    except subprocess.TimeoutExpired:
        print_error("Database migrations timed out (exceeded 5 minutes)")
        return False
    except subprocess.CalledProcessError as e:
        print_error(f"Database migrations failed with return code {e.returncode}")
        if e.stderr:
            print_error(f"Error details: {e.stderr}")
        return False
    except Exception as e:
        print_error(f"Unexpected error during database migrations: {e}")
        return False


def resolve_ssl_decision(no_ssl: bool = False) -> bool:
    """Resolve the effective SSL decision and propagate it to the run_api subprocess.

    Called by run_startup() Step 6. Extracted as a named function so regression
    tests can call it directly (rather than re-implementing the logic inline),
    ensuring the actual decision-and-env-var code is exercised (BE-5042 pattern).

    Sets os.environ["GILJO_FORCE_HTTP"]="1" when HTTP is forced so run_api reads it
    and skips all SSL config resolution (MISMATCH-1/INF-6040). Clears any stale
    value when HTTPS is genuinely enabled.

    Args:
        no_ssl: True when --no-ssl flag was passed (override any ssl_enabled config).

    Returns:
        Effective ssl_enabled value (False means HTTP mode will be used).
    """
    ssl_enabled = get_ssl_enabled() and not no_ssl
    if not ssl_enabled:
        os.environ["GILJO_FORCE_HTTP"] = "1"
    else:
        os.environ.pop("GILJO_FORCE_HTTP", None)  # Clear any stale value from a prior run
    return ssl_enabled


# ---------------------------------------------------------------------------
# Pre-boot consistency gate (INF-0004 sub-task #3)
#
# After a fresh install or an upgrade, refuse to start the server if the install
# is in a half-finished / drifted state that would serve a broken product. Each
# check degrades to "no problem reported" on any internal error, so the gate can
# only ever ADD a clear refusal on a genuinely-detected inconsistency, never wedge
# an otherwise-healthy boot. The wording targets a non-developer customer.
# ---------------------------------------------------------------------------

# Runtime packages whose absence means "dependencies did not install". Same spirit
# as install_requirements()'s critical_packages, kept as a module constant so the
# pre-boot consistency gate (startup.verify_install_consistency) and tests share
# one source of truth.
_CRITICAL_IMPORT_MODULES = (
    "fastapi",
    "sqlalchemy",
    "psycopg2",
    "dotenv",
    "yaml",
    "alembic",
    "uvicorn",
    "click",
)


def _missing_critical_imports() -> list[str]:
    """Return the critical runtime modules that fail to import (empty = all OK)."""
    import importlib

    missing = []
    for module_name in _CRITICAL_IMPORT_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append(module_name)
    return missing


def _frontend_consistency_problem(frontend_dir: Path) -> str | None:
    """Return a problem string if the built frontend is missing or stale, else None.

    'Stale' = dist/index.html older than package.json, i.e. sources changed since the
    last build. Returns None when there is no frontend to serve (no package.json).
    """
    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        return None  # no frontend in this tree — nothing to verify
    index_html = frontend_dir / "dist" / "index.html"
    if not index_html.exists():
        return "the web interface was not built (frontend/dist/index.html is missing)"
    try:
        if index_html.stat().st_mtime < package_json.stat().st_mtime:
            return "the web interface is out of date (it was built before the latest update)"
    except OSError:
        return None  # cannot stat — degrades to no-issue-reported
    return None


def _alembic_revision_drift() -> tuple[str | None, list[str]] | None:
    """Return (current_revision, [code_head(s)]) if the DB revision != code head, else None.

    Degrades to no-drift-reported: returns None on any error or when the comparison
    cannot be made safely (no DB URL, SaaS mode handled by the caller, etc.). Reads the
    CE migration head from the static alembic.ini (version_locations = migrations/versions)
    so it never runs env.py and never picks up a SaaS-only chain.
    """
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine

        ini_path = Path.cwd() / "alembic.ini"
        if not ini_path.exists():
            return None
        script = ScriptDirectory.from_config(Config(str(ini_path)))
        heads = set(script.get_heads())
        if not heads:
            return None

        url = _get_database_url()
        if not url:
            return None
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                current = MigrationContext.configure(conn).get_current_revision()
        finally:
            engine.dispose()

        if current not in heads:
            return (current, sorted(heads))
        return None
    except Exception:
        return None


def verify_install_consistency(
    frontend_dir: Path | None = None,
    *,
    dev_mode: bool = False,
    enforce_frontend: bool = True,
    check_alembic: bool = True,
) -> list[str]:
    """Run the three pre-boot consistency checks and return a list of problems.

    An empty list means the install looks consistent. Each problem is a plain-English
    phrase suitable for a non-developer. See module-level note for the fail-open policy.
    """
    problems: list[str] = []

    missing = _missing_critical_imports()
    if missing:
        problems.append("some Python dependencies are missing or failed to install (" + ", ".join(missing) + ")")

    # SaaS runs the saas_versions chain; the CE head read from alembic.ini would not
    # match, so skip the revision check there (this gate is CE-scoped).
    if check_alembic and os.getenv("GILJO_MODE", "") != "saas":
        drift = _alembic_revision_drift()
        if drift is not None:
            current, heads = drift
            head_label = ", ".join(heads)
            problems.append(
                f"the database is out of date (it is at revision {current or 'none'}, "
                f"the code expects {head_label}); run: python -m alembic upgrade head"
            )

    if enforce_frontend and not dev_mode and frontend_dir is not None:
        fe = _frontend_consistency_problem(frontend_dir)
        if fe:
            problems.append(fe)

    return problems


def run_startup(
    check_only: bool = False,
    verbose: bool = False,
    no_browser: bool = False,
    no_migrations: bool = False,
    no_ssl: bool = False,
) -> int:
    """
    Main startup function.

    Args:
        check_only: If True, only check dependencies without starting services
        verbose: If True, show console windows for API/frontend (Windows only)
        no_browser: If True, skip automatic browser launch
        no_migrations: If True, skip automatic database migrations
        no_ssl: If True, force HTTP even if HTTPS is configured

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    print_header("Giljo HQ - Unified Startup v3.0")

    # Step 1: Check dependencies (Python, PostgreSQL, pip)
    if not check_dependencies():
        print_error("Dependency checks failed")
        return 1

    if check_only:
        print_success("All dependency checks passed")
        return 0

    # Step 2: Install requirements
    print_header("Installing Requirements")
    if not install_requirements():
        print_error("Failed to install requirements")
        print_info("Please install manually: pip install -r requirements.txt")
        return 1

    # Register giljo_mcp as importable package (editable install, idempotent)
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except subprocess.CalledProcessError as e:
        print_warning(f"Editable install failed (non-fatal): {e.stderr[:200] if e.stderr else e}")
    except Exception as e:
        print_warning(f"Editable install skipped: {e}")

    # Step 2.9: Patch .env with missing variables derived from config.yaml
    _patch_env_from_config()

    # Step 3: Run database migrations
    if not no_migrations:
        if not run_database_migrations():
            print_error("Database migrations failed")
            return 1
    else:
        print_info("Skipping database migrations as requested")

    # Step 4: Check database connectivity
    print_header("Database Connectivity")
    print_info("Checking database connection...")
    db_success, _db_error = check_database_connectivity()

    if not db_success:
        print_error("Database connectivity check failed")
        print_info("Please ensure PostgreSQL is running and configured correctly")
        return 1

    # Step 4b: Seed default settings (idempotent, non-fatal)
    seed_default_settings()

    # Step 5: Check first-run status
    print_header("Setup Status")
    print_info("Checking setup completion status...")
    is_first_run, _state = check_first_run()

    # Step 6: Get ports and SSL config
    # resolve_ssl_decision() calls get_ssl_enabled() + applies --no-ssl, then
    # sets/clears GILJO_FORCE_HTTP in os.environ so run_api binds the matching
    # scheme (R5/INF-6040). start_api_server() propagates via child_env =
    # {**os.environ} -- no signature change needed.
    api_port, frontend_port = get_config_ports()
    ssl_enabled = resolve_ssl_decision(no_ssl=no_ssl)
    if no_ssl and not ssl_enabled:
        print_warning("SSL disabled via --no-ssl flag (HTTP mode forced)")
    http_proto = "https" if ssl_enabled else "http"

    # BE-6030: tear down any stale prior server tree before (re)starting so only ONE
    # process holds logs/giljo_mcp.log (single-writer guarantee).
    stop_services()

    # Step 7: Check port availability
    print_header("Port Availability")
    print_info(f"Checking API port {api_port}...")
    if not is_port_available(api_port):
        print_warning(f"Port {api_port} is occupied - finding alternative...")
        new_api_port = find_available_port(api_port)
        if new_api_port:
            print_success(f"Using alternative port {new_api_port}")
            api_port = new_api_port
        else:
            print_error("Could not find available port for API")
            return 1

    print_info(f"Checking frontend port {frontend_port}...")
    if not is_port_available(frontend_port):
        print_warning(f"Port {frontend_port} is occupied - finding alternative...")
        new_frontend_port = find_available_port(frontend_port)
        if new_frontend_port:
            print_success(f"Using alternative port {new_frontend_port}")
            frontend_port = new_frontend_port
        else:
            print_warning("Could not find available port for frontend")

    # Step 8: Start services
    print_header("Starting Services")

    if verbose:
        print_info("Verbose mode enabled - services will open in separate console windows")

    # Always rebuild frontend before starting API so static files are current.
    # Must complete before API starts — the API mounts dist/ at init time.
    dev_mode = "--dev" in sys.argv
    frontend_dir = Path.cwd() / "frontend"
    # Set True only when a fresh build actually completed this boot; the post-build
    # consistency gate uses it to know whether to enforce dist freshness (it must
    # NOT enforce it on the "npm missing, run on existing dist" fallback below).
    frontend_built = False
    if not dev_mode and frontend_dir.exists() and (frontend_dir / "package.json").exists():
        npm_cmd = "npm.cmd" if platform.system() == "Windows" else "npm"
        # Verify npm is actually callable BEFORE invoking subprocess.run.
        # Common Windows trap: install.py freshly winget-installed Node in
        # this session, the registry PATH update happened mid-process, but
        # the parent PowerShell that launched startup.py still has the
        # pre-install PATH. Node/npm are installed but invisible until the
        # user opens a new shell. Without this guard, subprocess.run crashes
        # with WinError 2 / FileNotFoundError, masking the real cause.
        if shutil.which(npm_cmd) is None:
            dist_dir = frontend_dir / "dist"
            if dist_dir.exists() and any(dist_dir.iterdir()):
                print_warning(f"{npm_cmd} not found in PATH — skipping frontend rebuild")
                print_info(f"Using existing build at {dist_dir}")
                print_info(
                    "If you just installed Node.js, close this shell and open a "
                    "new one to refresh PATH; the rebuild will run on next startup."
                )
            else:
                print_error(f"{npm_cmd} not found in PATH and no existing frontend build at {frontend_dir / 'dist'}")
                print_error(
                    "If you just installed Node.js, close this shell and open a "
                    "new one to refresh PATH, then re-run: python startup.py"
                )
                return 1
        else:
            print_info("Rebuilding frontend...")
            # Ensure node_modules exist AND match package-lock.json (catches dep upgrades
            # that shipped via `git pull` since the last install). Use `npm ci`
            # (read-only against the lockfile) so production-style restarts never
            # leave a dirty working tree.
            node_modules_marker = frontend_dir / "node_modules" / ".package-lock.json"
            package_lock = frontend_dir / "package-lock.json"
            needs_install = not node_modules_marker.exists() or (
                package_lock.exists() and package_lock.stat().st_mtime > node_modules_marker.stat().st_mtime
            )
            if needs_install:
                print_info("Installing frontend dependencies (npm ci)...")
                ci_result = subprocess.run([npm_cmd, "ci"], cwd=str(frontend_dir), check=False)
                if ci_result.returncode != 0:
                    print_error("Frontend dependency install (npm ci) failed.")
                    print_error("Your install is incomplete. Re-run the installer to repair it:")
                    print_error("    Windows:      irm giljo.ai/install.ps1 | iex")
                    print_error("    Linux/macOS:  curl -fsSL giljo.ai/install.sh | bash")
                    return 1
            # Clean rebuild: nuke previous dist/ and Vite transform cache so
            # `git pull` updates to .vue/.js sources are guaranteed to land
            # in the new bundle on user upgrades. Without this, stale content-
            # hashed chunks can linger in dist/ alongside the new ones, and
            # (rarely) Vite can reuse a cached transform that no longer
            # matches source. ~2s extra; worth it for bulletproof upgrades.
            dist_dir = frontend_dir / "dist"
            vite_cache_dir = frontend_dir / "node_modules" / ".vite"
            for stale in (dist_dir, vite_cache_dir):
                if stale.exists():
                    try:
                        shutil.rmtree(stale)
                    except OSError as exc:
                        print_warning(f"Could not remove {stale}: {exc}")
            build_result = subprocess.run(
                [npm_cmd, "run", "build"],
                cwd=str(frontend_dir),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if build_result.returncode == 0:
                print_success("Frontend build complete")
                frontend_built = True
            else:
                # Hard fail: the clean-rebuild step above already removed the old
                # dist/, so a failed build leaves NO servable frontend -- starting
                # the API now would serve a blank/404 UI. Stop with a repair message
                # the customer can act on, and surface the build output (which was
                # captured) so the real cause is visible, not hidden behind --verbose.
                print_error("Frontend build failed -- the web interface cannot be served.")
                if build_result.stdout:
                    print_error(build_result.stdout[-1500:])
                if build_result.stderr:
                    print_error(build_result.stderr[-1500:])
                print_error("Your install is incomplete. Re-run the installer to repair it:")
                print_error("    Windows:      irm giljo.ai/install.ps1 | iex")
                print_error("    Linux/macOS:  curl -fsSL giljo.ai/install.sh | bash")
                return 1

    # Pre-boot consistency gate (INF-0004 sub-task #3): refuse to start a half-
    # finished / drifted install rather than serving a broken product. Frontend
    # freshness is only enforced when a fresh build actually ran this boot (not on
    # the npm-missing "run on existing dist" fallback above, which already verified
    # an existing build is present).
    consistency_problems = verify_install_consistency(
        frontend_dir=frontend_dir,
        dev_mode=dev_mode,
        enforce_frontend=frontend_built,
    )
    if consistency_problems:
        print_error("Your Giljo HQ install looks incomplete or out of date:")
        for problem in consistency_problems:
            print_error(f"    - {problem}")
        print_error("")
        print_error("Re-run the installer to repair it, then start the server again:")
        print_error("    Windows:      irm giljo.ai/install.ps1 | iex")
        print_error("    Linux/macOS:  curl -fsSL giljo.ai/install.sh | bash")
        return 1

    print_info("Starting API server...")
    # Serialize the spawn so two near-simultaneous launches can't both write
    # api_stdout.log (INF-6023b). Fail-open: the lock never blocks boot.
    with _single_instance_lock():
        api_process = start_api_server(verbose=verbose, api_port=api_port)

    if not api_process:
        print_error("Failed to start API server")
        return 1

    print_info("Starting frontend server...")
    frontend_process = start_frontend_server(verbose=verbose)

    # Step 8.5: Wait for API to be ready before opening browser
    print_header("Waiting for Services")
    api_ready = wait_for_api_ready(api_port, max_attempts=60, interval=0.5, ssl_enabled=ssl_enabled)

    if not api_ready:
        print_warning("API did not respond to health check, but continuing anyway")
        print_warning("You may see connection errors in the browser initially")

    # Step 9: Open browser
    # In production mode (no Vite), browser should point to the API port
    # since FastAPI serves both the API and the frontend static files.
    production_mode = frontend_process is None and (Path.cwd() / "frontend" / "dist" / "index.html").exists()
    browser_port = api_port if production_mode else frontend_port

    print_header("Opening Browser")

    # Determine the correct host for browser URLs based on deployment_context.
    # - localhost / lan: current behavior (network IP if configured, else localhost)
    # - saas-production: no desktop browser; auto-open is suppressed entirely
    deployment_context = get_deployment_context()
    network_host = get_network_ip() or "localhost"

    server_host = network_host

    suppress_browser = deployment_context == "saas-production"

    if no_browser or suppress_browser:
        if suppress_browser:
            print_info("saas-production mode: browser auto-open disabled (operator mode)")
        else:
            print_info("Login to your server to begin setup!")
            print_success(f"Setup URL: {http_proto}://{server_host}:{browser_port}/setup")

        print_header("Welcome to Giljo HQ, a GiljoAI product! -Gil")
    else:
        # Branch order (saas-production → CE first-run → dashboard) lives in the
        # pure helper above so tests and production share one source of truth.
        # saas-production returns None defensively; `suppress_browser` above
        # already short-circuits that mode.
        target_route = _choose_browser_target(deployment_context, is_first_run)
        if target_route is None:
            print_info("saas-production mode: browser auto-open disabled (operator mode)")
        else:
            auto_open_url = f"{http_proto}://{server_host}:{browser_port}{target_route}"
            if target_route == "/welcome":
                print_info("First-run detected - opening welcome setup screen...")
            else:
                print_info("Opening dashboard...")
            open_browser(auto_open_url, delay=2)

    # Step 10: Display status
    mode_label = "PRODUCTION" if production_mode else "DEVELOPMENT"
    print_header(f"Services Running ({mode_label})")
    print_success(f"API Server: {http_proto}://{server_host}:{api_port}")
    print_success(f"API Docs: {http_proto}://{server_host}:{api_port}/docs")

    if production_mode:
        print_success(f"Frontend (Production): {http_proto}://{server_host}:{api_port}")
    elif frontend_process:
        print_success(f"Frontend (Dev): {http_proto}://{server_host}:{frontend_port}")

    # Deployment-context-aware banner extras
    if deployment_context == "saas-production":
        print_info("saas-production mode: operator console only (no auto-open)")

    print_info("\nPress Ctrl+C to stop all services")

    # Wait for processes. The live-log viewer (if --verbose) runs in its own
    # window and tails api_stdout.log independently -- nothing to manage here.
    try:
        api_process.wait()
    except KeyboardInterrupt:
        print_info("\nShutting down services...")
        api_process.terminate()
        if frontend_process:
            frontend_process.terminate()
        print_success("Services stopped")

    return 0


def stop_services() -> int:
    """Stop all running Giljo HQ services by finding and terminating their processes."""
    print_info("Stopping Giljo HQ services...")

    stopped = 0

    # Find and kill API server (run_api.py)
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                [
                    "wmic",
                    "process",
                    "where",
                    "CommandLine like '%run_api.py%' and Name='python.exe'",
                    "get",
                    "ProcessId",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            for line in result.stdout.strip().split("\n")[1:]:
                pid = line.strip()
                if pid.isdigit():
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10, check=False)
                    print_success(f"Stopped API server (PID: {pid})")
                    stopped += 1
        else:
            result = subprocess.run(
                ["pgrep", "-f", "run_api.py"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            for pid in result.stdout.strip().split("\n"):
                if pid.strip().isdigit():
                    subprocess.run(["kill", pid.strip()], capture_output=True, timeout=10, check=False)
                    print_success(f"Stopped API server (PID: {pid.strip()})")
                    stopped += 1
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Find and kill frontend dev server (npm/vite)
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "process", "where", "CommandLine like '%vite%' and Name='node.exe'", "get", "ProcessId"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            for line in result.stdout.strip().split("\n")[1:]:
                pid = line.strip()
                if pid.isdigit():
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10, check=False)
                    print_success(f"Stopped frontend server (PID: {pid})")
                    stopped += 1
        else:
            result = subprocess.run(
                ["pgrep", "-f", "vite"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            for pid in result.stdout.strip().split("\n"):
                if pid.strip().isdigit():
                    subprocess.run(["kill", pid.strip()], capture_output=True, timeout=10, check=False)
                    print_success(f"Stopped frontend server (PID: {pid.strip()})")
                    stopped += 1
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    if stopped == 0:
        print_info("No running GiljoAI services found")
    else:
        print_success(f"Stopped {stopped} service(s)")

    return 0


@click.command()
@click.option("--check-only", is_flag=True, help="Only check dependencies without starting services")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output (show console windows on Windows)")
@click.option("--no-browser", is_flag=True, help="Skip automatic browser launch (show URLs instead)")
@click.option("--no-migrations", is_flag=True, help="Skip automatic database migrations")
@click.option("--no-ssl", is_flag=True, help="Force HTTP even if HTTPS is configured (for Docker/CI/reverse-proxy)")
@click.option("--stop", is_flag=True, help="Stop all running GiljoAI services")
@click.option("--dev", is_flag=True, help="Force development mode (Vite dev server with hot-reload)")
def main(
    check_only: bool, verbose: bool, no_browser: bool, no_migrations: bool, no_ssl: bool, stop: bool, dev: bool
) -> None:
    """
    Giljo HQ - Unified Startup Script

    This script handles the complete startup process for Giljo HQ,
    including dependency checking, database verification, and service launching.

    Production mode is automatic when frontend/dist/ exists.
    Use --dev to force Vite dev server with hot-reload.
    """
    exit_code = 0
    try:
        if stop:
            exit_code = stop_services()
        else:
            exit_code = run_startup(
                check_only=check_only,
                verbose=verbose,
                no_browser=no_browser,
                no_migrations=no_migrations,
                no_ssl=no_ssl,
            )
    except KeyboardInterrupt:
        print_info("\nStartup cancelled by user")
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        if verbose:
            import traceback

            traceback.print_exc()
        exit_code = 1
    finally:
        # Keep window open on error so the user can read the output
        if exit_code != 0:
            print_error("\nStartup failed. Press Enter to close this window...")
            with contextlib.suppress(EOFError):
                input()
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
