#!/usr/bin/env python3

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Giljo HQ - Production Startup Script (DEPRECATED)

DEPRECATED: Use 'python startup.py' instead.
Production mode is now automatic when frontend/dist/ exists.
Use 'python startup.py --dev' to force development mode.

This script is kept for backward compatibility and delegates to startup.py.
"""

import atexit
import contextlib
import platform
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import click
from colorama import Fore, Style, init

# Import helper functions from startup.py
from startup import (
    check_database_connectivity,
    check_dependencies,
    check_first_run,
    get_config_ports,
    get_network_ip,
    install_requirements,
    is_port_available,
    print_error,
    print_header,
    print_info,
    print_success,
    print_warning,
    run_database_migrations,
    wait_for_api_ready,
)


# ExitStack for managing log file handles that must outlive the function scope
# (passed to subprocess.Popen). Registered with atexit so handles close on exit.
_log_file_stack = contextlib.ExitStack()
atexit.register(_log_file_stack.close)

# Initialize colorama for cross-platform colored output
init(autoreset=True)


def start_api_server(verbose: bool = False) -> subprocess.Popen | None:
    """
    Start the API server (same as dev mode).

    Args:
        verbose: If True, show console window with output (Windows only)

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

        # Configure process creation for verbose mode
        popen_kwargs = {
            "cwd": str(Path.cwd()),
        }

        if verbose:
            if platform.system() == "Windows":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
                print_success("API server will open in new console window")
            else:
                print_success("API server output will stream to this terminal (verbose mode)")
        else:
            # Background mode: hide output for quiet startup
            logs_dir = Path.cwd() / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            api_stdout = _log_file_stack.enter_context(
                open(logs_dir / "api_stdout.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115
            )
            api_stderr = _log_file_stack.enter_context(
                open(logs_dir / "api_stderr.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115
            )
            popen_kwargs["stdout"] = api_stdout
            popen_kwargs["stderr"] = api_stderr

        # Start API server
        process = subprocess.Popen([python_executable, str(api_script)], **popen_kwargs)

        print_success(f"API server started (PID: {process.pid})")
        if not verbose:
            print_info(f"API logs: {(Path.cwd() / 'logs' / 'api_stdout.log').resolve()!s}")
            print_info(f"API errors: {(Path.cwd() / 'logs' / 'api_stderr.log').resolve()!s}")
        return process

    except Exception as e:
        print_error(f"Failed to start API server: {e}")
        return None


def start_frontend_production_server(verbose: bool = False) -> subprocess.Popen | None:
    """
    Start the frontend PRODUCTION server using serve_frontend.py.

    This serves pre-built files from frontend/dist/ directory.

    Args:
        verbose: If True, show console window with output (Windows only)

    Returns:
        Popen process object or None if failed
    """
    try:
        serve_script = Path.cwd() / "serve_frontend.py"
        frontend_dist = Path.cwd() / "frontend" / "dist"

        # Check if production build exists
        if not frontend_dist.exists():
            print_error("Production build not found!")
            print_error(f"Missing directory: {frontend_dist}")
            print_info("Run the following commands to build:")
            print_info("  cd frontend")
            print_info("  npm run build")
            return None

        # Check if serve_frontend.py exists
        if not serve_script.exists():
            print_error(f"Production server script not found: {serve_script}")
            return None

        # Determine Python executable
        python_executable = sys.executable

        # Configure process creation for verbose mode
        popen_kwargs = {
            "cwd": str(Path.cwd()),
        }

        if verbose:
            if platform.system() == "Windows":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
                print_success("Frontend production server will open in new console window")
            else:
                print_success("Frontend output will stream to this terminal (verbose mode)")
        else:
            # Background mode: hide output for quiet startup
            logs_dir = Path.cwd() / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            fe_stdout = _log_file_stack.enter_context(
                open(logs_dir / "frontend_prod.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115
            )
            fe_stderr = fe_stdout  # Use same file for stderr
            popen_kwargs["stdout"] = fe_stdout
            popen_kwargs["stderr"] = fe_stderr

        # Start production frontend server
        process = subprocess.Popen([python_executable, str(serve_script)], **popen_kwargs)

        print_success(f"Frontend production server started (PID: {process.pid})")
        print_success("Serving pre-built files from frontend/dist/")
        if not verbose:
            print_info(f"Frontend logs: {(Path.cwd() / 'logs' / 'frontend_prod.log').resolve()!s}")
        return process

    except Exception as e:
        print_error(f"Failed to start frontend production server: {e}")
        return None


def open_browser(url: str, delay: int = 3) -> None:
    """
    Open browser to specified URL after a delay.

    Args:
        url: URL to open
        delay: Delay in seconds before opening
    """
    try:
        print_info(f"Opening browser to {url} in {delay} seconds...")
        time.sleep(delay)
        webbrowser.open(url)
        print_success("Browser opened")
    except Exception as e:
        print_error(f"Failed to open browser: {e}")
        print_info(f"Please manually open: {url}")


def run_production_startup(
    check_only: bool = False, verbose: bool = False, no_browser: bool = False, no_migrations: bool = False
) -> int:
    """
    Main production startup function.

    Args:
        check_only: If True, only check dependencies without starting services
        verbose: If True, show console windows for API/frontend (Windows only)
        no_browser: If True, skip automatic browser launch
        no_migrations: If True, skip automatic database migrations

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    print_header("Giljo HQ - PRODUCTION Startup v3.0")
    print_warning("Running in PRODUCTION MODE")
    print_info("Frontend will serve pre-built files from frontend/dist/")

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

    # Step 2.5: Run database migrations
    if not no_migrations:
        if not run_database_migrations():
            print_error("Database migrations failed")
            return 1
    else:
        print_info("Skipping database migrations as requested")

    # Step 3: Check database connectivity
    print_header("Database Connectivity")
    print_info("Checking database connection...")
    db_success, _db_error = check_database_connectivity()

    if not db_success:
        print_error("Database connectivity check failed")
        print_info("Please ensure PostgreSQL is running and configured correctly")
        return 1

    # Step 4: Check first-run status
    print_header("Setup Status")
    print_info("Checking setup completion status...")
    is_first_run, _state = check_first_run()

    # Step 5: Get ports and protocol from config
    api_port, frontend_port = get_config_ports()
    try:
        import yaml as _yaml

        _cfg_path = Path("config.yaml")
        _cfg_data = _yaml.safe_load(_cfg_path.read_text()) if _cfg_path.exists() else {}
        _ssl_on = _cfg_data.get("features", {}).get("ssl_enabled", False)
    except (OSError, ValueError, ImportError):
        _ssl_on = False
    http_proto = "https" if _ssl_on else "http"

    # Step 6: Check port availability
    print_header("Port Availability")
    print_info(f"Checking API port {api_port}...")
    if not is_port_available(api_port):
        print_error(f"Port {api_port} is occupied!")
        print_info("Stop the existing process or use a different port")
        return 1

    print_info(f"Checking frontend port {frontend_port}...")
    if not is_port_available(frontend_port):
        print_error(f"Port {frontend_port} is occupied!")
        print_info("Stop the existing process or use a different port")
        return 1

    # Step 7: Start services
    print_header("Starting Services")

    if verbose:
        print_info("Verbose mode enabled - services will open in separate console windows")

    print_info("Starting API server...")
    api_process = start_api_server(verbose=verbose)

    if not api_process:
        print_error("Failed to start API server")
        return 1

    print_info("Starting frontend production server...")
    frontend_process = start_frontend_production_server(verbose=verbose)

    if not frontend_process:
        print_error("Failed to start frontend production server")
        print_info("Make sure you've built the frontend: cd frontend && npm run build")
        # Terminate API server since frontend failed
        api_process.terminate()
        return 1

    # Step 7.5: Wait for API to be ready before opening browser
    print_header("Waiting for Services")
    api_ready = wait_for_api_ready(api_port, max_attempts=60, interval=0.5)

    if not api_ready:
        print_warning("API did not respond to health check, but continuing anyway")
        print_warning("You may see connection errors in the browser initially")

    # Step 8: Open browser
    print_header("Opening Browser")

    if no_browser:
        # User chose not to auto-launch browser
        network_ip = get_network_ip()
        if network_ip:
            print_info("Access the application via network IP:")
            print_success(f"Network URL: {http_proto}://{network_ip}:{frontend_port}")
        print_success(f"Localhost URL: {http_proto}://localhost:{frontend_port}")

        print_header("Giljo HQ - Production Mode Active")
    else:
        # Auto-launch browser
        network_ip = get_network_ip()

        if is_first_run:
            # Open welcome setup
            target_route = "/welcome"
            if network_ip:
                setup_url = f"{http_proto}://{network_ip}:{frontend_port}{target_route}"
                print_info("First-run detected - opening welcome setup at network IP...")
            else:
                setup_url = f"{http_proto}://localhost:{frontend_port}{target_route}"
                print_info("First-run detected - opening welcome setup...")

            open_browser(setup_url, delay=2)
        else:
            # Open dashboard
            if network_ip:
                dashboard_url = f"{http_proto}://{network_ip}:{frontend_port}"
                print_info("Opening dashboard at network IP...")
            else:
                dashboard_url = f"{http_proto}://localhost:{frontend_port}"
                print_info("Opening dashboard...")

            open_browser(dashboard_url, delay=2)

    # Step 9: Display status
    print_header("Services Running (PRODUCTION MODE)")
    print_success(f"API Server: {http_proto}://localhost:{api_port}")
    print_success(f"API Docs: {http_proto}://localhost:{api_port}/docs")
    print_success(f"Frontend (Production): {http_proto}://localhost:{frontend_port}")

    network_ip = get_network_ip()
    if network_ip:
        print_success(f"Network Access: {http_proto}://{network_ip}:{frontend_port}")

    print_info("\nPress Ctrl+C to stop all services")

    # Wait for processes
    try:
        api_process.wait()
    except KeyboardInterrupt:
        print_info("\nShutting down services...")
        api_process.terminate()
        if frontend_process:
            frontend_process.terminate()
        print_success("Services stopped")

    return 0


@click.command()
@click.option("--check-only", is_flag=True, help="Only check dependencies without starting services")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output (show console windows on Windows)")
@click.option("--no-browser", is_flag=True, help="Skip automatic browser launch (show URLs instead)")
@click.option("--no-migrations", is_flag=True, help="Skip automatic database migrations")
def main(check_only: bool, verbose: bool, no_browser: bool, no_migrations: bool) -> None:
    """
    Giljo HQ - Production Startup Script

    Launches Giljo HQ in PRODUCTION mode with pre-built frontend.

    DEPRECATED: Use 'python startup.py' instead.
    """
    print(f"\n{Fore.YELLOW}{Style.BRIGHT}WARNING: startup_prod.py is deprecated.{Style.RESET_ALL}")  # noqa: T201
    print(  # noqa: T201
        f"{Fore.YELLOW}Use 'python startup.py' instead — production mode is automatic when frontend/dist/ exists.{Style.RESET_ALL}"
    )
    print(f"{Fore.YELLOW}Use 'python startup.py --dev' to force Vite dev server.{Style.RESET_ALL}\n")  # noqa: T201

    try:
        exit_code = run_production_startup(
            check_only=check_only, verbose=verbose, no_browser=no_browser, no_migrations=no_migrations
        )
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print_info("\nStartup cancelled by user")
        sys.exit(0)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
