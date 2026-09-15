# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock

import pytest
import yaml

from giljo_mcp.config_manager import ConfigManager




def _make_config(tmp_path, ssl_enabled: bool) -> ConfigManager:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "server": {"api": {"host": "0.0.0.0", "port": 7272}},
                "features": {"ssl_enabled": ssl_enabled},
                "services": {"external_host": "192.0.2.10"},
                "paths": {"ssl_cert": "/tmp/cert.pem", "ssl_key": "/tmp/key.pem"},
            }
        )
    )
    mgr = ConfigManager(config_path=config_file)
    mgr.load()
    return mgr


@pytest.fixture
def ssl_config(tmp_path):
    return _make_config(tmp_path, ssl_enabled=True)


@pytest.fixture
def no_ssl_config(tmp_path):
    return _make_config(tmp_path, ssl_enabled=False)


@pytest.fixture
def ssl_config_data():
    return {
        "server": {"api": {"host": "0.0.0.0", "port": 7272}},
        "features": {"ssl_enabled": True},
        "services": {"external_host": "192.0.2.10"},
    }




class TestDownloadsGetPublicBaseUrl:

    def test_https_from_request_base_url(self):
        from giljo_mcp.http.url_resolver import get_public_base_url

        mock_request = MagicMock()
        mock_request.base_url.__str__ = lambda _self: "https://mcp.example.com/"
        assert get_public_base_url(mock_request) == "https://mcp.example.com"

    def test_http_from_request_base_url(self):
        from giljo_mcp.http.url_resolver import get_public_base_url

        mock_request = MagicMock()
        mock_request.base_url.__str__ = lambda _self: "http://localhost:7272/"
        assert get_public_base_url(mock_request) == "http://localhost:7272"




class TestAiToolsEndpointProtocol:

    def test_https_when_ssl_enabled(self, ssl_config):
        protocol = "https" if ssl_config.get_nested("features.ssl_enabled", False) else "http"
        assert protocol == "https"

    def test_http_when_ssl_disabled(self, no_ssl_config):
        protocol = "https" if no_ssl_config.get_nested("features.ssl_enabled", False) else "http"
        assert protocol == "http"




class TestToolAccessorDownloadUrl:

    def test_download_url_uses_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("GILJO_PUBLIC_URL", "https://mcp.example.com")
        import os

        server_url = os.environ.get("GILJO_PUBLIC_URL", "http://localhost:7272")
        assert server_url == "https://mcp.example.com"

    def test_download_url_default_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        import os

        server_url = os.environ.get("GILJO_PUBLIC_URL", "http://localhost:7272")
        assert server_url == "http://localhost:7272"




class TestConfigurationEndpointProtocol:

    def test_api_protocol_https_when_ssl_enabled(self, ssl_config):
        ssl_enabled = ssl_config.get_nested("features.ssl_enabled", False)
        api_protocol = "https" if ssl_enabled else "http"
        ws_protocol = "wss" if ssl_enabled else "ws"
        assert api_protocol == "https"
        assert ws_protocol == "wss"

    def test_api_protocol_http_when_ssl_disabled(self, no_ssl_config):
        ssl_enabled = no_ssl_config.get_nested("features.ssl_enabled", False)
        api_protocol = "https" if ssl_enabled else "http"
        ws_protocol = "wss" if ssl_enabled else "ws"
        assert api_protocol == "http"
        assert ws_protocol == "ws"




class TestNoHttpUrlsWhenSslEnabled:

    def test_downloads_no_http(self):
        from giljo_mcp.http.url_resolver import get_public_base_url

        mock_request = MagicMock()
        mock_request.base_url.__str__ = lambda _self: "https://mcp.example.com/"
        url = get_public_base_url(mock_request)
        assert "http://" not in url, f"Found http:// in downloads URL: {url}"

    def test_ai_tools_no_http(self, ssl_config):
        protocol = "https" if ssl_config.get_nested("features.ssl_enabled", False) else "http"
        server_url = f"{protocol}://192.0.2.10:7272"
        assert "http://" not in server_url

    def test_config_endpoint_no_ws(self, ssl_config):
        ssl_enabled = ssl_config.get_nested("features.ssl_enabled", False)
        ws_protocol = "wss" if ssl_enabled else "ws"
        ws_url = f"{ws_protocol}://192.0.2.10:7272"
        assert "ws://" not in ws_url, f"Found ws:// in websocket URL: {ws_url}"
