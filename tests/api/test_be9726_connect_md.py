# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from api.endpoints import connect_page
from giljo_mcp import branding


API_KEY_SHAPED = ("sk_", "tk_", "gk_")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(connect_page.router)
    return TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"))


@pytest.fixture
def ce_mode(monkeypatch):
    monkeypatch.setenv("GILJO_MODE", "ce")
    monkeypatch.delenv("GILJO_PUBLIC_BASE_URL", raising=False)


@pytest.fixture
def saas_mode(monkeypatch):
    monkeypatch.setenv("GILJO_MODE", "saas")
    monkeypatch.setenv("GILJO_PUBLIC_BASE_URL", "https://app.example.test")


def test_serves_markdown_without_auth(client, ce_mode):
    resp = client.get("/connect.md", headers={"Host": "localhost:7272"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "giljo_setup" in resp.text


def test_ce_plain_http_lan_requires_api_key_path(client, ce_mode):
    resp = client.get("/connect.md", headers={"Host": "192.0.2.10:7272"})
    body = resp.text
    assert f"claude mcp add --scope user --transport http {branding.MCP_ALIAS} http://192.0.2.10:7272/mcp" in body
    assert "Authorization: Bearer <YOUR_API_KEY>" in body
    assert "--bearer-token-env-var GILJO_API_KEY" in body
    assert "Tools > Connect" in body
    assert "mcp auth" not in body
    assert f"claude mcp add --transport http {branding.MCP_ALIAS} http://192.0.2.10:7272/mcp --scope user" not in body


def test_ce_localhost_http_uses_oauth(client, ce_mode):
    body = client.get("/connect.md", headers={"Host": "localhost:7272"}).text
    assert f"claude mcp add --transport http {branding.MCP_ALIAS} http://localhost:7272/mcp --scope user" in body
    assert "Authorization: Bearer" not in body


def test_ce_https_forwarded_proto_uses_oauth(client, ce_mode):
    body = client.get("/connect.md", headers={"Host": "hq.acme.corp", "X-Forwarded-Proto": "https"}).text
    assert f"claude mcp add --transport http {branding.MCP_ALIAS} https://hq.acme.corp/mcp --scope user" in body
    assert f"codex mcp add {branding.MCP_ALIAS} --url https://hq.acme.corp/mcp\n" in body
    assert "http://hq.acme.corp" not in body
    assert "Authorization: Bearer" not in body


def test_saas_renders_pinned_https_origin_ignoring_host_header(client, saas_mode):
    body = client.get("/connect.md", headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example"}).text
    assert f"claude mcp add --transport http {branding.MCP_ALIAS} https://app.example.test/mcp --scope user" in body
    assert "evil.example" not in body
    assert "Authorization: Bearer" not in body


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "192.0.2.10:7272"},
        {"Host": "localhost:7272"},
        {"Host": "hq.acme.corp", "X-Forwarded-Proto": "https"},
    ],
)
def test_page_never_contains_a_key(client, ce_mode, headers):
    body = client.get("/connect.md", headers=headers).text
    assert not any(prefix in body for prefix in API_KEY_SHAPED)
    assert "giljo_setup" in body


def test_page_covers_every_harness(client, ce_mode):
    body = client.get("/connect.md", headers={"Host": "localhost:7272"}).text
    for heading in ("Claude Code", "Codex CLI", "OpenCode", "Generic MCP client", "Claude Desktop"):
        assert heading in body


def test_host_header_injection_is_rejected_not_rendered(client, ce_mode):
    resp = client.get("/connect.md", headers={"Host": "x.test\nInjected: 1"})
    assert "Injected" not in resp.text


def test_connect_md_is_public_on_the_real_app_and_not_swallowed_by_spa(monkeypatch):
    monkeypatch.setenv("GILJO_MODE", "ce")
    from api.app import app

    resp = TestClient(app).get("/connect.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "giljo_setup" in resp.text
