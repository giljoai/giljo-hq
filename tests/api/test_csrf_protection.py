# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import secrets

import pytest


NON_EXEMPT_ENDPOINT = "/api/v1/products/"




def _auth_only_headers(auth_headers: dict) -> dict:
    cookie = auth_headers["Cookie"]
    parts = [p.strip() for p in cookie.split(";")]
    access_only = "; ".join(p for p in parts if p.startswith("access_token="))
    return {"Cookie": access_only}




class TestCSRFBlocksWithoutToken:

    @pytest.mark.asyncio
    async def test_csrf_blocks_post_without_token(self, api_client, auth_headers):
        headers = _auth_only_headers(auth_headers)
        response = await api_client.post(NON_EXEMPT_ENDPOINT, headers=headers, json={})

        assert response.status_code == 403
        assert "CSRF validation failed" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_csrf_blocks_put_without_token(self, api_client, auth_headers):
        headers = _auth_only_headers(auth_headers)
        response = await api_client.put(f"{NON_EXEMPT_ENDPOINT}fake-id", headers=headers, json={})

        assert response.status_code == 403
        assert "CSRF validation failed" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_csrf_blocks_delete_without_token(self, api_client, auth_headers):
        headers = _auth_only_headers(auth_headers)
        response = await api_client.delete(f"{NON_EXEMPT_ENDPOINT}fake-id", headers=headers)

        assert response.status_code == 403
        assert "CSRF validation failed" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_csrf_blocks_patch_without_token(self, api_client, auth_headers):
        headers = _auth_only_headers(auth_headers)
        response = await api_client.patch(f"{NON_EXEMPT_ENDPOINT}fake-id", headers=headers, json={})

        assert response.status_code == 403
        assert "CSRF validation failed" in response.json()["detail"]




class TestCSRFAllowsValidToken:

    @pytest.mark.asyncio
    async def test_csrf_allows_post_with_valid_token(self, api_client, auth_headers):
        response = await api_client.post(NON_EXEMPT_ENDPOINT, headers=auth_headers, json={})

        assert response.status_code != 403




class TestCSRFBlocksMismatchedToken:

    @pytest.mark.asyncio
    async def test_csrf_blocks_mismatched_token(self, api_client, auth_headers):
        mismatched_header_token = secrets.token_urlsafe(32)
        headers = {
            "Cookie": auth_headers["Cookie"],
            "X-CSRF-Token": mismatched_header_token,
        }
        response = await api_client.post(NON_EXEMPT_ENDPOINT, headers=headers, json={})

        assert response.status_code == 403
        assert "CSRF validation failed" in response.json()["detail"]




class TestCSRFAllowsSafeMethods:

    @pytest.mark.asyncio
    async def test_csrf_allows_get_without_token(self, api_client, auth_headers):
        headers = _auth_only_headers(auth_headers)
        response = await api_client.get(NON_EXEMPT_ENDPOINT, headers=headers)

        assert response.status_code != 403




class TestCSRFExemptPaths:

    @pytest.mark.asyncio
    async def test_csrf_exempt_login_endpoint(self, api_client):
        response = await api_client.post(
            "/api/auth/login",
            json={"username": "nonexistent", "password": "wrong"},
        )

        assert response.status_code != 403 or (
            response.status_code == 403 and "CSRF" not in response.json().get("detail", "")
        )

    @pytest.mark.asyncio
    async def test_csrf_exempt_setup_endpoints(self, api_client):
        response = await api_client.post(
            "/api/setup/database/test-connection",
            json={"host": "localhost", "port": 5432},
        )

        assert response.status_code != 403 or (
            response.status_code == 403 and "CSRF" not in response.json().get("detail", "")
        )




class TestCSRFSkipsAPIKey:

    @pytest.mark.asyncio
    async def test_csrf_exempt_api_key_requests(self, api_client):
        headers = {"X-API-Key": "some-api-key-value"}
        response = await api_client.post(NON_EXEMPT_ENDPOINT, headers=headers, json={})

        assert response.status_code != 403 or (
            response.status_code == 403 and "CSRF" not in response.json().get("detail", "")
        )




class TestCSRFCookieBehavior:

    @pytest.mark.asyncio
    async def test_csrf_cookie_set_on_first_visit(self, api_client, auth_headers):
        headers = _auth_only_headers(auth_headers)
        response = await api_client.get(NON_EXEMPT_ENDPOINT, headers=headers)

        set_cookie_headers = response.headers.get_list("set-cookie")
        csrf_cookies = [h for h in set_cookie_headers if "csrf_token=" in h]

        assert len(csrf_cookies) > 0, (
            f"Expected Set-Cookie header with csrf_token but none found. All Set-Cookie headers: {set_cookie_headers}"
        )

    @pytest.mark.asyncio
    async def test_csrf_cookie_not_httponly(self, api_client, auth_headers):
        headers = _auth_only_headers(auth_headers)
        response = await api_client.get(NON_EXEMPT_ENDPOINT, headers=headers)

        set_cookie_headers = response.headers.get_list("set-cookie")
        csrf_cookies = [h for h in set_cookie_headers if "csrf_token=" in h]

        assert len(csrf_cookies) > 0, "No csrf_token Set-Cookie header found"

        for cookie_header in csrf_cookies:
            assert "httponly" not in cookie_header.lower(), (
                f"csrf_token cookie must NOT be httponly (JS needs to read it). Got: {cookie_header}"
            )
