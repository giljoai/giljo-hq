# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import errno
import os
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest


CANARY = "SEC9349-must-not-be-served"

OUTSIDE_SENTINEL = "parent-sentinel.txt"

_ANY_FILENAME = re.compile(r"^.*\Z", re.DOTALL)


def _build_app(monkeypatch, log_dir: Path, pattern: re.Pattern[str] | None = None):
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
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / OUTSIDE_SENTINEL).write_text(CANARY, encoding="utf-8")
    return log_dir, outside


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:
        if os.name != "nt":
            raise
        pytest.skip(reason=f"Windows symlink creation needs Developer Mode or elevation: {exc}")


def _filenames(response) -> list[str]:
    return [entry["filename"] for entry in response.json()]


_PERMITTED_ARCHIVE_NAMES = ["giljo_mcp.log.7", "giljo_mcp.log.2026-04-12"]


@pytest.mark.parametrize("archive_name", _PERMITTED_ARCHIVE_NAMES)
@pytest.mark.asyncio
async def test_symlink_escaping_the_log_dir_is_not_downloadable(monkeypatch, tmp_path, archive_name):
    log_dir, outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / archive_name, outside / OUTSIDE_SENTINEL)

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, f"/api/download/logs/archive/{archive_name}")

    assert CANARY not in response.text, f"served a file outside the log directory via {archive_name}"
    assert response.status_code == 404, f"escaping symlink should 404, got {response.status_code}"


@pytest.mark.parametrize("archive_name", _PERMITTED_ARCHIVE_NAMES)
@pytest.mark.asyncio
async def test_symlink_escaping_the_log_dir_is_not_listed(monkeypatch, tmp_path, archive_name):
    log_dir, outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / archive_name, outside / OUTSIDE_SENTINEL)

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200
    assert _filenames(response) == [], "an escaping symlink was advertised in the archive listing"


@pytest.mark.asyncio
async def test_current_log_symlink_escaping_the_log_dir_is_not_served(monkeypatch, tmp_path):
    log_dir, outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / "giljo_mcp.log", outside / OUTSIDE_SENTINEL)

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, "/api/download/logs/current")

    assert CANARY not in response.text, "served a file outside the log directory as the current log"
    assert response.status_code == 404


_SEPARATOR_ENCODING = "%5C"
_ESCAPE_PREFIXES = ("..", f".{_SEPARATOR_ENCODING}..", f"giljo_mcp.log.1{_SEPARATOR_ENCODING}..{_SEPARATOR_ENCODING}..")

_WINDOWS_SEPARATOR_ESCAPES = [
    f"{prefix}{_SEPARATOR_ENCODING}outside{_SEPARATOR_ENCODING}{OUTSIDE_SENTINEL}" for prefix in _ESCAPE_PREFIXES
]


@pytest.mark.parametrize("filename", _WINDOWS_SEPARATOR_ESCAPES)
@pytest.mark.asyncio
async def test_backslash_traversal_refused_even_with_the_allowlist_wide_open(monkeypatch, tmp_path, filename):
    log_dir, outside = _layout(tmp_path)
    (log_dir / "giljo_mcp.log.1").write_text("a real archive", encoding="utf-8")

    decoded = unquote(filename)
    reached = Path(os.path.normpath(str(log_dir / decoded.replace("\\", "/"))))
    assert reached == outside / OUTSIDE_SENTINEL, f"vacuous param: {filename!r} points at {reached}, not the sentinel"

    app = _build_app(monkeypatch, log_dir, pattern=_ANY_FILENAME)
    response = await _get(app, f"/api/download/logs/archive/{filename}")

    assert CANARY not in response.text, f"backslash traversal served the canary via {filename}"
    assert response.status_code == 404, f"{filename!r} should be refused, got {response.status_code}"


@pytest.mark.asyncio
async def test_null_byte_is_a_404_not_a_500_with_the_allowlist_wide_open(monkeypatch, tmp_path):
    log_dir, _outside = _layout(tmp_path)

    app = _build_app(monkeypatch, log_dir, pattern=_ANY_FILENAME)
    response = await _get(app, "/api/download/logs/archive/giljo_mcp.log.1%00.txt")

    assert response.status_code == 404, f"NUL byte should 404, got {response.status_code}"


@pytest.mark.asyncio
async def test_symlink_escaping_the_log_dir_is_refused_with_the_allowlist_wide_open(monkeypatch, tmp_path):
    log_dir, outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / "anything.gz", outside / OUTSIDE_SENTINEL)

    app = _build_app(monkeypatch, log_dir, pattern=_ANY_FILENAME)

    download = await _get(app, "/api/download/logs/archive/anything.gz")
    assert CANARY not in download.text
    assert download.status_code == 404

    listing = await _get(app, "/api/download/logs/archives")
    assert _filenames(listing) == []


@pytest.mark.asyncio
async def test_legitimate_archives_still_list_and_download_unchanged(monkeypatch, tmp_path):
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
    log_dir, _outside = _layout(tmp_path)

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, f"/api/download/logs/archive/giljo_mcp.log.{'9' * 4000}")

    assert response.status_code == 404, f"expected 404, got {response.status_code}"


def _stat_raising(errno_value: int, message: str, only_for: str | None = None):
    real_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        if only_for is None or self.name == only_for:
            raise OSError(errno_value, message, str(self))
        return real_stat(self, *args, **kwargs)

    return fake_stat


@pytest.mark.asyncio
async def test_name_too_long_errno_is_404_not_500(monkeypatch, tmp_path):
    log_dir, _outside = _layout(tmp_path)

    app = _build_app(monkeypatch, log_dir)
    monkeypatch.setattr(Path, "stat", _stat_raising(errno.ENAMETOOLONG, "File name too long"))
    response = await _get(app, "/api/download/logs/archive/giljo_mcp.log.1")

    assert response.status_code == 404, f"ENAMETOOLONG should 404, got {response.status_code}"


@pytest.mark.asyncio
async def test_listing_survives_an_unstatable_entry(monkeypatch, tmp_path):
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
    log_dir, _outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / "giljo_mcp.log.7", log_dir / "giljo_mcp.log.8")
    _symlink_or_skip(log_dir / "giljo_mcp.log.8", log_dir / "giljo_mcp.log.7")

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, "/api/download/logs/archive/giljo_mcp.log.7")

    assert response.status_code == 404, f"symlink loop should 404, got {response.status_code}"


@pytest.mark.asyncio
async def test_symlink_loop_does_not_break_the_listing(monkeypatch, tmp_path):
    log_dir, _outside = _layout(tmp_path)
    _symlink_or_skip(log_dir / "giljo_mcp.log.7", log_dir / "giljo_mcp.log.8")
    _symlink_or_skip(log_dir / "giljo_mcp.log.8", log_dir / "giljo_mcp.log.7")
    (log_dir / "giljo_mcp.log.1").write_text("a real archive", encoding="utf-8")

    app = _build_app(monkeypatch, log_dir)
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200, f"symlink loop took the listing down: {response.status_code}"
    assert _filenames(response) == ["giljo_mcp.log.1"]
