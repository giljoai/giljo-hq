# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Structured Logging with Error Codes

Production-grade structured logging using structlog as a processing
pipeline on top of stdlib logging.getLogger():
- JSON output for production (machine-parseable)
- Console output for development (human-readable)
- Error code support for quick diagnosis
- File logging with daily rotation (logs/giljo_mcp.log)

Usage:
    import logging
    from giljo_mcp.logging import ErrorCode

    logger = logging.getLogger(__name__)
    logger.info("Processing request for user_id=%s", user_id)

Environment Variables:
    ENVIRONMENT: Set to "production" for JSON output, anything else for console
    LOG_LEVEL: debug, info, warning, error, critical (default: info)
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler as _BaseRotatingFileHandler
from pathlib import Path

import structlog

from .error_codes import ErrorCode, get_error_description


class _McpHeartbeatAccessFilter(logging.Filter):
    """Drop uvicorn.access lines for GET /mcp keepalive polls.

    Uvicorn passes the access tuple via record.args:
    (client_addr, method, full_path, http_version, status_code).
    We suppress only GET requests whose path is exactly /mcp (the streamable
    transport mount). POSTs (real tool calls) and any sub-path pass through.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        method, path = args[1], args[2]
        return not (method == "GET" and path == "/mcp")


# Query params whose values are secrets by design: lifecycle links (password
# reset / account deletion / email change) deliver ?token=<plaintext>, and the
# social OAuth callbacks carry ?code=/?state=. Match is exact param name,
# case-insensitive.
_SENSITIVE_QUERY_PARAMS = frozenset({"token", "code", "state"})


class _SensitiveQueryAccessFilter(logging.Filter):
    """Redact secret-bearing query-param VALUES in uvicorn.access lines (SEC-9174 #34).

    The access log writes the full request line to captured stdout (the
    platform's log drain in SaaS, logs/giljo_mcp.log in CE), so a clicked reset link
    lands its plaintext token in every log sink. Rewrites the path element of
    uvicorn's access args tuple (client_addr, method, full_path, http_version,
    status_code); keeps the param name so the line stays debuggable, and never
    drops the record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not (isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]):
            return True
        path, _, query = args[2].partition("?")
        redacted = []
        for pair in query.split("&"):
            name, sep, _value = pair.partition("=")
            if sep and name.lower() in _SENSITIVE_QUERY_PARAMS:
                redacted.append(f"{name}=[REDACTED]")
            else:
                redacted.append(pair)
        record.args = (*args[:2], f"{path}?{'&'.join(redacted)}", *args[3:])
        return True


class _SafeRotatingFileHandler(_BaseRotatingFileHandler):
    """RotatingFileHandler that survives Windows file-lock errors.

    On Windows, os.rename() fails with PermissionError (WinError 32) when
    another process (uvicorn worker, log tail) holds the file open. Instead
    of crashing the request, we skip the rotation attempt — the next emit
    will retry when the lock may have cleared.
    """

    def doRollover(self):  # noqa: N802 -- must match parent class name
        try:  # noqa: SIM105 -- suppress is less clear for override pattern
            super().doRollover()
        except PermissionError:
            pass


# Public alias. The single canonical rotating-file handler for the whole
# codebase (logging/__init__, config_manager, api/run_api) — never define a
# second copy. The underscore name is retained for existing private importers.
SafeRotatingFileHandler = _SafeRotatingFileHandler


# Re-export for convenience
__all__ = [
    "ErrorCode",
    "SafeRotatingFileHandler",
    "configure_logging",
    "get_error_description",
]


# Module-level configuration state
class _LoggingState:
    """Configuration state holder to avoid global statement."""

    configured = False


def _setup_file_handler(level: int) -> None:
    """Add a RotatingFileHandler to the root logger.

    Writes human-readable log lines to logs/giljo_mcp.log with size-based
    rotation (10MB per file, 5 backups = 60MB max). Uses size-based rotation
    instead of time-based to avoid Windows file-locking issues (WinError 32)
    where TimedRotatingFileHandler cannot rename open files.
    """
    # Determine project root (3 levels up from this file: src/giljo_mcp/logging/)
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "giljo_mcp.log"

    handler = _SafeRotatingFileHandler(
        filename=str(log_file),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)


def configure_logging(
    environment: str | None = None,
    log_level: str = "INFO",
    force_json: bool = False,
) -> None:
    """
    Configure structlog processing pipeline for the application.

    Structlog acts as a log processor/formatter on top of stdlib logging.
    Individual modules should use ``logging.getLogger(__name__)`` to obtain
    their loggers.

    Args:
        environment: "production" for JSON, anything else for console (default: from ENVIRONMENT env var)
        log_level: Logging level (default: INFO)
        force_json: Force JSON output regardless of environment
    """
    if _LoggingState.configured:
        return

    # Determine environment
    if environment is None:
        environment = os.getenv("ENVIRONMENT", "development")

    # Determine log level
    level_str = os.getenv("LOG_LEVEL", log_level).upper()
    level = getattr(logging, level_str, logging.INFO)

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # Add file handler for persistent logging (daily rotation)
    _setup_file_handler(level)

    # Silence MCP transport heartbeat noise. The streamable_http transport
    # logs "Terminating session: None" at INFO on every stateless GET /mcp
    # poll (5+ per second from a single Claude Code client). WARNING keeps
    # real transport errors visible.
    logging.getLogger("mcp.server.streamable_http").setLevel(logging.WARNING)

    # Drop uvicorn access lines for GET /mcp polls only. Keeps all other
    # request logging (including MCP POSTs, which are real tool calls).
    # Then redact secret-bearing query-param values (SEC-9174 #34) — dictConfig
    # (uvicorn's own logging setup) replaces handlers but keeps logger filters,
    # so these survive regardless of whether uvicorn configures logging before
    # (CLI `uvicorn api.app:app`) or after (`uvicorn.run` in startup) import.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addFilter(_McpHeartbeatAccessFilter())
    access_logger.addFilter(_SensitiveQueryAccessFilter())

    # Shared processors for all configurations
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    # Production: JSON output
    if environment == "production" or force_json:
        processors = [*shared_processors, structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    # Development: Console output with colors
    else:
        processors = [
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _LoggingState.configured = True


# Initialize logging configuration on import (lazy initialization)
def _init_logging() -> None:
    """Initialize logging configuration on module import"""
    if not _LoggingState.configured:
        configure_logging()


# Auto-configure on import for seamless backward compatibility
_init_logging()
