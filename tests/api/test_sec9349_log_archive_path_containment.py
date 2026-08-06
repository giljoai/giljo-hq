# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9349 -- the log routes must not serve a file outside the log directory.

Failing layer this regression-locks: ``api/endpoints/downloads/logs.py``. Before
this fix the download route was ``_ARCHIVE_PATTERN.match(filename)`` ->
``_LOG_DIR / filename`` -> ``is_file()`` -> ``FileResponse``, with no
``Path.resolve()`` and no containment check anywhere. The filename allowlist was
therefore the SOLE barrier between a URL path parameter and the filesystem, and
it cannot see a symlink: a symlink planted inside ``logs/`` under a permitted
archive name and pointing outside was listed and served in full.

These tests pin the SECOND, INDEPENDENT barrier. Several of them deliberately
monkeypatch ``_ARCHIVE_PATTERN`` wide open to prove containment holds on its own,
so that a future well-meaning widening of the allowlist (gzip suffixes, say)
cannot silently remove the only defence. Do not "simplify" those by dropping the
patch -- with the real allowlist in place they would pass vacuously, which is the
exact failure mode this file exists to prevent.

Exercised at the API layer through the real ASGI transport and the real router,
which is the layer the defect lived at.

Edition Scope: CE. ``downloads.log_router`` is included by
``api/wiring/routers.py`` only when ``GILJO_MODE in ("", "ce")``, so these routes
do not exist in SaaS.

Parallel-safe: monkeypatched module constants + tmp_path only. No DB, no
module-level mutable state, no ordering dependency. The canary lives inside this
test's own ``tmp_path``, never in the shared parent, so concurrent workers cannot
race on it.
"""

from __future__ import annotations

import errno
import os
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest


CANARY = "SEC9349-must-not-be-served"

# Wide open: stands in for a future edit that loosens the allowlist (e.g. adding
# gzip-rotation suffixes). Containment must refuse the escape regardless.
_ANY_FILENAME = re.compile(r"^.*\Z", re.DOTALL)


def _build_app(monkeypatch, log_dir: Path, pattern: re.Pattern[str] | None = None):
    """A minimal app carrying the real ``log_router`` against a seeded log dir."""
    from fastapi import FastAPI

    from api.endpoints.downloads import logs as logs_mod
    from giljo_mcp.auth.dependencies import get_current_active_user

    monkeypatch.setattr(logs_mod, "_LOG_DIR", log_dir)
    if pattern is not None:
        monkeypatch.setattr(logs_mod, "_ARCHIVE_PATTERN", pattern)

    app = FastAPI()
    app.include_router(logs_mod.log_router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(username="tester")
    return app


async def _get(app, path: str):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    """``logs/`` next to an ``outside/`` holding the canary, both under tmp_path.

    Self-contained on purpose: planting the canary in ``tmp_path.parent`` would
    put it in pytest's shared per-run directory, where parallel workers would
    write over each other.
    """
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".env").write_text(f"SECRET={CANARY}", encoding="utf-8")
    return log_dir, outside


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Create a symlink, skipping ONLY on Windows without the privilege for it.

    On POSIX any unprivileged user can create a symlink, so a failure there is a
    broken environment, not an unsupported platform -- and skipping would
    silently void ten of this file's eighteen tests (every symlink-based one,
    which is the bulk of the containment coverage) while CI stayed green. That
    is a vacuous pass, so POSIX raises instead.
    """
    try:
        # target_is_directory matters on Windows, which picks the link TYPE at
        # creation time rather than following the target.
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:
        if os.name != "nt":
            raise
        pytest.skip(reason=f"Windows symlink creation needs Developer Mode or elevation: {exc}")


def _filenames(response) -> list[str]:
    return [entry["filename"] for entry in response.json()]


# Both permitted archive forms, so the escape is pinned for the numbered names the
# handlers actually write AND the legacy dated names still tolerated on read.
_PERMITTED_ARCHIVE_NAMES = ["giljo_mcp.log.7", "giljo_mcp.log.2026-04-12"]


@pytest.mark.parametrize("archive_name", _PERMITTED_ARCHIVE_NAMES)
@pytest.mark.asyncio
async def test_symlink_escaping_the_log_dir_is_not_downloadable(monkeypatch, tmp_path, archive_name):
    """THE regression target. The name passes the allowlist -- only containment
    can refuse it, because a filename check cannot see where a symlink points."""
    log_dir, outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / archive_name, outside / ".env")

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, f"/api/download/logs/archive/{archive_name}")

    assert CANARY not in response.text, f"served a file outside the log directory via {archive_name}"
    assert response.status_code == 404, f"escaping symlink should 404, got {response.status_code}"


