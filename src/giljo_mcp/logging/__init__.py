# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler as _BaseRotatingFileHandler
from pathlib import Path

import structlog

from .error_codes import ErrorCode


class _McpHeartbeatAccessFilter(logging.Filter):

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        method, path = args[1], args[2]
        return not (method == "GET" and path == "/mcp")


_SENSITIVE_QUERY_PARAMS = frozenset({"token", "code", "state"})

_DOWNLOAD_TOKEN_PATH_RE = re.compile(r"(/api/download/temp/)[^/?]+")


class _SensitiveQueryAccessFilter(logging.Filter):

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not (isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str)):
            return True

        full_path = _DOWNLOAD_TOKEN_PATH_RE.sub(r"\1[REDACTED]", args[2])

        if "?" not in full_path:
            if full_path != args[2]:
                record.args = (*args[:2], full_path, *args[3:])
            return True

        path, _, query = full_path.partition("?")
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

    def doRollover(self):  # noqa: N802 -- must match parent class name
        try:  # noqa: SIM105 -- suppress is less clear for override pattern
            super().doRollover()
        except PermissionError:
            pass


SafeRotatingFileHandler = _SafeRotatingFileHandler


__all__ = [
    "ErrorCode",
    "SafeRotatingFileHandler",
    "configure_logging",
]


class _LoggingState:

    configured = False


def _setup_file_handler(level: int) -> None:
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "giljo_mcp.log"

    handler = _SafeRotatingFileHandler(
        filename=str(log_file),
        maxBytes=10 * 1024 * 1024,
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
    if _LoggingState.configured:
        return

    if environment is None:
        environment = os.getenv("ENVIRONMENT", "development")

    level_str = os.getenv("LOG_LEVEL", log_level).strip().upper()
    levels = logging.getLevelNamesMapping()
    if level_str not in levels:
        raise ValueError(f"LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL; got {level_str!r}")
    level = levels[level_str]

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    _setup_file_handler(level)

    logging.getLogger("mcp.server.streamable_http").setLevel(logging.WARNING)

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addFilter(_McpHeartbeatAccessFilter())
    access_logger.addFilter(_SensitiveQueryAccessFilter())

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if environment == "production" or force_json:
        processors = [*shared_processors, structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        processors = [
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _LoggingState.configured = True


def _init_logging() -> None:
    if not _LoggingState.configured:
        configure_logging()


_init_logging()
