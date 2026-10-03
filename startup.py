#!/usr/bin/env python3

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




_log_file_stack = contextlib.ExitStack()
atexit.register(_log_file_stack.close)

_api_job_object: object = None




def ensure_project_virtualenv() -> None:
    try:
        project_root = Path(__file__).resolve().parent
        venv_dir = project_root / "venv"

        if not venv_dir.exists():
            return

        if Path(sys.prefix).resolve() == venv_dir.resolve():
            return

        if platform.system() == "Windows":
            venv_python = venv_dir / "Scripts" / "python.exe"
        else:
            venv_python = venv_dir / "bin" / "python"
            if not venv_python.exists():
                venv_python = venv_dir / "bin" / "python3"

        if not venv_python.exists():
            return

        print("Re-launching Giljo HQ startup inside project virtual environment...")

        result = subprocess.run([str(venv_python), *sys.argv], check=False)
        sys.exit(result.returncode)

    except Exception as e:
        print(f"Warning: Could not activate venv: {e}", file=sys.stderr)
        return


if "pytest" not in sys.modules:
    ensure_project_virtualenv()

import click
from colorama import init


init(autoreset=True)

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


REQUIRED_POSTGRESQL_VERSION = 18
DEFAULT_API_PORT = 7272
DEFAULT_FRONTEND_PORT = 7274
POSTGRESQL_DOWNLOAD_URL = "https://www.postgresql.org/download/"


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    with contextlib.suppress(Exception), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        return result != 0
    return False


def find_available_port(preferred_port: int, max_attempts: int = 10) -> int | None:
    for offset in range(max_attempts):
        port = preferred_port + offset
        if is_port_available(port):
            return port

    return None


def get_config_ports() -> tuple[int, int]:
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

    return DEFAULT_API_PORT, DEFAULT_FRONTEND_PORT


def _get_network_mode() -> str:
    with contextlib.suppress(Exception):
        import yaml

        config_path = Path.cwd() / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
            return config.get("security", {}).get("network", {}).get("mode", "localhost")
    return "localhost"


def get_deployment_context() -> str:
    with contextlib.suppress(Exception):
        import yaml

        config_path = Path.cwd() / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
            return config.get("deployment_context", "localhost")
    return "localhost"


def _get_external_host() -> str:
    with contextlib.suppress(Exception):
        import yaml

        config_path = Path.cwd() / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
            return config.get("services", {}).get("external_host", "") or ""
    return ""


