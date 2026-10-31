# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest


def _cookie_only(auth_headers: dict) -> dict:
    parts = [p.strip() for p in auth_headers["Cookie"].split(";")]
    return {"Cookie": "; ".join(p for p in parts if p.startswith("access_token="))}


def _is_csrf_403(response) -> bool:
    return response.status_code == 403 and "CSRF" in response.json().get("detail", "")


PROTECTED = [
    ("DELETE", "/api/auth/connected-apps"),
    ("DELETE", "/api/auth/connected-apps/some-login-id"),
    ("POST", "/api/auth/api-keys"),
    ("DELETE", "/api/auth/api-keys/some-key-id"),
    ("PATCH", "/api/auth/me/setup-state"),
    ("POST", "/api/auth/complete-first-login"),
]

EXEMPT = [
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/create-first-admin"),
    ("POST", "/api/auth/check-first-login"),
    ("POST", "/api/auth/verify-pin"),
    ("POST", "/api/auth/verify-pin-and-reset-password"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_signed_in_auth_action_rejected_without_csrf_header(api_client, auth_headers, method, path):
    response = await api_client.request(method, path, headers=_cookie_only(auth_headers), json={})
    assert _is_csrf_403(response), (response.status_code, response.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_signed_in_auth_action_rejected_on_token_mismatch(api_client, auth_headers, method, path):
    headers = dict(auth_headers)
    headers["X-CSRF-Token"] = "not-the-cookie-value"
    response = await api_client.request(method, path, headers=headers, json={})
    assert _is_csrf_403(response), (response.status_code, response.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_signed_in_auth_action_passes_csrf_with_matching_header(api_client, auth_headers, method, path):
    response = await api_client.request(method, path, headers=auth_headers, json={})
    assert not _is_csrf_403(response), (response.status_code, response.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), EXEMPT)
async def test_pre_session_auth_endpoints_stay_exempt(api_client, method, path):
    response = await api_client.request(method, path, json={})
    assert not _is_csrf_403(response), (response.status_code, response.text)


@pytest.mark.asyncio
async def test_api_key_header_requests_still_skip_csrf(api_client):
    response = await api_client.delete("/api/auth/connected-apps", headers={"X-API-Key": "gk_bogus"})
    assert not _is_csrf_403(response), (response.status_code, response.text)
