# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from giljo_mcp.services.version_service import (
    CACHE_TTL_SECONDS,
    clear_cache,
    compare_versions,
    get_installed_version,
    get_version_info,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_cache()
    yield
    clear_cache()




class TestGetInstalledVersion:
    def test_reads_version_file(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.2.3\n")
        assert get_installed_version(tmp_path) == "1.2.3"

    def test_strips_whitespace(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("  0.9.1  \n")
        assert get_installed_version(tmp_path) == "0.9.1"

    def test_missing_file_returns_unknown(self, tmp_path: Path):
        assert get_installed_version(tmp_path) == "unknown"




class TestCompareVersions:
    def test_newer_version(self):
        assert compare_versions("1.0.0", "1.2.0") is True

    def test_same_version(self):
        assert compare_versions("1.0.0", "1.0.0") is False

    def test_older_latest(self):
        assert compare_versions("2.0.0", "1.0.0") is False

    def test_invalid_installed(self):
        assert compare_versions("unknown", "1.0.0") is False

    def test_invalid_latest(self):
        assert compare_versions("1.0.0", "bad") is False

    def test_both_invalid(self):
        assert compare_versions("x", "y") is False

    def test_patch_bump(self):
        assert compare_versions("1.0.0", "1.0.1") is True

    def test_major_bump(self):
        assert compare_versions("1.9.9", "2.0.0") is True




def _github_release_payload(
    tag: str = "v1.2.0",
    tarball_name: str = "giljoai-mcp-1.2.0.tar.gz",
    tarball_url: str = "https://example.com/giljoai-mcp-1.2.0.tar.gz",
    include_manifest: bool = False,
) -> dict:
    assets = [
        {"name": tarball_name, "browser_download_url": tarball_url},
    ]
    if include_manifest:
        assets.append(
            {
                "name": "version-manifest.json",
                "browser_download_url": "https://example.com/version-manifest.json",
            }
        )
    return {"tag_name": tag, "assets": assets}


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


class TestGetVersionInfoFetch:
    @pytest.mark.asyncio
    async def test_fresh_fetch_success(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _mock_response(200, _github_release_payload())

        info = await get_version_info(root=tmp_path, client=mock_client)

        assert info.installed_version == "1.0.0"
        assert info.latest_version == "1.2.0"
        assert info.update_available is True
        assert info.latest_tarball_url == "https://example.com/giljoai-mcp-1.2.0.tar.gz"
        assert info.checked_at is not None

    @pytest.mark.asyncio
    async def test_fetch_with_manifest(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)

        release_resp = _mock_response(200, _github_release_payload(include_manifest=True))
        manifest_resp = _mock_response(
            200,
            {
                "tarball_url": "https://cdn.example.com/manifest-tarball.tar.gz",
                "sha256": "abc123def456",
            },
        )

        mock_client.get.side_effect = [release_resp, manifest_resp]

        info = await get_version_info(root=tmp_path, client=mock_client)

        assert info.latest_tarball_url == "https://cdn.example.com/manifest-tarball.tar.gz"
        assert info.latest_sha256 == "abc123def456"

    @pytest.mark.asyncio
    async def test_no_releases_404(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _mock_response(404)

        info = await get_version_info(root=tmp_path, client=mock_client)

        assert info.installed_version == "1.0.0"
        assert info.latest_version is None
        assert info.update_available is False

    @pytest.mark.asyncio
    async def test_rate_limit_403(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _mock_response(403)

        info = await get_version_info(root=tmp_path, client=mock_client)

        assert info.latest_version is None
        assert info.update_available is False

    @pytest.mark.asyncio
    async def test_network_error(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        info = await get_version_info(root=tmp_path, client=mock_client)

        assert info.installed_version == "1.0.0"
        assert info.latest_version is None
        assert info.update_available is False

    @pytest.mark.asyncio
    async def test_malformed_github_response(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _mock_response(200, {})

        info = await get_version_info(root=tmp_path, client=mock_client)

        assert info.latest_version is None
        assert info.update_available is False




class TestCaching:
    @pytest.mark.asyncio
    async def test_cached_return_no_refetch(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _mock_response(200, _github_release_payload())

        now = time.monotonic()

        info1 = await get_version_info(root=tmp_path, client=mock_client, _now=now)
        assert info1.latest_version == "1.2.0"
        assert mock_client.get.call_count == 1

        info2 = await get_version_info(root=tmp_path, client=mock_client, _now=now + 100)
        assert info2.latest_version == "1.2.0"
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_expiry_refetches(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _mock_response(200, _github_release_payload())

        now = time.monotonic()

        await get_version_info(root=tmp_path, client=mock_client, _now=now)
        assert mock_client.get.call_count == 1

        await get_version_info(root=tmp_path, client=mock_client, _now=now + CACHE_TTL_SECONDS + 1)
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_returns_fresh_installed_version(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _mock_response(200, _github_release_payload(tag="v1.2.0"))

        now = time.monotonic()
        info1 = await get_version_info(root=tmp_path, client=mock_client, _now=now)
        assert info1.installed_version == "1.0.0"
        assert info1.update_available is True

        (tmp_path / "VERSION").write_text("1.2.0\n")
        info2 = await get_version_info(root=tmp_path, client=mock_client, _now=now + 10)
        assert info2.installed_version == "1.2.0"
        assert info2.update_available is False

    @pytest.mark.asyncio
    async def test_network_error_after_cache_expiry(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _mock_response(200, _github_release_payload())

        now = time.monotonic()
        await get_version_info(root=tmp_path, client=mock_client, _now=now)

        mock_client.get.side_effect = httpx.ConnectError("timeout")
        info = await get_version_info(root=tmp_path, client=mock_client, _now=now + CACHE_TTL_SECONDS + 1)
        assert info.latest_version is None
