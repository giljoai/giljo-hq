# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

import pytest


def _build_app(monkeypatch, log_dir):
    from fastapi import FastAPI

    from api.endpoints.downloads import logs as logs_mod
    from giljo_mcp.auth.dependencies import get_current_active_user

    monkeypatch.setattr(logs_mod, "_LOG_DIR", log_dir)

    app = FastAPI()
    app.include_router(logs_mod.log_router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(username="tester")
    return app


async def _get(app, path: str):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def _seed(log_dir, name: str, body: str = "rotated log content") -> None:
    (log_dir / name).write_text(body, encoding="utf-8")


def response_filenames(response) -> list[str]:
    return [entry["filename"] for entry in response.json()]


@pytest.mark.asyncio
async def test_listing_includes_size_rotated_archive(monkeypatch, tmp_path):
    _seed(tmp_path, "giljo_mcp.log")
    _seed(tmp_path, "giljo_mcp.log.1")

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200
    listed = {entry["filename"] for entry in response.json()}
    assert "giljo_mcp.log.1" in listed, f"size-rotated archive missing from listing: {listed}"


@pytest.mark.asyncio
async def test_listing_includes_multi_digit_rotation_index(monkeypatch, tmp_path):
    _seed(tmp_path, "giljo_mcp.log.12")

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, "/api/download/logs/archives")

    listed = {entry["filename"] for entry in response.json()}
    assert "giljo_mcp.log.12" in listed


@pytest.mark.asyncio
async def test_legacy_date_suffixed_archive_still_listed(monkeypatch, tmp_path):
    _seed(tmp_path, "giljo_mcp.log.2026-04-12")

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, "/api/download/logs/archives")

    listed = {entry["filename"] for entry in response.json()}
    assert "giljo_mcp.log.2026-04-12" in listed


@pytest.mark.asyncio
async def test_current_log_is_not_listed_as_an_archive(monkeypatch, tmp_path):
    _seed(tmp_path, "giljo_mcp.log")

    app = _build_app(monkeypatch, tmp_path)

    assert response_filenames(await _get(app, "/api/download/logs/archives")) == []


@pytest.mark.asyncio
async def test_every_listed_archive_is_actually_downloadable(monkeypatch, tmp_path):
    _seed(tmp_path, "giljo_mcp.log.1", "body of rotation one")
    _seed(tmp_path, "giljo_mcp.log.5", "body of rotation five")
    _seed(tmp_path, "giljo_mcp.log.2026-04-12", "body of the legacy archive")

    app = _build_app(monkeypatch, tmp_path)
    listing = await _get(app, "/api/download/logs/archives")
    filenames = response_filenames(listing)
    assert len(filenames) == 3, f"expected all three archives listed, got {filenames}"

    for filename in filenames:
        download = await _get(app, f"/api/download/logs/archive/{filename}")
        assert download.status_code == 200, f"listed but not downloadable: {filename} -> {download.status_code}"
        assert download.text == (tmp_path / filename).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_listing_reports_a_valid_date_and_rotation_index(monkeypatch, tmp_path):
    _seed(tmp_path, "giljo_mcp.log.1")
    _seed(tmp_path, "giljo_mcp.log.2026-04-12")

    app = _build_app(monkeypatch, tmp_path)
    entries = {entry["filename"]: entry for entry in (await _get(app, "/api/download/logs/archives")).json()}

    numbered = entries["giljo_mcp.log.1"]
    assert numbered["rotation_index"] == 1
    assert len(numbered["date"]) == 10 and numbered["date"].count("-") == 2

    legacy = entries["giljo_mcp.log.2026-04-12"]
    assert legacy["date"] == "2026-04-12"
    assert legacy["rotation_index"] is None


@pytest.mark.asyncio
async def test_listing_is_ordered_newest_first(monkeypatch, tmp_path):
    for name in ("giljo_mcp.log.5", "giljo_mcp.log.1", "giljo_mcp.log.10", "giljo_mcp.log.2"):
        _seed(tmp_path, name)
    _seed(tmp_path, "giljo_mcp.log.2026-04-12")
    _seed(tmp_path, "giljo_mcp.log.2026-07-30")

    app = _build_app(monkeypatch, tmp_path)

    assert response_filenames(await _get(app, "/api/download/logs/archives")) == [
        "giljo_mcp.log.1",
        "giljo_mcp.log.2",
        "giljo_mcp.log.5",
        "giljo_mcp.log.10",
        "giljo_mcp.log.2026-07-30",
        "giljo_mcp.log.2026-04-12",
    ]


_PARENT_SENTINEL = "parent-sentinel.txt"
_SENTINEL_BODY = "must-not-be-served"