@pytest.mark.parametrize("archive_name", _PERMITTED_ARCHIVE_NAMES)
@pytest.mark.asyncio
async def test_symlink_escaping_the_log_dir_is_not_listed(monkeypatch, tmp_path, archive_name):
    """Listing it is its own defect: the UI advertises a file the operator never
    put there, and it is the listing that tells a caller the name to fetch."""
    log_dir, outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / archive_name, outside / ".env")

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200
    assert _filenames(response) == [], "an escaping symlink was advertised in the archive listing"


@pytest.mark.asyncio
async def test_current_log_symlink_escaping_the_log_dir_is_not_served(monkeypatch, tmp_path):
    """The current-log route takes no user input, so the allowlist never applied
    to it at all -- it had no barrier whatsoever. Same containment, same refusal."""
    log_dir, outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / "giljo_mcp.log", outside / ".env")

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, "/api/download/logs/current")

    assert CANARY not in response.text, "served a file outside the log directory as the current log"
    assert response.status_code == 404


# ``%5C`` decodes to a real path separator on Windows -- the primary CE self-host
# platform -- and Starlette's router does NOT refuse it the way it refuses ``/``.
# On POSIX a backslash is an ordinary filename character, so the same request asks
# for a (nonexistent) file inside the log dir. Both platforms must end at "not
# served"; asserting 404 rather than "not 200" holds on both.
_WINDOWS_SEPARATOR_ESCAPES = [
    "..%5Coutside%5C.env",
    ".%5C..%5Coutside%5C.env",
    "giljo_mcp.log.1%5C..%5C..%5Coutside%5C.env",
]


@pytest.mark.parametrize("filename", _WINDOWS_SEPARATOR_ESCAPES)
@pytest.mark.asyncio
async def test_backslash_traversal_refused_even_with_the_allowlist_wide_open(monkeypatch, tmp_path, filename):
    """Containment must stand alone. The allowlist is patched wide open here on
    purpose: it already refuses every one of these, so with the real pattern this
    test would prove nothing about the second barrier."""
    log_dir, outside = _layout(tmp_path)
    (log_dir / "giljo_mcp.log.1").write_text("a real archive", encoding="utf-8")

    # A param that lands somewhere no canary sits would 404 for a benign reason
    # and pin nothing. Assert the escape is REAL under Windows separator
    # semantics -- which is also what keeps this meaningful on POSIX, where the
    # request itself cannot escape because a backslash is an ordinary character.
    decoded = unquote(filename)
    reached = Path(os.path.normpath(str(log_dir / decoded.replace("\\", "/"))))
    assert reached == outside / ".env", f"vacuous param: {filename!r} points at {reached}, not the canary"

    app = _build_app(monkeypatch, log_dir, pattern=_ANY_FILENAME)
    response = await _get(app, f"/api/download/logs/archive/{filename}")

    assert CANARY not in response.text, f"backslash traversal served the canary via {filename}"
    assert response.status_code == 404, f"{filename!r} should be refused, got {response.status_code}"


@pytest.mark.asyncio
async def test_null_byte_is_a_404_not_a_500_with_the_allowlist_wide_open(monkeypatch, tmp_path):
    """An embedded NUL makes the underlying stat raise ValueError, NOT OSError.

    The real allowlist refuses this name today, so this is only reachable once
    someone widens it -- which is precisely the scenario containment exists for.
    Containment answering with a 500 instead of a 404 would make the second
    barrier a denial-of-service surface of its own.
    """
    log_dir, _outside = _layout(tmp_path)

    app = _build_app(monkeypatch, log_dir, pattern=_ANY_FILENAME)
    response = await _get(app, "/api/download/logs/archive/giljo_mcp.log.1%00.txt")

    assert response.status_code == 404, f"NUL byte should 404, got {response.status_code}"


