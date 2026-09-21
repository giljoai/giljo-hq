# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock

import pytest

from api.middleware.auth import AuthMiddleware


CHALLENGE_PATH = "/.well-known/openai-apps-challenge"
ENV_VAR = "GILJO_OPENAI_APPS_CHALLENGE_TOKEN"


@pytest.mark.asyncio
async def test_unset_token_returns_404(api_client, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    response = await api_client.get(CHALLENGE_PATH)
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_set_token_is_served_verbatim_as_plain_text(api_client, monkeypatch):
    token = "oai-challenge-abc123XYZ"
    monkeypatch.setenv(ENV_VAR, token)
    response = await api_client.get(CHALLENGE_PATH)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == token, "body must be the token and nothing else (no newline)"
    assert response.content == token.encode()


@pytest.mark.asyncio
async def test_whitespace_only_token_returns_404(api_client, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "  \n\t ")
    response = await api_client.get(CHALLENGE_PATH)
    assert response.status_code == 404, response.text


def test_path_is_admitted_by_auth_middleware_public_check():
    middleware = AuthMiddleware(MagicMock())
    assert middleware._is_public_endpoint(CHALLENGE_PATH) is True
    assert middleware._is_public_endpoint("/.well-known/mcp-server-info") is True