def _plant_canary(tmp_path) -> None:
    _seed(tmp_path, "giljo_mcp.log")
    _seed(tmp_path, "giljo_mcp.log.1")
    (tmp_path.parent / _PARENT_SENTINEL).write_text(_SENTINEL_BODY, encoding="utf-8")


_TRAVERSAL_ENCODINGS = ("%5C", "%00", "%0A")

_ENCODED_REFUSALS = [
    name
    for encoded in _TRAVERSAL_ENCODINGS
    for name in (
        f"giljo_mcp.log.1{encoded}..{encoded}..{encoded}{_PARENT_SENTINEL}",
        f"..{encoded}{_PARENT_SENTINEL}",
        f"giljo_mcp.log.1{encoded}.txt",
        f"giljo_mcp.log.1{encoded}",
        f"giljo_mcp.log.2026-04-12{encoded}",
    )
]

_REFUSED_BY_THE_ALLOWLIST = [
    *_ENCODED_REFUSALS,
    "giljo_mcp.log",
    "giljo_mcp.log.",
    "giljo_mcp.log.0",
    "giljo_mcp.log.01",
    "giljo_mcp.log.-1",
    "giljo_mcp.log.1.bak",
    "giljo_mcp.log.2026-04-12.gz",
    "giljo_mcp.log.abc",
    "GILJO_MCP.LOG.1",
    "giljo_mcp.log.%D9%A1",
    "giljo_mcp.log.%D9%A2%D9%A0%D9%A2%D9%A6-%D9%A0%D9%A4-%D9%A1%D9%A2",
    "giljo_mcpXlogX1",
]

_REFUSED_BY_THE_ROUTER = [
    f"../{_PARENT_SENTINEL}",
    f"../../{_PARENT_SENTINEL}",
    f"..%2F..%2F{_PARENT_SENTINEL}",
    "giljo_mcp.log.1/../../../etc/passwd",
    "/etc/passwd",
]


@pytest.mark.parametrize("filename", _REFUSED_BY_THE_ALLOWLIST)
@pytest.mark.asyncio
async def test_traversal_and_non_archive_filenames_are_rejected(monkeypatch, tmp_path, filename):
    _plant_canary(tmp_path)

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, f"/api/download/logs/archive/{filename}")

    assert response.status_code == 400, f"allowlist did not refuse {filename!r} (got {response.status_code})"
    assert _SENTINEL_BODY not in response.text


@pytest.mark.parametrize("filename", _REFUSED_BY_THE_ROUTER)
@pytest.mark.asyncio
async def test_slash_bearing_filenames_never_reach_the_download_route(monkeypatch, tmp_path, filename):
    _plant_canary(tmp_path)

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, f"/api/download/logs/archive/{filename}")

    assert response.status_code != 200, f"route served {filename!r}"
    assert _SENTINEL_BODY not in response.text


@pytest.mark.parametrize("filename", ["giljo_mcp.log.1%0A", "giljo_mcp.log.2026-04-12%0A"])
@pytest.mark.asyncio
async def test_trailing_newline_is_refused_by_the_allowlist_not_merely_missing(monkeypatch, tmp_path, filename):
    _seed(tmp_path, "giljo_mcp.log.1")
    _seed(tmp_path, "giljo_mcp.log.2026-04-12")

    app = _build_app(monkeypatch, tmp_path)
    response = await _get(app, f"/api/download/logs/archive/{filename}")

    assert response.status_code == 400, f"{filename!r} should be refused by the allowlist, got {response.status_code}"


@pytest.mark.asyncio
async def test_directory_named_like_an_archive_is_not_served(monkeypatch, tmp_path):
    (tmp_path / "giljo_mcp.log.3").mkdir()

    app = _build_app(monkeypatch, tmp_path)

    assert response_filenames(await _get(app, "/api/download/logs/archives")) == []
    assert (await _get(app, "/api/download/logs/archive/giljo_mcp.log.3")).status_code == 404


@pytest.mark.asyncio
async def test_archive_vanishing_mid_listing_does_not_500(monkeypatch, tmp_path):
    from pathlib import Path

    _seed(tmp_path, "giljo_mcp.log.1")
    _seed(tmp_path, "giljo_mcp.log.2")

    real_stat = Path.stat

    def vanishing_stat(self, *args, **kwargs):
        if self.name == "giljo_mcp.log.1":
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_stat(self, *args, **kwargs)

    app = _build_app(monkeypatch, tmp_path)
    monkeypatch.setattr(Path, "stat", vanishing_stat)
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200
    assert response_filenames(response) == ["giljo_mcp.log.2"]


@pytest.mark.asyncio
async def test_missing_log_dir_lists_empty_rather_than_erroring(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path / "does-not-exist")
    response = await _get(app, "/api/download/logs/archives")

    assert response.status_code == 200
    assert response.json() == []
