# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from pathlib import Path

from installer.core.config import ConfigManager


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _base_settings(tmp_path: Path) -> dict:
    return {
        "install_dir": str(tmp_path),
        "owner_password": "owner-secret",  # pragma: allowlist secret
        "user_password": "user-secret",  # pragma: allowlist secret
        "pg_password": "super-secret",  # pragma: allowlist secret
        "api_port": 7272,
        "dashboard_port": 7274,
        "db_name": "giljo_mcp",
    }


def _generate(tmp_path: Path, extra: dict) -> dict[str, str]:
    settings = _base_settings(tmp_path)
    settings.update(extra)
    result = ConfigManager(settings=settings).generate_env_file()
    assert result["success"], result.get("errors")
    return _parse_env(tmp_path / ".env")


class TestLanHttpsEnvUrls:
    def test_lan_https_does_not_write_localhost_http_urls(self, tmp_path):
        env = _generate(
            tmp_path,
            {
                "bind": "0.0.0.0",
                "external_host": "192.0.2.163",
                "network_mode": "auto",
                "ssl_enabled": True,
                "ssl_cert": "/certs/cert.pem",
                "ssl_key": "/certs/key.pem",
            },
        )

        assert env["VITE_API_URL"] == ""
        assert env["VITE_WS_URL"] == ""
        assert "localhost" not in env["VITE_API_URL"]
        assert "http://" not in env["VITE_API_URL"]

        assert env["GILJO_PUBLIC_URL"] == "https://192.0.2.163:7272"

        assert env["VITE_APP_MODE"] == "auto"
        assert env["DEPLOYMENT_CONTEXT"] == "auto"

        assert env["SERVICE_BIND"] == "0.0.0.0"
        assert env["GILJO_API_HOST"] == "0.0.0.0"

    def test_lan_http_no_ssl_still_avoids_localhost(self, tmp_path):
        env = _generate(
            tmp_path,
            {
                "bind": "0.0.0.0",
                "external_host": "192.0.2.163",
                "network_mode": "static",
                "ssl_enabled": False,
            },
        )
        assert env["VITE_API_URL"] == ""
        assert env["VITE_WS_URL"] == ""
        assert env["GILJO_PUBLIC_URL"] == "http://192.0.2.163:7272"
        assert env["VITE_APP_MODE"] == "static"

    def test_localhost_install_unchanged(self, tmp_path):
        env = _generate(
            tmp_path,
            {
                "bind": "127.0.0.1",
                "external_host": "localhost",
                "network_mode": "localhost",
                "ssl_enabled": False,
            },
        )
        assert env["VITE_API_URL"] == "http://localhost:7272"
        assert env["VITE_WS_URL"] == "ws://localhost:7272"
        assert env["VITE_APP_MODE"] == "localhost"
        assert env["DEPLOYMENT_CONTEXT"] == "localhost"

    def test_required_env_keys_present_even_when_empty(self, tmp_path):
        _generate(
            tmp_path,
            {
                "bind": "0.0.0.0",
                "external_host": "192.0.2.163",
                "network_mode": "auto",
                "ssl_enabled": True,
            },
        )
        content = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "VITE_API_URL=" in content
        assert "VITE_WS_URL=" in content
