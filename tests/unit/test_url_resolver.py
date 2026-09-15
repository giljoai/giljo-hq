# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock

from giljo_mcp.http.url_resolver import get_public_base_url


def _make_request(base_url: str) -> MagicMock:
    request = MagicMock()
    request.base_url = MagicMock()
    request.base_url.__str__ = lambda _self: base_url
    return request


class TestGetPublicBaseUrl:

    def test_localhost_http(self):
        request = _make_request("http://localhost:7272/")
        assert get_public_base_url(request) == "http://localhost:7272"

    def test_lan_https_with_port(self):
        request = _make_request("https://192.0.2.42:7272/")
        assert get_public_base_url(request) == "https://192.0.2.42:7272"

    def test_cloudflare_tunnel_no_port(self):
        request = _make_request("https://mcp.example.com/")
        assert get_public_base_url(request) == "https://mcp.example.com"

    def test_customer_nginx_proxy(self):
        request = _make_request("https://mcp.acme.corp/")
        assert get_public_base_url(request) == "https://mcp.acme.corp"

    def test_saas_production(self):
        request = _make_request("https://app.example.com/")
        assert get_public_base_url(request) == "https://app.example.com"

    def test_no_trailing_slash_input(self):
        request = _make_request("http://localhost:7272")
        assert get_public_base_url(request) == "http://localhost:7272"

    def test_returns_str(self):
        request = _make_request("http://localhost:7272/")
        assert isinstance(get_public_base_url(request), str)
