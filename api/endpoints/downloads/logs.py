# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CE-only log-download endpoints (current log, archive listing, archive fetch).

Extracted verbatim from api/endpoints/downloads.py (TSK-9209 / IMP-9169 §3.1
route-group split), which changed no behavior.

Every route here serves a file only after ``_servable_log_file`` has confirmed
it really lives inside the log directory. Two independent barriers guard the
archive routes -- the ``_ARCHIVE_PATTERN`` name allowlist and that containment
check -- and neither is allowed to become the only one.

``_LOG_DIR`` walks to ``parents[3]`` -- one level FURTHER UP than the former
single-file module's ``parents[2]``, because this file sits one level deeper
(``endpoints/downloads/logs.py`` vs ``endpoints/downloads.py``). That extra level
is what KEEPS the anchor on the repo root -- ``parents[2]`` would silently
retarget the constant at ``api/logs`` and every log endpoint would 404 on a real
log file.
"""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


# LOG DOWNLOAD ENDPOINTS (CE-only — not in SaaS/Demo). On a DEDICATED
# ``log_router`` defined UNCONDITIONALLY here; register_routers includes it at
# CALL time only in CE (reads ``api.app.GILJO_MODE``). The prior module-level
# ``if GILJO_MODE in ("", "ce")`` gate latched log-route membership to whichever
# edition imported this module first — non-deterministic under xdist (TSK-9125).
log_router = APIRouter(prefix="/api/download", tags=["downloads"])

_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"

# Filename ALLOWLIST -- the FIRST of the two path guards on the archive download
# route, not a display filter. Keep it fully anchored and keep both alternatives
# exact; never relax it to a prefix, glob, or substring test. It is no longer the
# only barrier (``_servable_log_file`` below is the second, and is what catches
# a symlink out of the directory), but it is still the one that decides what
# counts as an archive NAME -- widen it and you widen the attack surface even
# though containment holds.
#
# ``index``: what the running system actually writes. Every log handler in the
# codebase is a size-based RotatingFileHandler subclass, which emits
# ``giljo_mcp.log.1`` .. ``.N`` -- N is operator-configurable via
# ``LoggingConfig.max_files``, so the index is not single-digit. No ``.0`` and no
# zero padding, because the handler never writes those.
# ``date``: legacy leftovers from an earlier time-based configuration. Accepted so
# existing archives do not vanish from the list (tolerate the old shape).
#
# ``\Z``, not ``$``: Python's ``$`` also matches just before a trailing newline, so
# ``$`` let ``giljo_mcp.log.2026-04-12\n`` through the allowlist (BE-9347).
# ``[0-9]``, not ``\d``: ``\d`` also matches non-ASCII digits, which no handler
# ever writes.
_ARCHIVE_PATTERN = re.compile(r"^giljo_mcp\.log\.(?:(?P<index>[1-9][0-9]*)|(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}))\Z")


def _servable_log_file(filename: str) -> Path | None:
    """The real path of ``filename`` if it is a regular file INSIDE the log
    directory; None if it escapes, cannot be resolved, or is not a file.

    This is a SECOND, INDEPENDENT barrier behind ``_ARCHIVE_PATTERN``, and every
    route in this module goes through it before serving anything. The allowlist
    can only judge the NAME; it cannot see where that name leads, so a symlink
    planted inside ``logs/`` under a permitted archive name is caught here and
    nowhere else (SEC-9349). Keeping the two barriers separate is the point:
    widening the allowlist later must not be able to re-open a path out of the
    directory.

    A symlink whose target lies OUTSIDE the log directory is refused rather than
    followed. It takes local write access to ``logs/`` to plant one, but these
    routes promise "this install's log files", and following such a link turns an
    authenticated log download into an arbitrary-file read. A link pointing back
    inside the directory resolves inside and is still served.

    BOTH sides are resolved, which is what makes the comparison correct in both
    directions: resolving only the candidate would refuse every archive on an
    install whose ``logs/`` is itself a symlink onto a data volume. And
    containment is a component-wise parent test, never a string prefix -- a
    prefix test would accept ``/var/logs-evil`` as living under ``/var/logs``.

    The resolve AND the is-a-file test share ONE guard because a filesystem
    lookup has three unrelated ways to fail here, and every one of them must end
    at 404 rather than 500:

    * ``RuntimeError`` -- a symlink LOOP. pathlib converts ELOOP into
      ``RuntimeError("Symlink loop from ...")`` even in non-strict mode, calling
      ``stat()`` at the end specifically to force it. Missing this class made the
      containment check itself regress master's 404 into a 500.
    * ``ValueError`` -- an embedded NUL, raised (not as OSError) by the
      underlying stat.
    * ``OSError`` -- chiefly ENAMETOOLONG and EACCES, which pathlib's ignore set
      ``(ENOENT, ENOTDIR, EBADF, ELOOP)`` does NOT cover. On Windows the
      equivalent WinError IS ignored, so an over-length name answered 404 there
      and raised into a 500 on Linux, from the same request.

    Folding the file test in here is also what removes the last unguarded
    ``is_file()`` from the listing, where ``is_file()`` FOLLOWS symlinks -- so it
    is the resolved TARGET that can blow a limit, and a short entry name proves
    nothing. That is consistent with what this module already concedes: the
    ``except OSError`` around ``entry.stat()`` below exists precisely because a
    directory entry can fail mid-listing.
    """
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

    # Fixed name, so the allowlist never applied to this route at all -- until
    # SEC-9349 it had no path barrier whatsoever.
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

            # Never advertise a name that resolves out of the log directory, and
            # never let one unresolvable entry take the whole listing down -- this
            # is also the file-existence test, so no unguarded is_file() remains.
            if _servable_log_file(entry.name) is None:
                continue

            try:
                entry_stat = entry.stat()
            except OSError:
                # Rotation renames these files underneath us; one that vanishes
                # mid-listing is not an error, it is just no longer an archive.
                continue

            archive = {
                "filename": entry.name,
                # Local time, not UTC: a self-hoster comparing this against their
                # own file manager must see the same day.
                "date": match["date"]
                or datetime.fromtimestamp(entry_stat.st_mtime, tz=UTC).astimezone().strftime("%Y-%m-%d"),
                "rotation_index": int(match["index"]) if match["index"] else None,
                "size_kb": round(entry_stat.st_size / 1024, 1),
            }
            (numbered if archive["rotation_index"] is not None else dated).append(archive)

    # Newest first. Numbered rotation counts UP as files get OLDER (.1 is the most
    # recently rotated), so ascending index IS newest-first. Legacy date-named
    # archives predate anything the current handlers wrote, so they follow.
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

    # Containment is checked BEFORE the existence test, and an escape is reported
    # as 404 exactly like an absent file: the caller learns nothing about what
    # does or does not sit outside the log directory.
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
