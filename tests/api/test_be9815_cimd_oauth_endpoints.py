# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from giljo_mcp.services import oauth_cimd
from giljo_mcp.services.oauth_cimd import FetchedDocument
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID


CIMD_URL = "https://app.example.com/.well-known/oauth-client/giljo-connector/metadata-document.json"
REDIRECT = "http://localhost:53682/callback"
PUBLIC_ADDRESS = "93.184.216.34"


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _doc(client_id: str = CIMD_URL, **overrides) -> bytes:
    body = {"client_id": client_id, "client_name": "Example Connector", "redirect_uris": [REDIRECT]}
    body.update(overrides)
    return json.dumps(body).encode()


class _Network:

    def __init__(self) -> None:
        self.body: bytes | None = _doc()
        self.fetches = 0
        self.delay = 0.0

    async def fetch(self, url, parts, address):
        self.fetches += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.body is None:
            raise oauth_cimd.CimdError("client metadata URL answered 404")
        return FetchedDocument(status=200, cache_control=None, body=self.body)


@pytest.fixture
def network(monkeypatch):
    oauth_cimd.clear_cache()
    net = _Network()

    async def public(host, port):
        return [PUBLIC_ADDRESS]

    monkeypatch.setattr(oauth_cimd, "_lookup", public)
    monkeypatch.setattr(oauth_cimd, "fetch_document", net.fetch)
    yield net
    oauth_cimd.clear_cache()


def _authorize_payload(client_id: str = CIMD_URL, redirect_uri: str = REDIRECT, challenge: str | None = None) -> dict:
    return {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge or _pkce_pair()[1],
        "code_challenge_method": "S256",
        "scope": "mcp:read mcp:write",
        "state": "xyz",
        "response_type": "code",
    }


async def _authorize(api_client, auth_headers, **kwargs):
    return await api_client.post(
        "/api/oauth/authorize", headers=auth_headers, json=_authorize_payload(**kwargs), follow_redirects=False
    )


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