def get_network_ip() -> str | None:
    network_mode = _get_network_mode()

    if network_mode == "localhost":
        return None

    try:
        import yaml

        config_path = Path.cwd() / "config.yaml"

        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)

            external_host = config.get("services", {}).get("external_host")
            if external_host and external_host not in ("localhost", "127.0.0.1", "0.0.0.0"):
                return external_host

            network_ip = config.get("server", {}).get("ip")
            if not network_ip:
                network_ip = config.get("security", {}).get("network", {}).get("initial_ip")

            if network_ip:
                return network_ip

    except Exception as e:
        print_warning(f"Could not read network IP from config.yaml: {e}")

    try:
        import psutil

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
            is_virtual = any(pattern.lower() in interface_name.lower() for pattern in virtual_patterns)
            is_loopback = any(pattern.lower() in interface_name.lower() for pattern in loopback_patterns)

            stats = interface_stats.get(interface_name)
            is_active = stats.isup if stats else False

            for addr in addresses:
                if addr.family == 2:
                    ip = addr.address

                    if not ip.startswith("127.") and not ip.startswith("169.254.") and is_active and not is_loopback:
                        candidates.append({"name": interface_name, "ip": ip, "is_virtual": is_virtual})

        if candidates:
            physical = [c for c in candidates if not c["is_virtual"]]

            if physical:
                selected = physical[0]
                print_info(f"Detected primary network adapter: {selected['name']} ({selected['ip']})")
                return selected["ip"]
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
) -> subprocess.Popen | None:
    try:
        api_script = Path.cwd() / "api" / "run_api.py"

        if not api_script.exists():
            print_error(f"API script not found: {api_script}")
            return None

        venv_python = Path.cwd() / "venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            venv_python = Path.cwd() / "venv" / "bin" / "python"

        if venv_python.exists():
            python_executable = str(venv_python)
        else:
            python_executable = sys.executable

        logs_dir = Path.cwd() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = logs_dir / "api_stdout.log"
        stderr_path = logs_dir / "api_stderr.log"

        giljo_mode = os.environ.get("GILJO_MODE", "")
        _run_stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")  # noqa: DTZ005 -- local wall-clock time for the viewer title

        stdout_fd = os.open(str(stdout_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        stderr_fd = os.open(str(stderr_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)

        child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        popen_kwargs: dict = {
            "cwd": str(Path.cwd()),
            "stdout": stdout_fd,
            "stderr": stderr_fd,
            "env": child_env,
        }

        api_cmd = [python_executable, str(api_script)]
        if api_port is not None:
            api_cmd += ["--port", str(api_port), "--strict-port"]
        process = subprocess.Popen(api_cmd, **popen_kwargs)

        os.close(stdout_fd)
        os.close(stderr_fd)

        if platform.system() == "Windows":
            try:
                from giljo_mcp.process.win_job_object import WindowsJobObject

                _job = WindowsJobObject()
                _job.assign(process.pid)
                global _api_job_object  # noqa: PLW0603
                _api_job_object = _job
            except Exception as job_err:
                print_warning(f"Job Object containment unavailable: {job_err}")

        print_success(f"API server started (PID: {process.pid})")
        print_info(f"API logs: {stdout_path.resolve()!s}")
        print_info(f"API errors: {stderr_path.resolve()!s}")

        if verbose and giljo_mode in ("", "ce"):
            _launch_log_viewer(stdout_path, _run_stamp)

        return process

    except Exception as e:
        print_error(f"Failed to start API server: {e}")
        return None


def start_frontend_server(verbose: bool = False) -> subprocess.Popen | None:
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

        npm_executable = shutil.which("npm")
        if not npm_executable:
            print_warning("npm not found in PATH - skipping frontend server")
            return None

        node_modules_marker = frontend_dir / "node_modules" / ".package-lock.json"
        package_lock = frontend_dir / "package-lock.json"
        needs_install = not node_modules_marker.exists() or (
            package_lock.exists() and package_lock.stat().st_mtime > node_modules_marker.stat().st_mtime
        )
        if needs_install:
            print_info("Installing frontend dependencies (npm ci)...")
            subprocess.run([npm_executable, "ci"], cwd=str(frontend_dir), check=True)

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
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    try:
        env_text = env_path.read_text(encoding="utf-8")
    except OSError:
        return

    external_host = _get_external_host()
    if not external_host or external_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return

    api_port, _ = get_config_ports()
    desired = {
        "GILJO_PUBLIC_URL": f"http://{external_host}:{api_port}",
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
                current = line[len(key) + 1 :].strip()
                if key == "GILJO_PUBLIC_URL" and current.lower().startswith("https://"):
                    continue
                if current != want:
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
    print_header("Running Database Migrations")

    _check_and_stamp_migration_version()

    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
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
    import importlib

    missing = []
    for module_name in _CRITICAL_IMPORT_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append(module_name)
    return missing


def _frontend_consistency_problem(frontend_dir: Path) -> str | None:
    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        return None
    index_html = frontend_dir / "dist" / "index.html"
    if not index_html.exists():
        return "the web interface was not built (frontend/dist/index.html is missing)"
    try:
        if index_html.stat().st_mtime < package_json.stat().st_mtime:
            return "the web interface is out of date (it was built before the latest update)"
    except OSError:
        return None
    return None


def _alembic_revision_drift() -> tuple[str | None, list[str]] | None:
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
    problems: list[str] = []

    missing = _missing_critical_imports()
    if missing:
        problems.append("some Python dependencies are missing or failed to install (" + ", ".join(missing) + ")")

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
) -> int:
    print_header("Giljo HQ - Unified Startup v3.0")

    if not check_dependencies():
        print_error("Dependency checks failed")
        return 1

    if check_only:
        print_success("All dependency checks passed")
        return 0

    print_header("Installing Requirements")
    if not install_requirements():
        print_error("Failed to install requirements")
        print_info("Please install manually: pip install -r requirements.txt")
        return 1

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

    _patch_env_from_config()

    if not no_migrations:
        if not run_database_migrations():
            print_error("Database migrations failed")
            return 1
    else:
        print_info("Skipping database migrations as requested")

    print_header("Database Connectivity")
    print_info("Checking database connection...")
    db_success, _db_error = check_database_connectivity()

    if not db_success:
        print_error("Database connectivity check failed")
        print_info("Please ensure PostgreSQL is running and configured correctly")
        return 1

    seed_default_settings()

    print_header("Setup Status")
    print_info("Checking setup completion status...")
    is_first_run, _state = check_first_run()

    api_port, frontend_port = get_config_ports()
    http_proto = "http"

    stop_services()

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

    print_header("Starting Services")

    if verbose:
        print_info("Verbose mode enabled - services will open in separate console windows")

    dev_mode = "--dev" in sys.argv
    frontend_dir = Path.cwd() / "frontend"
    frontend_built = False
    if not dev_mode and frontend_dir.exists() and (frontend_dir / "package.json").exists():
        npm_cmd = "npm.cmd" if platform.system() == "Windows" else "npm"
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
                print_error("Frontend build failed -- the web interface cannot be served.")
                if build_result.stdout:
                    print_error(build_result.stdout[-1500:])
                if build_result.stderr:
                    print_error(build_result.stderr[-1500:])
                print_error("Your install is incomplete. Re-run the installer to repair it:")
                print_error("    Windows:      irm giljo.ai/install.ps1 | iex")
                print_error("    Linux/macOS:  curl -fsSL giljo.ai/install.sh | bash")
                return 1

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
    with _single_instance_lock():
        api_process = start_api_server(verbose=verbose, api_port=api_port)

    if not api_process:
        print_error("Failed to start API server")
        return 1

    print_info("Starting frontend server...")
    frontend_process = start_frontend_server(verbose=verbose)

    print_header("Waiting for Services")
    api_ready = wait_for_api_ready(api_port, max_attempts=60, interval=0.5)

    if not api_ready:
        print_warning("API did not respond to health check, but continuing anyway")
        print_warning("You may see connection errors in the browser initially")

    production_mode = frontend_process is None and (Path.cwd() / "frontend" / "dist" / "index.html").exists()
    browser_port = api_port if production_mode else frontend_port

    print_header("Opening Browser")

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

    mode_label = "PRODUCTION" if production_mode else "DEVELOPMENT"
    print_header(f"Services Running ({mode_label})")
    print_success(f"API Server: {http_proto}://{server_host}:{api_port}")
    print_success(f"API Docs: {http_proto}://{server_host}:{api_port}/docs")

    if production_mode:
        print_success(f"Frontend (Production): {http_proto}://{server_host}:{api_port}")
    elif frontend_process:
        print_success(f"Frontend (Dev): {http_proto}://{server_host}:{frontend_port}")

    if deployment_context == "saas-production":
        print_info("saas-production mode: operator console only (no auto-open)")

    print_info("\nPress Ctrl+C to stop all services")

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
    print_info("Stopping Giljo HQ services...")

    stopped = 0

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
@click.option("--stop", is_flag=True, help="Stop all running GiljoAI services")
@click.option("--dev", is_flag=True, help="Force development mode (Vite dev server with hot-reload)")
def main(check_only: bool, verbose: bool, no_browser: bool, no_migrations: bool, stop: bool, dev: bool) -> None:
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
        if exit_code != 0:
            print_error("\nStartup failed. Press Enter to close this window...")
            with contextlib.suppress(EOFError):
                input()
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
