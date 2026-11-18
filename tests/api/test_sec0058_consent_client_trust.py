# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from pathlib import Path

import pytest

from api.endpoints import oauth_client_info
from giljo_mcp.services.oauth_service import (
    BUILTIN_CLIENT_ID,
    OAUTH_GRANTABLE_SCOPES,
    ResolvedClient,
    get_client_resolver,
    set_client_resolver,
)


DCR_ID = "7c1f0d3e-2b51-4f7e-9a51-1f2d3c4b5a69"
LOOKALIKE_CIMD = "https://lookalike.example/client.json"
CLAUDE_CIMD = "https://claude.ai/oauth/mcp-oauth-client-metadata"


@pytest.fixture
def dcr_claude_lookalike():
    original = get_client_resolver()

    def resolver(client_id, tenant_key):
        if client_id != DCR_ID:
            return original(client_id, tenant_key)
        return ResolvedClient(
            client_id=DCR_ID,
            client_name="Claude",
            redirect_uris=[
                "https://attacker.example/cb",
                "https://\u0441laude.ai/cb",
                "https://attacker.example\\@claude.ai/cb",
            ],
            client_secret_hash=None,
        )

    set_client_resolver(resolver)
    yield
    set_client_resolver(original)


DCR_SHAPES = {
    "0b6f5f7e-0000-4000-8000-000000000001": ["https://chatgpt.com/connector_platform_oauth_redirect"],
    "0b6f5f7e-0000-4000-8000-000000000002": [
        "https://chatgpt.com/connector_platform_oauth_redirect",
        "https://attacker.example/cb",
    ],
    "0b6f5f7e-0000-4000-8000-000000000003": ["http://chatgpt.com/connector_platform_oauth_redirect"],
    "0b6f5f7e-0000-4000-8000-000000000004": ["https://attacker.example\\@chatgpt.com/cb"],
    "0b6f5f7e-0000-4000-8000-000000000005": ["http://127.0.0.1:33418/callback"],
    "0b6f5f7e-0000-4000-8000-000000000006": ["https://chatgpt.com:8443/cb"],
    "0b6f5f7e-0000-4000-8000-000000000007": ["https://:@chatgpt.com/cb"],
}
DCR_CHATGPT, DCR_MIXED, DCR_HTTP, DCR_BACKSLASH, DCR_LOOPBACK, DCR_PORT, DCR_USERINFO = DCR_SHAPES


@pytest.fixture
def dcr_shapes():
    original = get_client_resolver()

    def resolver(client_id, tenant_key):
        uris = DCR_SHAPES.get(client_id)
        if uris is None:
            return original(client_id, tenant_key)
        return ResolvedClient(client_id=client_id, client_name="ChatGPT", redirect_uris=uris, client_secret_hash=None)

    set_client_resolver(resolver)
    yield
    set_client_resolver(original)


@pytest.fixture
def cimd_documents(monkeypatch):
    documents = {
        LOOKALIKE_CIMD: ["https://attacker.example/cb"],
        CLAUDE_CIMD: ["https://claude.ai/api/mcp/auth_callback"],
    }

    async def fake_resolve(client_id):
        uris = documents.get(client_id)
        if uris is None:
            return None
        return ResolvedClient(client_id=client_id, client_name="Claude", redirect_uris=uris, client_secret_hash=None)

    monkeypatch.setattr(oauth_client_info, "resolve_cimd_client", fake_resolve)


async def _lookup(api_client, auth_headers, client_id, redirect_uri=None):
    params = {"client_id": client_id}
    if redirect_uri is not None:
        params["redirect_uri"] = redirect_uri
    return await api_client.get("/api/oauth/authorize/client", headers=auth_headers, params=params)


class TestRedirectHost:
    @pytest.mark.asyncio
    async def test_self_registered_client_returns_its_redirect_host(
        self, api_client, auth_headers, dcr_claude_lookalike
    ):
        response = await _lookup(api_client, auth_headers, DCR_ID, "https://attacker.example/cb")
        assert response.status_code == 200
        body = response.json()
        assert body["client_name"] == "Claude"
        assert body["redirect_host"] == "attacker.example"
        assert body["redirect_is_local"] is False

    @pytest.mark.asyncio
    async def test_loopback_redirect_is_flagged_local(self, api_client, auth_headers):
        response = await _lookup(api_client, auth_headers, BUILTIN_CLIENT_ID, "http://127.0.0.1:5173/callback")
        assert response.status_code == 200
        body = response.json()
        assert body["redirect_is_local"] is True
        assert body["verified"] is True

    @pytest.mark.asyncio
    async def test_unregistered_redirect_is_refused_without_echo(self, api_client, auth_headers, dcr_claude_lookalike):
        response = await _lookup(api_client, auth_headers, DCR_ID, "https://elsewhere.example/cb")
        assert response.status_code == 400
        assert "elsewhere.example" not in response.text

    @pytest.mark.asyncio
    async def test_unicode_host_is_not_vouched_for(self, api_client, auth_headers, dcr_claude_lookalike):
        response = await _lookup(api_client, auth_headers, DCR_ID, "https://\u0441laude.ai/cb")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_backslash_host_trick_is_not_vouched_for(self, api_client, auth_headers, dcr_claude_lookalike):
        response = await _lookup(api_client, auth_headers, DCR_ID, "https://attacker.example\\@claude.ai/cb")
        assert response.status_code == 400
        assert "claude.ai" not in response.text

    @pytest.mark.asyncio
    async def test_url_metadata_client_also_returns_its_publisher_host(self, api_client, auth_headers, cimd_documents):
        response = await _lookup(api_client, auth_headers, LOOKALIKE_CIMD, "https://attacker.example/cb")
        assert response.status_code == 200
        body = response.json()
        assert body["redirect_host"] == "attacker.example"
        assert body["client_id_host"] == "lookalike.example"