@pytest.mark.asyncio
class TestCimdAuthorizeAndToken:
    async def test_full_flow_for_a_cimd_client(self, api_client, auth_headers, network):
        assert len(CIMD_URL) > 64
        verifier, challenge = _pkce_pair()

        authz = await _authorize(api_client, auth_headers, challenge=challenge)
        assert authz.status_code == 200, authz.text
        code = parse_qs(urlparse(authz.json()["redirect_uri"]).query)["code"][0]

        tok = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
                "client_id": CIMD_URL,
            },
        )
        assert tok.status_code == 200, tok.text
        body = tok.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert _claims(body["access_token"])["cid"] == CIMD_URL

        refreshed = await api_client.post(
            "/api/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": CIMD_URL},
        )
        assert refreshed.status_code == 200, refreshed.text
        assert _claims(refreshed.json()["access_token"])["cid"] == CIMD_URL

    async def test_a_token_for_a_registered_client_carries_no_cid_claim(self, api_client, auth_headers, network):
        verifier, challenge = _pkce_pair()
        authz = await _authorize(api_client, auth_headers, client_id=BUILTIN_CLIENT_ID, challenge=challenge)
        assert authz.status_code == 200, authz.text
        code = parse_qs(urlparse(authz.json()["redirect_uri"]).query)["code"][0]
        tok = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
                "client_id": BUILTIN_CLIENT_ID,
            },
        )
        assert tok.status_code == 200, tok.text
        assert "cid" not in _claims(tok.json()["access_token"])
        assert network.fetches == 0

    async def test_an_unknown_non_url_client_id_is_still_refused(self, api_client, auth_headers, network):
        resp = await _authorize(api_client, auth_headers, client_id="not-registered")
        assert resp.status_code == 400
        assert network.fetches == 0

    @pytest.mark.parametrize(
        "served",
        [
            b"not json",
            b"[]",
            _doc(client_id="https://other.example.com/meta.json"),
            _doc(redirect_uris=["http://localhost:1111/other"]),
            _doc(redirect_uris=["https://app.example.com/other-callback"]),
            _doc(client_name="x" * 20000),
        ],
        ids=[
            "bad-json",
            "not-an-object",
            "client-id-mismatch",
            "redirect-not-listed",
            "https-redirect-not-the-requested-one",
            "oversize",
        ],
    )
    async def test_bad_documents_are_refused_at_authorize(self, api_client, auth_headers, network, served):
        network.body = served
        resp = await _authorize(api_client, auth_headers)
        assert resp.status_code == 400, resp.text

    async def test_ce_accepts_a_hosted_app_document_with_only_an_https_redirect(
        self, api_client, auth_headers, network, monkeypatch
    ):
        monkeypatch.setenv("GILJO_MODE", "ce")
        hosted_redirect = "https://claude.example.com/api/mcp/auth_callback"
        network.body = _doc(redirect_uris=[hosted_redirect])
        verifier, challenge = _pkce_pair()
        authz = await _authorize(api_client, auth_headers, redirect_uri=hosted_redirect, challenge=challenge)
        assert authz.status_code == 200, authz.text
        target = authz.json()["redirect_uri"]
        assert target.startswith(hosted_redirect + "?")
        code = parse_qs(urlparse(target).query)["code"][0]
        tok = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": hosted_redirect,
                "client_id": CIMD_URL,
            },
        )
        assert tok.status_code == 200, tok.text
        wrong = await _authorize(api_client, auth_headers, redirect_uri="https://claude.example.com/other")
        assert wrong.status_code == 400

    async def test_loopback_port_may_differ_from_the_one_in_the_document(self, api_client, auth_headers, network):
        network.body = _doc(redirect_uris=["http://localhost/callback", "http://127.0.0.1/callback"])
        ok = await _authorize(api_client, auth_headers, redirect_uri="http://127.0.0.1:61234/callback")
        assert ok.status_code == 200, ok.text
        assert ok.json()["redirect_uri"].startswith("http://127.0.0.1:61234/callback?")
        wrong_path = await _authorize(api_client, auth_headers, redirect_uri="http://127.0.0.1:61234/elsewhere")
        assert wrong_path.status_code == 400

    async def test_a_document_preferring_private_key_jwt_is_served_as_a_public_pkce_client(
        self, api_client, auth_headers, network
    ):
        network.body = _doc(
            token_endpoint_auth_method="private_key_jwt",
            jwks_uri="https://app.example.com/jwks.json",
            grant_types=["authorization_code", "urn:ietf:params:oauth:grant-type:jwt-bearer"],
        )
        verifier, challenge = _pkce_pair()
        authz = await _authorize(api_client, auth_headers, challenge=challenge)
        assert authz.status_code == 200, authz.text
        code = parse_qs(urlparse(authz.json()["redirect_uri"]).query)["code"][0]
        tok = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
                "client_id": CIMD_URL,
            },
        )
        assert tok.status_code == 200, tok.text

    async def test_redirect_uri_not_in_the_document_is_refused(self, api_client, auth_headers, network):
        resp = await _authorize(api_client, auth_headers, redirect_uri="http://localhost:9999/elsewhere")
        assert resp.status_code == 400

    async def test_http_client_id_is_refused_without_a_fetch(self, api_client, auth_headers, network):
        resp = await _authorize(api_client, auth_headers, client_id=CIMD_URL.replace("https://", "http://"))
        assert resp.status_code == 400
        assert network.fetches == 0

    @pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "100.64.0.9"])  # noqa: leak-check
    async def test_host_resolving_to_a_non_public_address_is_refused_without_a_fetch(
        self, api_client, auth_headers, network, monkeypatch, address
    ):
        async def lookup(host, port):
            return [address]

        monkeypatch.setattr(oauth_cimd, "_lookup", lookup)
        resp = await _authorize(api_client, auth_headers)
        assert resp.status_code == 400
        assert network.fetches == 0

    async def test_a_slow_document_host_times_out(self, api_client, auth_headers, network, monkeypatch):
        monkeypatch.setattr(oauth_cimd, "CIMD_FETCH_TIMEOUT_SECONDS", 0.3)
        network.delay = 3
        resp = await _authorize(api_client, auth_headers)
        assert resp.status_code == 400

    async def test_the_document_is_fetched_once_while_cached(self, api_client, auth_headers, network):
        for _ in range(3):
            assert (await _authorize(api_client, auth_headers)).status_code == 200
        assert network.fetches == 1

    async def test_token_for_a_client_whose_document_vanished_is_invalid_client(
        self, api_client, auth_headers, network
    ):
        verifier, challenge = _pkce_pair()
        authz = await _authorize(api_client, auth_headers, challenge=challenge)
        code = parse_qs(urlparse(authz.json()["redirect_uri"]).query)["code"][0]

        oauth_cimd.clear_cache()
        network.body = None
        tok = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
                "client_id": CIMD_URL,
            },
        )
        assert tok.status_code == 401, tok.text
        assert tok.json()["error"] == "invalid_client"

    async def test_a_cimd_client_may_not_present_a_secret(self, api_client, auth_headers, network):
        verifier, challenge = _pkce_pair()
        authz = await _authorize(api_client, auth_headers, challenge=challenge)
        code = parse_qs(urlparse(authz.json()["redirect_uri"]).query)["code"][0]
        tok = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
                "client_id": CIMD_URL,
                "client_secret": "guess",
            },
        )
        assert tok.status_code == 401, tok.text
        assert tok.json()["error"] == "invalid_client"

    async def test_a_code_minted_for_one_client_is_not_redeemable_by_a_cimd_url(
        self, api_client, auth_headers, network
    ):
        verifier, challenge = _pkce_pair()
        authz = await _authorize(api_client, auth_headers, client_id=BUILTIN_CLIENT_ID, challenge=challenge)
        code = parse_qs(urlparse(authz.json()["redirect_uri"]).query)["code"][0]
        tok = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT,
                "client_id": CIMD_URL,
            },
        )
        assert tok.status_code == 400, tok.text


@pytest.mark.asyncio
class TestAuthorizationServerMetadata:
    async def test_the_cimd_gates_hosted_clients_check_are_advertised_together(self, api_client):
        from api.endpoints.oauth import register_edition_registration_endpoint

        register_edition_registration_endpoint("/api/oauth/register")
        body = (await api_client.get("/.well-known/oauth-authorization-server")).json()
        assert body["client_id_metadata_document_supported"] is True
        assert "none" in body["token_endpoint_auth_methods_supported"]
        assert body["code_challenge_methods_supported"] == ["S256"]
        assert body["registration_endpoint"].endswith("/api/oauth/register")

    @pytest.mark.parametrize(
        "path",
        ["/api/oauth/.well-known/oauth-authorization-server", "/.well-known/oauth-authorization-server"],
    )
    async def test_cimd_support_is_advertised(self, api_client, path):
        body = (await api_client.get(path)).json()
        assert body["client_id_metadata_document_supported"] is True
