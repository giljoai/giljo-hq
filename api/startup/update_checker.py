# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Background task that checks for available updates.

Two strategies:
  1. Git-based (cloned installs): git fetch + rev-list to count commits behind origin/master.
  2. GitHub releases API (zip installs): compare local __version__ against latest release tag.

Runs every 6 hours. Sets state.update_available when an update is detected
and broadcasts a WebSocket event on state transitions.
Silently no-ops if no network is available.
"""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path


try:
    from packaging.version import InvalidVersion, Version

    _HAS_PACKAGING = True
except ImportError:
    _HAS_PACKAGING = False


logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 21600  # 6 hours
_SUBPROCESS_TIMEOUT_SECONDS = 10
_GITHUB_RELEASES_URL = "https://api.github.com/repos/giljoai/giljo-hq/releases/latest"
_HTTP_TIMEOUT_SECONDS = 10


async def _run_git(*args: str) -> tuple[int, str, str]:
    """Run a git subcommand and return (returncode, stdout, stderr).

    Raises FileNotFoundError if the git binary is not on PATH.
    Raises asyncio.TimeoutError if the process does not complete in time.
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(Path.cwd()),
    )
    stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=_SUBPROCESS_TIMEOUT_SECONDS)
    return (
        proc.returncode,
        stdout_bytes.decode("utf-8", errors="replace").strip(),
        stderr_bytes.decode("utf-8", errors="replace").strip(),
    )


async def _is_git_repo() -> bool:
    """Return True if the working directory is inside a git repository."""
    try:
        code, _, _ = await _run_git("rev-parse", "--is-inside-work-tree")
        return code == 0
    except (TimeoutError, FileNotFoundError, OSError):
        return False


async def _has_remote(remote: str = "origin") -> bool:
    """Return True if the named remote exists."""
    try:
        code, _, _ = await _run_git("remote", "get-url", remote)
        return code == 0
    except (TimeoutError, FileNotFoundError, OSError):
        return False


async def _fetch_remote(remote: str = "origin") -> bool:
    """Fetch the remote to populate FETCH_HEAD. Returns True on success."""
    try:
        code, _, stderr = await _run_git("fetch", remote)
        if code != 0:
            logger.debug("git fetch %s failed: %s", remote, stderr)
            return False
        return True
    except (TimeoutError, FileNotFoundError, OSError) as exc:
        logger.debug("git fetch %s error: %s", remote, exc)
        return False


async def _resolve_default_branch(remote: str = "origin") -> str:
    """Resolve the remote's default branch ref (e.g. ``origin/main``).

    TSK-9262: the branch was hardcoded to ``<remote>/master``, so a CE fork
    whose default branch is ``main`` silently never saw update notices. Reads
    the symbolic ref git records at clone time; if it is unset (older clones),
    asks git to re-detect it via ``git remote set-head <remote> --auto`` and
    retries. Falls back to ``<remote>/master`` on any failure so behavior for
    stock clones is unchanged.
    """
    head_ref = f"refs/remotes/{remote}/HEAD"
    try:
        code, stdout, _ = await _run_git("symbolic-ref", "--short", head_ref)
        if code == 0 and stdout:
            return stdout
        code, _, stderr = await _run_git("remote", "set-head", remote, "--auto")
        if code == 0:
            code, stdout, _ = await _run_git("symbolic-ref", "--short", head_ref)
            if code == 0 and stdout:
                return stdout
        else:
            logger.debug("git remote set-head %s --auto failed: %s", remote, stderr)
    except (TimeoutError, FileNotFoundError, OSError) as exc:
        logger.debug("Default-branch detection error for %s: %s", remote, exc)
    return f"{remote}/master"


async def _commits_behind(branch: str) -> int | None:
    """Return the number of commits HEAD is behind the remote branch.

    Returns None if the count cannot be determined (network error, branch
    does not exist, etc.).
    """
    try:
        code, stdout, stderr = await _run_git("rev-list", f"HEAD..{branch}", "--count")
        if code != 0:
            logger.debug("git rev-list failed: %s", stderr)
            return None
        return int(stdout)
    except (TimeoutError, FileNotFoundError, OSError, ValueError) as exc:
        logger.debug("git rev-list error: %s", exc)
        return None


async def _emit_update_event(state, update_info: dict | None) -> None:
    """Broadcast a system:update_available WebSocket event to all tenants.

    Does nothing if the WebSocket manager is not ready.
    """
    ws_manager = getattr(state, "websocket_manager", None)
    if ws_manager is None:
        return

    event_data = {
        "update_available": update_info is not None,
        "detail": update_info,
    }

    try:
        # broadcast_json sends to all connected clients across all tenants
        await ws_manager.broadcast_json(
            {
                "type": "system:update_available",
                "data": event_data,
            }
        )
        logger.debug("Broadcast system:update_available event")
    except Exception as exc:
        logger.debug("Could not broadcast update event: %s", exc)


async def _refresh_update_banner(state) -> None:
    """Re-emit per-tenant system banners after an update-state transition.

    The DB-backed banner (``system.update_available``) is the durable authority;
    the WS event above is the live nudge. Banner emission must never crash the
    update loop, so failures are swallowed at this boundary.
    """
    try:
        from api.startup.background_tasks import emit_system_banners

        await emit_system_banners(state)
    except Exception as exc:
        logger.debug("Could not refresh update banner: %s", exc)


