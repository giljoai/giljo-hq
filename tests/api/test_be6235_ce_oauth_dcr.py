# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest

from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class TestCeDcrEndpoint:

    @pytest.mark.asyncio
    async def test_register_returns_builtin_public_client(self, api_client):
        resp = await api_client.post(
            "/api/oauth/register",
            json={
                "client_name": "Claude Code",
                "redirect_uris": ["http://localhost:54545/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["client_id"] == BUILTIN_CLIENT_ID
        assert data["token_endpoint_auth_method"] == "none"
        assert "client_secret" not in data
        assert data["redirect_uris"] == ["http://localhost:54545/callback"]
        assert "authorization_code" in data["grant_types"]

    @pytest.mark.asyncio
    async def test_register_defaults_client_name_and_grants(self, api_client):
        resp = await api_client.post(
            "/api/oauth/register",
            json={"redirect_uris": ["http://127.0.0.1:8080/cb"]},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["client_id"] == BUILTIN_CLIENT_ID
        assert data["grant_types"] == ["authorization_code", "refresh_token"]
        assert data["response_types"] == ["code"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_uri",
        [
            "https://app.example.com/callback",
            "http://127.0.0.1.evil.test/cb",
            "http://localhost.evil.test/cb",
            "http://localhost@evil.test/cb",
            "http://[::1]@evil.test/cb",
            "https://localhost/cb",
            "http://evil.test/?x=http://localhost/",
        ],
    )
    async def test_register_rejects_non_loopback_redirect(self, api_client, bad_uri):
        resp = await api_client.post(
            "/api/oauth/register",
            json={"redirect_uris": [bad_uri]},
        )
        assert resp.status_code == 422, (
            f"SECURITY: DCR accepted a non-loopback redirect_uri — validator bypass detected!\n"
            f"  URI: {bad_uri!r}\n"
            f"  Status: {resp.status_code}\n"
            f"  Body: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_register_rejects_empty_redirect_list(self, api_client):
        resp = await api_client.post(
            "/api/oauth/register",
            json={"redirect_uris": []},
        )
        assert resp.status_code == 422, resp.text


class TestCeOAuthFullFlow:

    @pytest.mark.asyncio
    async def test_metadata_then_dcr_then_authorize_then_token(self, api_client, auth_headers):
        from api.endpoints.oauth import register_edition_registration_endpoint

        register_edition_registration_endpoint("/api/oauth/register")
        meta = (await api_client.get("/api/oauth/.well-known/oauth-authorization-server")).json()
        reg = meta["registration_endpoint"]
        assert reg.endswith("/api/oauth/register")

        redirect_uri = "http://localhost:7777/callback"
        dcr = await api_client.post(
            "/api/oauth/register",
            json={"client_name": "harness", "redirect_uris": [redirect_uri]},
        )
        assert dcr.status_code == 201, dcr.text
        client_id = dcr.json()["client_id"]
        assert client_id == BUILTIN_CLIENT_ID

        verifier, challenge = _pkce_pair()
        authz = await api_client.post(
            "/api/oauth/authorize",
            headers=auth_headers,
            json={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "mcp:read mcp:write",
                "state": "xyz",
                "response_type": "code",
            },
            follow_redirects=False,
        )
        assert authz.status_code == 200, authz.text
        target = authz.json()["redirect_uri"]
        code = parse_qs(urlparse(target).query)["code"][0]
        assert code

        tok = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
            },
        )
        assert tok.status_code == 200, tok.text
        body = tok.json()
        assert body["access_token"]
        assert body["token_type"].lower() == "bearer"
