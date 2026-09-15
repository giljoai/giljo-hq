# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


log_router = APIRouter(prefix="/api/download", tags=["downloads"])

_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"

_ARCHIVE_PATTERN = re.compile(r"^giljo_mcp\.log\.(?:(?P<index>[1-9][0-9]*)|(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}))\Z")


def _servable_log_file(filename: str) -> Path | None:
    try:
        log_dir = _LOG_DIR.resolve()
        candidate = (_LOG_DIR / filename).resolve()
        if candidate == log_dir or log_dir not in candidate.parents:
            return None
        if not candidate.is_file():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


@log_router.get("/logs/current")
async def download_current_log(
    current_user: User = Depends(get_current_active_user),
):
    """
    Download the current runtime log file (giljo_mcp.log).

    CE-only endpoint. Requires authentication.

    Returns:
        FileResponse with the current log file.

    Raises:
        HTTPException 404: Log file does not exist yet.
    """
    from fastapi.responses import FileResponse

    log_file = _servable_log_file("giljo_mcp.log")
    if log_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Log file not found. Server may not have generated logs yet.",
        )

    logger.info(
        "Log download: current log requested by user=%s",
        sanitize(current_user.username),
    )

    return FileResponse(
        path=str(log_file),
        filename="giljo_mcp.log",
        media_type="text/plain",
    )


@log_router.get("/logs/archives")
async def list_log_archives(
    current_user: User = Depends(get_current_active_user),
):
    """
    List available log archive files with metadata, newest first.

    CE-only endpoint. Requires authentication.

    ``date`` is always a real ISO date so the client can format it: for a
    size-rotated archive the filename carries no date, so the file's mtime (when
    rotation wrote it) is used. ``rotation_index`` is the ``.N`` suffix, or None
    for a legacy date-named archive -- it is what keeps two archives rotated on
    the same day distinguishable in the UI.

    Returns:
        JSON list of archive files: [{filename, date, rotation_index, size_kb}]
    """
    numbered = []
    dated = []

    if _LOG_DIR.exists():
        for entry in _LOG_DIR.iterdir():
            match = _ARCHIVE_PATTERN.match(entry.name)
            if not match:
                continue

            if _servable_log_file(entry.name) is None:
                continue

            try:
                entry_stat = entry.stat()
            except OSError:
                continue

            archive = {
                "filename": entry.name,
                "date": match["date"]
                or datetime.fromtimestamp(entry_stat.st_mtime, tz=UTC).astimezone().strftime("%Y-%m-%d"),
                "rotation_index": int(match["index"]) if match["index"] else None,
                "size_kb": round(entry_stat.st_size / 1024, 1),
            }
            (numbered if archive["rotation_index"] is not None else dated).append(archive)

    numbered.sort(key=lambda archive: archive["rotation_index"])
    dated.sort(key=lambda archive: archive["date"], reverse=True)

    return numbered + dated


@log_router.get("/logs/archive/{filename}")
async def download_log_archive(
    filename: str,
    current_user: User = Depends(get_current_active_user),
):
    """
    Download a specific log archive file.

    CE-only endpoint. Requires authentication. The filename is validated against
    a strict allowlist and the resolved path is then required to stay inside the
    log directory.

    Args:
        filename: Archive filename (giljo_mcp.log.N or legacy giljo_mcp.log.YYYY-MM-DD)

    Returns:
        FileResponse with the archive file.

    Raises:
        HTTPException 400: Invalid filename pattern.
        HTTPException 404: Archive file does not exist, or resolves outside the
            log directory (the two are deliberately indistinguishable to the
            caller).
    """
    from fastapi.responses import FileResponse

    if not _ARCHIVE_PATTERN.match(filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename. Must match pattern: giljo_mcp.log.N or giljo_mcp.log.YYYY-MM-DD",
        )

    archive_file = _servable_log_file(filename)
    if archive_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archive file not found.",
        )

    logger.info(
        "Log download: archive %s requested by user=%s",
        sanitize(filename),
        sanitize(current_user.username),
    )

    return FileResponse(
        path=str(archive_file),
        filename=filename,
        media_type="text/plain",
    )