@pytest.mark.asyncio
async def test_symlink_escaping_the_log_dir_is_refused_with_the_allowlist_wide_open(monkeypatch, tmp_path):
    """The same symlink escape under an arbitrary name, to show the refusal comes
    from containment and not from the name happening to fail the allowlist."""
    log_dir, outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / "anything.gz", outside / ".env")

    app = _build_app(monkeypatch, log_dir, pattern=_ANY_FILENAME)

    download = await _get(app, "/api/download/logs/archive/anything.gz")
    assert CANARY not in download.text
    assert download.status_code == 404

    listing = await _get(app, "/api/download/logs/archives")
    assert _filenames(listing) == []


@pytest.mark.asyncio
async def test_legitimate_archives_still_list_and_download_unchanged(monkeypatch, tmp_path):
    """The control. Containment must cost a real self-hoster nothing: both
    permitted forms still list, and every listed entry still downloads its own
    bytes end to end."""
    log_dir, _outside = _layout(tmp_path)
    bodies = {
        "giljo_mcp.log.1": "body of rotation one",
        "giljo_mcp.log.12": "body of rotation twelve",
        "giljo_mcp.log.2026-04-12": "body of the legacy archive",
    }
    for name, body in bodies.items():
        (log_dir / name).write_text(body, encoding="utf-8")
    (log_dir / "giljo_mcp.log").write_text("the live file", encoding="utf-8")

    app = _build_app(monkeypatch, log_dir)
    listing = await _get(app, "/api/download/logs/archives")
    assert sorted(_filenames(listing)) == sorted(bodies)

    for name, body in bodies.items():
        download = await _get(app, f"/api/download/logs/archive/{name}")
        assert download.status_code == 200, f"legitimate archive stopped downloading: {name}"
        assert download.text == body

    current = await _get(app, "/api/download/logs/current")
    assert current.status_code == 200
    assert current.text == "the live file"


@pytest.mark.asyncio
async def test_symlink_pointing_inside_the_log_dir_is_still_served(monkeypatch, tmp_path):
    """Containment, not a blanket symlink ban. A link whose target is itself
    inside the log directory leaks nothing, so it stays served -- this is what
    keeps the rule "no file outside logs/" rather than "no links"."""
    log_dir, _outside = _layout(tmp_path)
    (log_dir / "rotated-elsewhere.txt").write_text("an in-directory target", encoding="utf-8")
    _symlink_or_skip(log_dir / "giljo_mcp.log.3", log_dir / "rotated-elsewhere.txt")

    app = _build_app(monkeypatch, log_dir)

    assert _filenames(await _get(app, "/api/download/logs/archives")) == ["giljo_mcp.log.3"]
    download = await _get(app, "/api/download/logs/archive/giljo_mcp.log.3")
    assert download.status_code == 200
    assert download.text == "an in-directory target"


@pytest.mark.asyncio
async def test_a_symlinked_log_directory_still_serves_its_own_archives(monkeypatch, tmp_path):
    """A self-hoster who points ``logs/`` at a data volume must not lose the
    endpoint. This is why BOTH sides are resolved: comparing a resolved candidate
    against an UNRESOLVED root would refuse every archive on such an install."""
    real_logs = tmp_path / "volume" / "giljo-logs"
    real_logs.mkdir(parents=True)
    (real_logs / "giljo_mcp.log.1").write_text("archive on the volume", encoding="utf-8")

    link_dir = tmp_path / "logs"
    _symlink_or_skip(link_dir, real_logs)

    app = _build_app(monkeypatch, link_dir)

    assert _filenames(await _get(app, "/api/download/logs/archives")) == ["giljo_mcp.log.1"]
    download = await _get(app, "/api/download/logs/archive/giljo_mcp.log.1")
    assert download.status_code == 200
    assert download.text == "archive on the volume"


@pytest.mark.asyncio
async def test_absurdly_long_index_still_404s_rather_than_500ing(monkeypatch, tmp_path):
    """An over-length archive name is a 404, never a 500 -- on EVERY platform.

    The BE-9347 audit recorded this as verified, but that verification was
    Windows-only and does not hold on Linux. pathlib's ignore set is
    ``(ENOENT, ENOTDIR, EBADF, ELOOP)`` plus a Windows-only WinError list
    containing ERROR_INVALID_NAME. ENAMETOOLONG is in neither, so the same
    request answered 404 on a Windows self-hoster and raised into a 500 on a
    Linux one. Reproduced on Linux from roughly 242 characters -- nothing here
    is ever written to disk, so this asserts on the request alone.
    """
    log_dir, _outside = _layout(tmp_path)

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, f"/api/download/logs/archive/giljo_mcp.log.{'9' * 4000}")

    assert response.status_code == 404, f"expected 404, got {response.status_code}"