class TestVerifiedFlag:
    @pytest.mark.asyncio
    async def test_self_registered_client_named_like_a_known_app_is_unverified(
        self, api_client, auth_headers, dcr_claude_lookalike
    ):
        response = await _lookup(api_client, auth_headers, DCR_ID, "https://attacker.example/cb")
        assert response.json()["verified"] is False

    @pytest.mark.asyncio
    async def test_operator_listed_client_id_is_verified(
        self, api_client, auth_headers, dcr_claude_lookalike, monkeypatch
    ):
        monkeypatch.setenv("GILJO_OAUTH_KNOWN_CLIENT_IDS", f" {DCR_ID} , other ")
        response = await _lookup(api_client, auth_headers, DCR_ID, "https://attacker.example/cb")
        assert response.json()["verified"] is True

    @pytest.mark.asyncio
    async def test_url_metadata_client_on_a_lookalike_host_is_unverified(
        self, api_client, auth_headers, cimd_documents
    ):
        response = await _lookup(api_client, auth_headers, LOOKALIKE_CIMD, "https://attacker.example/cb")
        assert response.json()["verified"] is False

    @pytest.mark.asyncio
    async def test_url_metadata_client_on_a_known_host_is_verified(self, api_client, auth_headers, cimd_documents):
        response = await _lookup(api_client, auth_headers, CLAUDE_CIMD, "https://claude.ai/api/mcp/auth_callback")
        body = response.json()
        assert body["verified"] is True
        assert body["redirect_host"] == "claude.ai"

    @pytest.mark.asyncio
    async def test_operator_can_replace_the_known_host_list(
        self, api_client, auth_headers, cimd_documents, monkeypatch
    ):
        monkeypatch.setenv("GILJO_OAUTH_KNOWN_CLIENT_HOSTS", "lookalike.example")
        known = await _lookup(api_client, auth_headers, LOOKALIKE_CIMD, "https://attacker.example/cb")
        dropped = await _lookup(api_client, auth_headers, CLAUDE_CIMD, "https://claude.ai/api/mcp/auth_callback")
        assert known.json()["verified"] is True
        assert dropped.json()["verified"] is False


class TestKnownAppSite:

    @pytest.mark.asyncio
    async def test_dcr_client_with_only_known_site_redirects_is_known(self, api_client, auth_headers, dcr_shapes):
        response = await _lookup(
            api_client, auth_headers, DCR_CHATGPT, "https://chatgpt.com/connector_platform_oauth_redirect"
        )
        assert response.status_code == 200
        assert response.json()["verified"] is True
        assert response.json()["redirect_host"] == "chatgpt.com"

    @pytest.mark.asyncio
    async def test_one_unlisted_redirect_makes_it_unverified(self, api_client, auth_headers, dcr_shapes):
        response = await _lookup(
            api_client, auth_headers, DCR_MIXED, "https://chatgpt.com/connector_platform_oauth_redirect"
        )
        assert response.status_code == 200
        assert response.json()["verified"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("client_id", [DCR_HTTP, DCR_BACKSLASH, DCR_PORT, DCR_USERINFO])
    async def test_http_ambiguous_or_odd_known_host_redirect_is_unverified(
        self, api_client, auth_headers, dcr_shapes, client_id
    ):
        response = await _lookup(api_client, auth_headers, client_id)
        assert response.status_code == 200
        assert response.json()["verified"] is False

    @pytest.mark.asyncio
    async def test_backslash_redirect_is_still_refused_as_a_destination(self, api_client, auth_headers, dcr_shapes):
        response = await _lookup(api_client, auth_headers, DCR_BACKSLASH, "https://attacker.example\\@chatgpt.com/cb")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_loopback_client_is_local_not_known(self, api_client, auth_headers, dcr_shapes):
        response = await _lookup(api_client, auth_headers, DCR_LOOPBACK, "http://127.0.0.1:33418/callback")
        body = response.json()
        assert body["redirect_is_local"] is True
        assert body["verified"] is False


def test_every_grantable_scope_has_plain_words_on_the_consent_screen():
    copy_module = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "oauthScopeCopy.js"
    source = copy_module.read_text(encoding="utf-8")
    for scope in sorted(OAUTH_GRANTABLE_SCOPES):
        entry = re.search(rf"'{re.escape(scope)}':\s*\{{(?P<body>[^}}]*)\}}", source)
        assert entry, f"{scope} has no entry in oauthScopeCopy.js"
        assert re.search(r"label:\s*'[^']+'", entry["body"]), f"{scope} has no label"
        assert re.search(r"description:\s*'[^']+'", entry["body"]), f"{scope} has no description"
