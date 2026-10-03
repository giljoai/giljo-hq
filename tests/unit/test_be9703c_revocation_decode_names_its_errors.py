# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from giljo_mcp.auth.jwt_manager import JWTAudienceMismatchError, JWTManager
from giljo_mcp.services import oauth_revocation_service


def _decode_raises(monkeypatch, exc: Exception) -> None:
    def _verify(token, *args, **kwargs):
        raise exc

    monkeypatch.setattr(JWTManager, "verify_token", staticmethod(_verify))


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [HTTPException(status_code=401, detail="bad"), JWTAudienceMismatchError("aud")])
async def test_an_invalid_token_is_not_revoked_here(monkeypatch, exc):
    _decode_raises(monkeypatch, exc)
    assert await oauth_revocation_service._revoke_access_jwt(AsyncMock(), token="t") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [HTTPException(status_code=500, detail="JWT configuration error"), TypeError("bug")])
async def test_a_server_fault_is_not_reported_as_an_invalid_token(monkeypatch, exc):
    _decode_raises(monkeypatch, exc)
    with pytest.raises(type(exc)):
        await oauth_revocation_service._revoke_access_jwt(AsyncMock(), token="t")