def _stat_raising(errno_value: int, message: str, only_for: str | None = None):
    """A ``Path.stat`` replacement that injects a specific errno.

    Injecting the errno is what makes a platform-specific failure testable off
    that platform: ENAMETOOLONG is what Linux raises where Windows swallows it,
    and this reproduces the Linux branch on any box.
    """
    real_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        if only_for is None or self.name == only_for:
            raise OSError(errno_value, message, str(self))
        return real_stat(self, *args, **kwargs)

    return fake_stat


@pytest.mark.asyncio
async def test_name_too_long_errno_is_404_not_500(monkeypatch, tmp_path):
    """The Linux branch of the over-length name, reproduced on any platform.

    Patches ``Path.stat`` rather than ``is_file`` on purpose: it exercises
    pathlib's REAL ``_ignore_error`` decision -- the thing that differs between
    platforms -- instead of bypassing it.
    """
    log_dir, _outside = _layout(tmp_path)

    app = _build_app(monkeypatch, log_dir)
    monkeypatch.setattr(Path, "stat", _stat_raising(errno.ENAMETOOLONG, "File name too long"))
    response = await _get(app, "/api/download/logs/archive/giljo_mcp.log.1")

    assert response.status_code == 404, f"ENAMETOOLONG should 404, got {response.status_code}"


@pytest.mark.asyncio
async def test_listing_survives_an_unstatable_entry(monkeypatch, tmp_path):
    """``is_file()`` FOLLOWS symlinks, so it is the resolved TARGET that can blow
    the length limit -- the entry name being short proves nothing.

    ENAMETOOLONG and EACCES are both absent from pathlib's ignore set, so a link
    in ``logs/`` pointing at a pathological or untraversable target raised
    straight out of the listing and 500'd it. The module already concedes that a
    directory entry can fail mid-listing -- that is what the existing
    ``except OSError`` around ``entry.stat()`` is for -- and this call was simply
    left outside that concession.
    """
    log_dir, _outside = _layout(tmp_path)
    (log_dir / "giljo_mcp.log.1").write_text("unstatable", encoding="utf-8")
    (log_dir / "giljo_mcp.log.2").write_text("fine", encoding="utf-8")

    app = _build_app(monkeypatch, log_dir)
    monkeypatch.setattr(
        Path, "stat", _stat_raising(errno.ENAMETOOLONG, "File name too long", only_for="giljo_mcp.log.1")
    )
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200, f"one bad entry took the whole listing down: {response.status_code}"
    assert _filenames(response) == ["giljo_mcp.log.2"]


@pytest.mark.asyncio
async def test_symlink_loop_is_404_not_500(monkeypatch, tmp_path):
    """A symlink LOOP makes ``Path.resolve()`` raise ``RuntimeError``, not OSError.

    pathlib converts ELOOP into ``RuntimeError("Symlink loop from ...")`` even in
    non-strict mode (it calls ``stat()`` at the end specifically to force the
    exception). Guarding only ``(OSError, ValueError)`` therefore turns master's
    404 into a 500 -- a regression introduced BY the containment check, on a
    change whose whole premise is hardening.
    """
    log_dir, _outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / "giljo_mcp.log.7", log_dir / "giljo_mcp.log.8")
    _symlink_or_skip(log_dir / "giljo_mcp.log.8", log_dir / "giljo_mcp.log.7")

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, "/api/download/logs/archive/giljo_mcp.log.7")

    assert response.status_code == 404, f"symlink loop should 404, got {response.status_code}"


@pytest.mark.asyncio
async def test_symlink_loop_does_not_break_the_listing(monkeypatch, tmp_path):
    """Same loop through the listing, which calls the same containment helper.
    One unresolvable entry must drop out, not take the endpoint down."""
    log_dir, _outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / "giljo_mcp.log.7", log_dir / "giljo_mcp.log.8")
    _symlink_or_skip(log_dir / "giljo_mcp.log.8", log_dir / "giljo_mcp.log.7")
    (log_dir / "giljo_mcp.log.1").write_text("a real archive", encoding="utf-8")

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200, f"symlink loop took the listing down: {response.status_code}"
    assert _filenames(response) == ["giljo_mcp.log.1"]