async def _update_check_loop(state) -> None:
    """Periodic loop that checks for remote commits every 6 hours.

    Runs an initial fetch at startup so rev-list has accurate data, then
    polls on the configured interval. State transitions trigger WebSocket
    broadcasts.
    """
    remote = "origin"

    # Initial fetch to populate FETCH_HEAD before the first check
    fetched = await _fetch_remote(remote)
    if not fetched:
        logger.debug("Initial fetch failed — update checks will rely on stale FETCH_HEAD if present")

    branch = await _resolve_default_branch(remote)

    while True:
        try:
            count = await _commits_behind(branch)

            if count is None:
                # Network or branch error — leave current state unchanged
                logger.debug("Could not determine commits behind %s — skipping this cycle", branch)
            elif count > 0:
                from giljo_mcp import branding

                new_info: dict | None = {
                    "commits_behind": count,
                    "message": f"{branding.PRODUCT_NAME}: {count} update{'s' if count != 1 else ''} available. "
                    f"Run 'git pull', then restart your server to update.",
                }
                previous = state.update_available
                state.update_available = new_info
                if previous != new_info:
                    logger.info(
                        "Update available: %d commit%s behind %s",
                        count,
                        "s" if count != 1 else "",
                        branch,
                    )
                    await _emit_update_event(state, new_info)
                    await _refresh_update_banner(state)
            else:
                previous = state.update_available
                state.update_available = None
                if previous is not None:
                    logger.info("System is up to date with %s", branch)
                    await _emit_update_event(state, None)
                    await _refresh_update_banner(state)

        except Exception as exc:
            logger.debug("Update check cycle error: %s", exc)

        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)

        # Fetch before each subsequent check
        await _fetch_remote(remote)


def _get_local_version() -> str:
    """Return the local application version string."""
    try:
        from giljo_mcp import __version__

        return __version__
    except ImportError:
        return "0.0.0"


async def _check_github_release() -> dict | None:
    """Check the GitHub releases API for a newer version.

    Returns update info dict if a newer release exists, None if up to date.
    Runs the blocking HTTP request in a thread executor to avoid blocking the event loop.
    """
    loop = asyncio.get_running_loop()
    try:
        local_version = Version(_get_local_version())
    except InvalidVersion:
        logger.debug("Could not parse local version — release check skipped")
        return None

    def _fetch_latest():
        req = urllib.request.Request(  # noqa: S310 — URL is a hardcoded HTTPS constant
            _GITHUB_RELEASES_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "GiljoAI-MCP-UpdateChecker"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310  # nosec B310
            return json.loads(resp.read().decode("utf-8"))

    try:
        data = await loop.run_in_executor(None, _fetch_latest)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        logger.debug("GitHub releases API error: %s", exc)
        return None

    tag = data.get("tag_name", "")
    # Strip leading 'v' from tag (e.g. "v1.1.0" -> "1.1.0")
    version_str = tag.lstrip("v")

    try:
        remote_version = Version(version_str)
    except InvalidVersion:
        logger.debug("Could not parse remote version tag: %s", tag)
        return None

    if remote_version > local_version:
        from giljo_mcp import branding

        html_url = data.get("html_url", "https://github.com/giljoai/giljo-hq/releases")
        return {
            "current_version": str(local_version),
            "latest_version": str(remote_version),
            "release_url": html_url,
            "message": f"{branding.PRODUCT_NAME} v{remote_version} is available (you have v{local_version}). "
            f"Re-run the installer to update.",
        }

    return None


async def _release_check_loop(state) -> None:
    """Periodic loop for zip-based installs that checks GitHub releases."""
    while True:
        try:
            update_info = await _check_github_release()

            previous = state.update_available
            if update_info is not None:
                state.update_available = update_info
                if previous != update_info:
                    logger.info(
                        "Update available: v%s -> v%s",
                        update_info["current_version"],
                        update_info["latest_version"],
                    )
                    await _emit_update_event(state, update_info)
                    await _refresh_update_banner(state)
            else:
                state.update_available = None
                if previous is not None:
                    logger.info("System is up to date (v%s)", _get_local_version())
                    await _emit_update_event(state, None)
                    await _refresh_update_banner(state)

        except Exception as exc:
            logger.debug("Release check cycle error: %s", exc)

        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)


async def start_update_checker(state) -> asyncio.Task | None:
    """Start the background update checker task.

    Uses git-based checking for cloned installs, falls back to GitHub
    releases API for zip-based installs.

    Returns the asyncio.Task if started, or None if the environment does not
    support it. This function never raises.
    """
    # Hosted SaaS controls its own rollout — never poll git/GitHub for updates
    # (belt-and-suspenders; the caller also gates this, BE-6031c).
    if os.environ.get("GILJO_MODE") == "saas":
        return None

    try:
        # Strategy 1: Git-based (cloned installs)
        if await _is_git_repo() and await _has_remote("origin"):
            logger.info("Update checker started (git mode)")
            return asyncio.create_task(_update_check_loop(state))

        # Strategy 2: GitHub releases API (zip installs)
        if not _HAS_PACKAGING:
            logger.debug("packaging library not available — release check disabled")
            return None
        logger.info("Update checker started (release mode — no git repo detected)")
        return asyncio.create_task(_release_check_loop(state))

    except FileNotFoundError:
        # No git binary — use release mode
        if not _HAS_PACKAGING:
            logger.debug("packaging library not available — release check disabled")
            return None
        logger.info("Update checker started (release mode — git not installed)")
        return asyncio.create_task(_release_check_loop(state))
    except Exception as exc:
        logger.debug("Update checker could not start: %s", exc)
        return None
