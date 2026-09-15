# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, patch

import pytest

from giljo_mcp.services.version_service import VersionInfo, clear_cache


@pytest.fixture(autouse=True)
def _reset_version_cache():
    clear_cache()
    yield
    clear_cache()


class TestVersionEndpoint:
    @pytest.mark.asyncio
    async def test_returns_correct_format(self, api_client):
        mock_info = VersionInfo(
            installed_version="1.0.0",
            latest_version="1.2.0",
            latest_tarball_url="https://example.com/tarball.tar.gz",
            latest_sha256="abc123",
            update_available=True,
            checked_at="2026-04-14T20:00:00+00:00",
        )
        with patch(
            "api.endpoints.version.get_version_info",
            new_callable=AsyncMock,
            return_value=mock_info,
        ):
            resp = await api_client.get("/api/version/latest")

        assert resp.status_code == 200
        data = resp.json()
        assert data["installed_version"] == "1.0.0"
        assert data["latest_version"] == "1.2.0"
        assert data["latest_tarball_url"] == "https://example.com/tarball.tar.gz"
        assert data["latest_sha256"] == "abc123"
        assert data["update_available"] is True
        assert data["checked_at"] == "2026-04-14T20:00:00+00:00"

    @pytest.mark.asyncio
    async def test_no_auth_required(self, api_client):
        mock_info = VersionInfo(installed_version="0.0.0")
        with patch(
            "api.endpoints.version.get_version_info",
            new_callable=AsyncMock,
            return_value=mock_info,
        ):
            resp = await api_client.get("/api/version/latest")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_null_latest_when_github_unavailable(self, api_client):
        mock_info = VersionInfo(
            installed_version="1.0.0",
            latest_version=None,
            update_available=False,
            checked_at="2026-04-14T20:00:00+00:00",
        )
        with patch(
            "api.endpoints.version.get_version_info",
            new_callable=AsyncMock,
            return_value=mock_info,
        ):
            resp = await api_client.get("/api/version/latest")

        assert resp.status_code == 200
        data = resp.json()
        assert data["latest_version"] is None
        assert data["update_available"] is False

    @pytest.mark.asyncio
    async def test_response_includes_all_fields(self, api_client):
        mock_info = VersionInfo(installed_version="unknown")
        with patch(
            "api.endpoints.version.get_version_info",
            new_callable=AsyncMock,
            return_value=mock_info,
        ):
            resp = await api_client.get("/api/version/latest")

        data = resp.json()
        expected_keys = {
            "installed_version",
            "latest_version",
            "latest_tarball_url",
            "latest_sha256",
            "update_available",
            "checked_at",
        }
        assert set(data.keys()) == expected_keys
