# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import base64
import hashlib
import secrets

import pytest

from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID


def _pkce_challenge(length: int = 43) -> str:
    if length == 43:
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    raw = secrets.token_urlsafe(length * 2)
    return raw[:length]


def _consent_body(**overrides) -> dict:
    body = {
        "client_id": BUILTIN_CLIENT_ID,
        "redirect_uri": "http://localhost:3000/callback",
        "code_challenge": _pkce_challenge(),
        "code_challenge_method": "S256",
        "scope": "mcp:agent mcp:read mcp:write",
        "state": "teststate123",
        "response_type": "code",
        "resource": "http://localhost:3000/mcp",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_authorize_accepts_a_real_43_char_challenge(api_client, auth_headers):
    response = await api_client.post(
        "/api/oauth/authorize",
        headers=auth_headers,
        json=_consent_body(code_challenge=_pkce_challenge(43)),
        follow_redirects=False,
    )
    assert response.status_code in (200, 302), response.text


@pytest.mark.asyncio
async def test_authorize_rejects_oversize_challenge_with_422_not_500(api_client, auth_headers):
    response = await api_client.post(
        "/api/oauth/authorize",
        headers=auth_headers,
        json=_consent_body(code_challenge=_pkce_challenge(200)),
        follow_redirects=False,
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_authorize_still_rejects_challenge_over_128(api_client, auth_headers):
    response = await api_client.post(
        "/api/oauth/authorize",
        headers=auth_headers,
        json=_consent_body(code_challenge=_pkce_challenge(129)),
        follow_redirects=False,
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_authorize_accepts_challenge_at_the_128_boundary(api_client, auth_headers):
    response = await api_client.post(
        "/api/oauth/authorize",
        headers=auth_headers,
        json=_consent_body(code_challenge=_pkce_challenge(128)),
        follow_redirects=False,
    )
    assert response.status_code in (200, 302), response.text
