# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import base64
import hashlib
import logging
import secrets

import pytest

from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID


def _pkce_challenge() -> str:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _consent_body(**overrides) -> dict:
    body = {
        "client_id": BUILTIN_CLIENT_ID,
        "redirect_uri": "http://localhost:3000/callback",
        "code_challenge": _pkce_challenge(),
        "code_challenge_method": "S256",
        "scope": "mcp:agent mcp:read mcp:write",
        "state": "a" * 1500,
        "response_type": "code",
        "resource": "http://localhost:3000/mcp",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_authorize_accepts_1500_char_state(api_client, auth_headers):
    response = await api_client.post(
        "/api/oauth/authorize",
        headers=auth_headers,
        json=_consent_body(),
        follow_redirects=False,
    )
    assert response.status_code in (200, 302), response.text


@pytest.mark.asyncio
async def test_authorize_still_rejects_state_over_4096(api_client, auth_headers):
    response = await api_client.post(
        "/api/oauth/authorize",
        headers=auth_headers,
        json=_consent_body(state="a" * 4097),
        follow_redirects=False,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_authorize_still_rejects_control_chars_in_long_state(api_client, auth_headers):
    response = await api_client.post(
        "/api/oauth/authorize",
        headers=auth_headers,
        json=_consent_body(state="a" * 1000 + "\n" + "b" * 10),
        follow_redirects=False,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_oauth_validation_failure_logs_field_and_constraint(api_client, auth_headers, caplog):
    caplog.set_level(logging.WARNING, logger="api.exception_handlers")
    secret_state = "ZZSECRETSTATE" + "z" * 5000
    response = await api_client.post(
        "/api/oauth/authorize",
        headers=auth_headers,
        json=_consent_body(state=secret_state),
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert response.json()["message"] == "Request validation failed"
    records = [r for r in caplog.records if "OAuth request validation failed" in r.getMessage()]
    assert records, [r.getMessage() for r in caplog.records]
    text = records[0].getMessage()
    assert "state" in text
    assert "string_too_long" in text
    assert "ZZSECRETSTATE" not in text


@pytest.mark.asyncio
async def test_non_oauth_validation_failure_does_not_log_oauth_warning(api_client, auth_headers, caplog):
    caplog.set_level(logging.WARNING, logger="api.exception_handlers")
    response = await api_client.post("/api/v1/tasks/", headers=auth_headers, json={"title": 12345})
    assert response.status_code == 422
    assert not [r for r in caplog.records if "OAuth request validation failed" in r.getMessage()]
