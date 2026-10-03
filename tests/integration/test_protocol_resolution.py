# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock, patch






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

    @staticmethod
    def _call(scheme: str, host: str):
        import asyncio

        from starlette.requests import Request

        from api.endpoints.configuration import get_frontend_configuration

        request = Request(
            {
                "type": "http",
                "scheme": scheme,
                "server": (host, 443 if scheme == "https" else 7272),
                "path": "/api/v1/config/frontend",
                "headers": [(b"host", host.encode())],
                "query_string": b"",
                "root_path": "",
            }
        )
        state = MagicMock()
        state.config.get_nested.return_value = False
        state.config.tenant.default_tenant_key = "tk_test"
        with patch("api.app_state.state", state):
            return asyncio.run(get_frontend_configuration(request))

    def test_http_request_yields_http_and_ws(self):
        cfg = self._call("http", "192.0.2.10:7272")
        assert cfg["api"]["protocol"] == "http"
        assert cfg["websocket"]["protocol"] == "ws"
        assert "ssl_enabled" not in cfg["api"]
        assert "is_remote_client" not in cfg["api"]

    def test_proxied_https_request_yields_https_and_wss(self):
        cfg = self._call("https", "giljo.example.com")
        assert cfg["api"]["protocol"] == "https"
        assert cfg["websocket"]["protocol"] == "wss"
