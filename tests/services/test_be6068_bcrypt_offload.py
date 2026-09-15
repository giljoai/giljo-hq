# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import contextlib

import bcrypt
import pytest

from giljo_mcp.schemas.service_responses import AuthResult


pytestmark = pytest.mark.asyncio


async def test_authenticate_user_offloads_bcrypt_after_session_close(
    monkeypatch, auth_service, auth_user_with_password
):
    user, password = auth_user_with_password

    events: list[str] = []

    original_get_session = auth_service._get_session

    def _recording_get_session(tenant_key: str | None = None):
        @contextlib.asynccontextmanager
        async def _wrap():
            async with original_get_session(tenant_key) as session:
                yield session
            events.append("session_closed")

        return _wrap()

    monkeypatch.setattr(auth_service, "_get_session", _recording_get_session)

    real_to_thread = asyncio.to_thread

    async def _spy(fn, *args, **kwargs):
        if fn is bcrypt.checkpw:
            events.append("bcrypt_offload")
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _spy)

    result = await auth_service.authenticate_user(user.username, password)

    assert isinstance(result, AuthResult)
    assert result.user_id == user.id

    assert "bcrypt_offload" in events, "bcrypt.checkpw was not offloaded via asyncio.to_thread"
    assert events.index("session_closed") < events.index("bcrypt_offload"), (
        "bcrypt verify ran while the DB session was still open"
    )


async def test_authenticate_user_invalid_password_still_offloads(monkeypatch, auth_service, auth_user_with_password):
    from giljo_mcp.exceptions import AuthenticationError

    user, _ = auth_user_with_password

    offloaded: list[bool] = []
    real_to_thread = asyncio.to_thread

    async def _spy(fn, *args, **kwargs):
        if fn is bcrypt.checkpw:
            offloaded.append(True)
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _spy)

    with pytest.raises(AuthenticationError):
        await auth_service.authenticate_user(user.username, "WrongPassword123!")

    assert offloaded, "bcrypt.checkpw was not offloaded on the invalid-password path"


async def test_oauth_client_secret_verify_offloads_bcrypt(monkeypatch):
    from giljo_mcp.services.oauth_service import (
        OAuthService,
        ResolvedClient,
        get_client_resolver,
        set_client_resolver,
    )

    secret = "confidential-secret-value"
    secret_hash = bcrypt.hashpw(secret.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    client = ResolvedClient(
        client_id="test-client",
        client_name="Test Client",
        redirect_uris=["https://example.com/cb"],
        client_secret_hash=secret_hash,
    )

    saved_resolver = get_client_resolver()
    set_client_resolver(lambda client_id, tenant_key: client)
    try:
        offloaded: list[bool] = []
        real_to_thread = asyncio.to_thread

        async def _spy(fn, *args, **kwargs):
            if fn is bcrypt.checkpw:
                offloaded.append(True)
            return await real_to_thread(fn, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", _spy)

        resolved = await OAuthService._verify_client_authentication(
            client_id="test-client",
            tenant_key="test-tenant",
            client_secret=secret,
        )

        assert resolved is client
        assert offloaded, "bcrypt.checkpw was not offloaded via asyncio.to_thread"
    finally:
        set_client_resolver(saved_resolver)
