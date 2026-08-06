#!/usr/bin/env python3

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Run the Giljo HQ REST API server
"""

import argparse
import atexit
import contextlib
import logging
import logging.handlers
import os
import queue
import sys
from pathlib import Path
from typing import ClassVar

import uvicorn


# ---------------------------------------------------------------------------
# Module-level async-safe logging infrastructure (INF-5092)
#
# A bare StreamHandler on the root logger is synchronous: every log emit
# holds the GIL and blocks the calling thread.  In uvicorn's single-threaded
# async model that means every access-log line can stall the event loop if
# the underlying fd stalls (e.g. a full pipe buffer or a dead parent process).
#
# Fix: the root logger gets ONLY a QueueHandler.  The real I/O handlers
# (RotatingFileHandler + StreamHandler) live inside a QueueListener on a
# dedicated background thread.  Log emits from the event loop thread are now
# O(1) lock-free enqueues; the I/O latency is absorbed by the listener thread.
# ---------------------------------------------------------------------------

_log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
_log_listener: logging.handlers.QueueListener | None = None
# Registered to atexit exactly once. _configure_logging can run more than once
# (server start, and several tests call it directly); without single-owner
# teardown each call left an orphaned QueueListener monitor thread on the shared
# _log_queue, and multiple atexit stop() calls then deadlocked joining a monitor
# whose sentinel was consumed by a sibling — hanging the process at exit.
_log_listener_atexit_registered = False


def _stop_log_listener() -> None:
    """atexit hook: stop the active QueueListener (idempotent, single-owner)."""
    global _log_listener  # noqa: PLW0603
    listener = _log_listener
    _log_listener = None
    if listener is not None:
        # best-effort shutdown; never raise at interpreter exit
        with contextlib.suppress(Exception):
            listener.stop()


# Ensure project root is on sys.path so uvicorn can resolve "api.app:app"
# (api/ is not a pip package — it needs the project root on sys.path)
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import PortManager for centralized port management
try:
    from giljo_mcp.port_manager import get_port_manager

    PORT_MANAGER_AVAILABLE = True
except ImportError:
    PORT_MANAGER_AVAILABLE = False
    logging.warning("PortManager not available, using fallback port detection")


def find_available_port(preferred_port: int) -> int:
    """Find an available port, starting with the preferred one.

    Args:
        preferred_port: The preferred port number

    Returns:
        Available port number

    Raises:
        RuntimeError: If no available port can be found
    """
    import socket

    # Check if preferred port is available
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", preferred_port))
            if result != 0:  # Port is available
                return preferred_port
    except OSError:  # Socket operations can fail
        pass  # nosec B110 - best effort port check

    # Try some alternative ports
    alternatives = [7273, 8747, 8823, 9456, 9789]
    for port in alternatives:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex(("127.0.0.1", port))
                if result != 0:  # Port is available
                    logging.warning(f"Port {preferred_port} is occupied, using alternative port {port}")
                    return port
        except OSError:
            continue  # nosec B112 - best effort port scan

    raise RuntimeError(f"Could not find available port (preferred: {preferred_port})")


def _strict_port_available(host: str, port: int) -> bool:
    """True if nothing is currently listening on host:port.

    Used by --strict-port (set when startup.py launches this process) to
    fail-fast instead of roaming to an alternative port. A losing duplicate
    that silently roamed to 7273 used to keep running and write the same
    redirected logs/api_stdout.log as the real server -- two writers at
    independent offsets NUL-padded the file and froze the live viewer
    (INF-6023b root cause). connect_ex probe matches find_available_port's
    convention and works reliably on Windows (the dogfood platform).

    A port still in TIME_WAIT (just-stopped server) probes as available, so a
    fast deliberate restart is not blocked; only an *active* listener blocks.
    """
    import socket

    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            return sock.connect_ex((probe_host, port)) != 0
    except OSError:
        return True  # probe itself failed -- do not block startup on a flaky check


def get_port_from_sources() -> int:
    """Get port from multiple sources in priority order

    Priority:
    1. GILJO_PORT environment variable
    2. config.yaml (via PortManager)
    3. Default 7272

    Also checks if port is available and finds alternative if needed.

    Returns:
        Available port number
    """
    if PORT_MANAGER_AVAILABLE:
        try:
            # Use PortManager for proper port configuration
            manager = get_port_manager()
            # Get port with availability check
            port = manager.get_api_port(check_availability=True)
            logging.info(f"Using port {port} from PortManager")
            return port
        except (ImportError, RuntimeError, ValueError, OSError) as e:
            logging.warning(f"PortManager failed, using fallback: {e}")

    # Fallback to environment variable or default
    env_port = os.environ.get("GILJO_PORT") or os.environ.get("GILJO_API_PORT")
    if env_port:
        try:
            port = int(env_port)
            if 1024 <= port <= 65535:
                logging.info(f"Using port {port} from environment variable")
                return port
        except ValueError:
            logging.warning(f"Invalid port value in environment: {env_port}")

    # Ultimate fallback
    default_port = 7272
    logging.info(f"Using default port {default_port}")
    return default_port


def get_default_host() -> str:
    """Get default host for API server binding.

    Bind address is derived from the install-time network choice:
    - Localhost installs: 127.0.0.1 (HTTP, no network exposure)
    - LAN/WAN installs: 0.0.0.0 (plain HTTP by default; optional bring-your-own-cert HTTPS)

    Priority:
    1. services.api.host from config.yaml (set by installer)
    2. Default: "0.0.0.0" (backward compat for pre-0843 installs)

    Returns:
        Host to bind to
    """
    try:
        from giljo_mcp._config_io import read_config

        config = read_config()
        configured_host = config.get("services", {}).get("api", {}).get("host")
        if configured_host:
            logging.info(f"Using configured API host: {configured_host}")
            return configured_host

        logging.info("No host configured, defaulting to 0.0.0.0")
        return "0.0.0.0"
    except (OSError, ValueError, KeyError) as e:
        logging.warning(f"Could not read config: {e}, defaulting to 0.0.0.0")

    return "0.0.0.0"


def _configure_logging(log_level: int = logging.INFO) -> None:
    """
    Wire up async-safe logging for the API process (INF-5092).

    Called once by ``main()`` (and by tests that need the new config).

    Architecture
    ~~~~~~~~~~~~
    - Root logger gets a single ``QueueHandler`` (+ ``_NoiseFilter``).
      All handlers that were on the root logger are cleared first.
    - A ``QueueListener`` runs on a background thread and holds the real
      I/O handlers:
        * ``SafeRotatingFileHandler`` -> ``logs/giljo_mcp.log`` (10 MB x 5, UTF-8)
        * ``StreamHandler``           → stdout (colored, for live tailing)
    - ``uvicorn``, ``uvicorn.access``, ``uvicorn.error``, ``fastapi`` loggers
      have their handlers cleared and ``propagate=True`` so their records
      flow through the root QueueHandler.
    - The listener is stopped cleanly via ``atexit``.

    Live-tailing — ALWAYS tail ``api_stdout.log``, NEVER ``giljo_mcp.log``::

        Get-Content -Wait logs\\api_stdout.log   # PowerShell
        tail -f logs/api_stdout.log              # bash

    Windows gotcha (BE-6030): do NOT tail ``logs/giljo_mcp.log`` directly. A
    reader holding that file open blocks the rotation rename, which on Windows
    raises PermissionError (WinError 32). ``SafeRotatingFileHandler`` now
    swallows that error so the logging path no longer crashes, but the rotation
    is silently skipped while the tail is open. Tail ``logs/api_stdout.log``
    instead — it carries the same records and is not the rotation target.
    """
    global _log_listener, _log_listener_atexit_registered  # noqa: PLW0603

    # Idempotent: stop any previously-started listener so repeated calls never
    # accumulate monitor threads on the shared _log_queue (the exit-hang cause).
    if _log_listener is not None:
        # best-effort teardown of the prior listener
        with contextlib.suppress(Exception):
            _log_listener.stop()
        _log_listener = None

    # ------------------------------------------------------------------
    # Real I/O handlers (run on the listener thread, never the event loop)
    # ------------------------------------------------------------------
    project_root = Path(__file__).resolve().parent.parent
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    colored_formatter = _ColoredFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    from giljo_mcp.logging import SafeRotatingFileHandler

    file_handler = SafeRotatingFileHandler(
        filename=str(logs_dir / "giljo_mcp.log"),
        maxBytes=10 * 1024 * 1024,  # 10 MB x 5 — canonical size, matches the other two handler call sites
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(log_level)

    # Colored stream -> stdout (matches the docstring + the api_stdout.log tail
    # target). logging.StreamHandler() defaults to stderr, which previously sent
    # the colored output to api_stderr.log and left api_stdout.log nearly empty
    # despite the documented "tail api_stdout.log". Pin to stdout explicitly.
    #
    # Defensive line-buffering (INF-6022). logging.StreamHandler already flushes
    # after every record, so the colored stream reaches api_stdout.log per-line
    # even when startup.py redirects this (non-tty) stdout to that file -- the
    # stream was never the staleness cause. This reconfigure is belt-and-
    # suspenders: it keeps stdout line-flushed if a future handler swap ever
    # bypasses StreamHandler's flush. The actual --verbose staleness fix lives in
    # startup.py, which truncates api_stdout.log on each launch so the viewer
    # shows the current session from the fresh-start banner instead of replaying
    # every past run. Buffering mode only -- the async-safe logging path
    # (QueueHandler/QueueListener) is untouched, so the INF-5092 wedge stays fixed.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(colored_formatter)
    stream_handler.setLevel(log_level)

    noise_filter = _NoiseFilter()
    file_handler.addFilter(noise_filter)
    stream_handler.addFilter(noise_filter)

    # ------------------------------------------------------------------
    # Start the listener (background thread, handles real I/O)
    # ------------------------------------------------------------------
    _log_listener = logging.handlers.QueueListener(
        _log_queue,
        file_handler,
        stream_handler,
        respect_handler_level=True,
    )
    _log_listener.start()
    # Register the single-owner stop hook exactly once (not per call / per
    # listener instance) so atexit never joins a stale monitor on the shared queue.
    if not _log_listener_atexit_registered:
        atexit.register(_stop_log_listener)
        _log_listener_atexit_registered = True

    # ------------------------------------------------------------------
    # Root logger: only a QueueHandler (enqueue, never block)
    # ------------------------------------------------------------------
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    queue_handler = logging.handlers.QueueHandler(_log_queue)
    queue_handler.addFilter(noise_filter)
    root_logger.addHandler(queue_handler)

    # ------------------------------------------------------------------
    # Sub-loggers: clear handlers, let records propagate to root
    # ------------------------------------------------------------------
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        sub_logger = logging.getLogger(logger_name)
        sub_logger.handlers.clear()
        sub_logger.propagate = True
        sub_logger.setLevel(log_level)


class _ColoredFormatter(logging.Formatter):
    """Colored log output for terminal readability."""

    COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET: ClassVar[str] = "\033[0m"
    BOLD: ClassVar[str] = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        levelname = f"{self.BOLD}{color}{record.levelname:<8}{self.RESET}"
        timestamp = self.formatTime(record, self.datefmt)
        name = f"\033[34m{record.name}\033[0m"  # Blue for logger name
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        exc = f"\n{record.exc_text}" if record.exc_text else ""
        return f"{timestamp} - {name} - {levelname} - {color}{message}{self.RESET}{exc}"


class _NoiseFilter(logging.Filter):
    """Filter to exclude health check, ping, and static asset log noise."""

    EXCLUDE_PATTERNS: ClassVar[list[str]] = [
        "GET /health",
        "GET /api/v1/health",
        "WebSocket ping",
        "WebSocket pong",
        "keepalive",
        "keep-alive",
        "heartbeat",
        "/ws/",
        "ping-pong",
        "GET /assets/",
        "GET /index.html",
        "GET /favicon.ico",
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        return not any(p.lower() in message for p in self.EXCLUDE_PATTERNS)


def main():
    """Main entry point for running the API server"""
    parser = argparse.ArgumentParser(description="Giljo HQ REST API Server")
    parser.add_argument("--host", default=None, help="Host to bind to (default: auto-detect from config)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to (default: auto-detect from config/env)")
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Bind the chosen port exactly or exit (no alternative-port roaming). Set by startup.py to "
        "prevent a losing duplicate from lingering as a 2nd log writer (INF-6023b).",
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Logging level (default: info)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging (equivalent to --log-level debug)",
    )
    parser.add_argument("--ssl-keyfile", help="SSL key file for HTTPS")
    parser.add_argument("--ssl-certfile", help="SSL certificate file for HTTPS")

    args = parser.parse_args()

    # Override log level if verbose flag is set
    if args.verbose:
        args.log_level = "debug"

    # Determine host with mode-based default
    if args.host is None:
        args.host = get_default_host()

    # Determine port with fallback logic
    if args.port is None:
        args.port = get_port_from_sources()
    elif args.strict_port:
        # INF-6023b: launched by startup.py with an explicit port. Bind exactly
        # this port or exit -- never roam to an alternative. A duplicate that
        # roamed to 7273 used to linger as a 2nd writer on the shared
        # api_stdout.log and corrupt the live viewer. Fail-fast instead.
        if not _strict_port_available(args.host, args.port):
            logging.error(
                "Port %s is already in use; refusing to start a duplicate server (--strict-port). "
                "Another GiljoAI API is already bound -- stop it first or free the port.",
                args.port,
            )
            sys.exit(3)
    else:
        # If port specified on command line, still check if available
        try:
            args.port = find_available_port(args.port)
        except RuntimeError:
            logging.exception("Port error")
            sys.exit(1)

    # Configure async-safe logging (QueueHandler + QueueListener, INF-5092)
    log_level = getattr(logging, args.log_level.upper())
    _configure_logging(log_level=log_level)

    logger = logging.getLogger(__name__)

    from giljo_mcp import __version__ as giljo_version

    # Log startup information
    logger.info("=" * 60)
    logger.info(f"  Giljo HQ REST API v{giljo_version}")
    logger.info("=" * 60)

    logger.info(f"Server binding to {args.host}:{args.port}")
    logger.info(f"Port selection: {'Command line' if args.port else 'Auto-detected'}")
    logger.info(f"Workers: {args.workers}")
    logger.info(f"Auto-reload: {'Enabled' if args.reload else 'Disabled'}")
    logger.info(f"Log level: {args.log_level.upper()}")

    # SSL Configuration Priority:
    # 0. GILJO_FORCE_HTTP=1 (set by startup.py when --no-ssl or certs absent) → skip all SSL
    # 1. Command-line arguments (--ssl-keyfile, --ssl-certfile)
    # 2. config.yaml paths (paths.ssl_cert, paths.ssl_key)
    # 3. Environment variables (SSL_CERT_FILE, SSL_KEY_FILE)
    ssl_config = {}

    # Priority 0: launcher forced HTTP — skip all SSL config resolution.
    # startup.py sets GILJO_FORCE_HTTP=1 when ssl_enabled resolves False
    # (covers --no-ssl, localhost mode, and configured-but-missing certs).
    # This prevents the startup health probe (http) diverging from run_api (https).
    force_http = os.getenv("GILJO_FORCE_HTTP") == "1"
    if force_http:
        logger.info("HTTP mode forced by launcher (GILJO_FORCE_HTTP=1) — SSL skipped")

    # Try command-line arguments first
    if not force_http and args.ssl_keyfile and args.ssl_certfile:
        ssl_config = {"ssl_keyfile": args.ssl_keyfile, "ssl_certfile": args.ssl_certfile}
        logger.info(f"SSL enabled via CLI: {args.ssl_certfile}")

    # Try config.yaml if no CLI args
    if not force_http and not ssl_config:
        try:
            import yaml

            config_path = Path(__file__).parent.parent / "config.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    config = yaml.safe_load(f) or {}

                ssl_enabled = config.get("features", {}).get("ssl_enabled", False)
                ssl_cert = config.get("paths", {}).get("ssl_cert")
                ssl_key = config.get("paths", {}).get("ssl_key")

                if ssl_enabled and ssl_cert and ssl_key:
                    cert_path = Path(ssl_cert)
                    key_path = Path(ssl_key)

                    if cert_path.exists() and key_path.exists():
                        ssl_config = {"ssl_keyfile": str(key_path), "ssl_certfile": str(cert_path)}
                        logger.info(f"SSL enabled via config.yaml: {cert_path}")
                    else:
                        logger.warning("SSL enabled in config but certificate files not found:")
                        if not cert_path.exists():
                            logger.warning(f"  Cert: {cert_path} (not found)")
                        if not key_path.exists():
                            logger.warning(f"  Key:  {key_path} (not found)")
                        logger.info("Falling back to HTTP mode")
        except (OSError, ValueError, ImportError) as e:
            logger.warning(f"Failed to load SSL config from config.yaml: {e}")

    # Try environment variables as last resort
    if not force_http and not ssl_config:
        ssl_cert_env = os.getenv("SSL_CERT_FILE")
        ssl_key_env = os.getenv("SSL_KEY_FILE")
        if ssl_cert_env and ssl_key_env:
            cert_path = Path(ssl_cert_env)
            key_path = Path(ssl_key_env)
            if cert_path.exists() and key_path.exists():
                ssl_config = {"ssl_keyfile": str(key_path), "ssl_certfile": str(cert_path)}
                logger.info(f"SSL enabled via environment: {cert_path}")

    if not ssl_config:
        logger.info("Running in HTTP mode (no SSL configured)")

    logger.info("-" * 60)
    http_proto = "https" if ssl_config else "http"
    ws_proto = "wss" if ssl_config else "ws"
    logger.info("API Endpoints:")
    logger.info(f"  Documentation: {http_proto}://{args.host}:{args.port}/docs")
    logger.info(f"  ReDoc: {http_proto}://{args.host}:{args.port}/redoc")
    logger.info(f"  OpenAPI JSON: {http_proto}://{args.host}:{args.port}/openapi.json")
    logger.info(f"  Health Check: {http_proto}://{args.host}:{args.port}/health")
    logger.info(f"  WebSocket: {ws_proto}://{args.host}:{args.port}/ws/{{client_id}}")
    logger.info("-" * 60)
    logger.info("Available API Routes:")
    logger.info("  /api/v1/projects - Project management")
    logger.info("  /api/v1/agents - Agent control")
    logger.info("  /api/v1/messages - Inter-agent messaging")
    logger.info("  /api/v1/tasks - Task management")
    logger.info("  /api/v1/context - Context and vision documents")
    logger.info("  /api/v1/config - Configuration management")
    logger.info("  /api/v1/stats - Statistics and monitoring")
    logger.info("=" * 60)
    logger.info("Server starting... Ready to accept connections!")
    logger.info("Ping/keepalive messages are filtered from output")
    logger.info("=" * 60)

    try:
        # Run the server
        uvicorn.run(
            "api.app:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            workers=args.workers if not args.reload else 1,  # Can't use multiple workers with reload
            log_level=args.log_level,
            **ssl_config,
        )
    except KeyboardInterrupt:
        logger.info("\nShutting down server...")
    except (RuntimeError, OSError, ImportError):
        logger.exception("Failed to start server")
        sys.exit(1)


if __name__ == "__main__":
    main()
