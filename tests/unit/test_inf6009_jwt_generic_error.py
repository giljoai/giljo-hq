# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException


pytestmark = pytest.mark.blocking

GENERIC_DETAIL = "Could not validate credentials"


@pytest.fixture(autouse=True)
def set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-" + "key-for-inf6009")


def _token(secret: str, *, token_type: str = "access", algorithm: str = "HS256") -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "username": "testuser",
        "role": "developer",
        "tenant_key": "test-tenant",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "type": token_type,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def test_invalid_signature_detail_is_generic_no_exception_text():
    from giljo_mcp.auth.jwt_manager import JWTManager

    bad_token = _token("a-different-wrong-secret")
    with pytest.raises(HTTPException) as exc_info:
        JWTManager.verify_token(bad_token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == GENERIC_DETAIL
    detail = str(exc_info.value.detail).lower()
    assert "signature" not in detail
    assert "verification failed" not in detail


def test_malformed_token_detail_is_generic():
    from giljo_mcp.auth.jwt_manager import JWTManager

    with pytest.raises(HTTPException) as exc_info:
        JWTManager.verify_token("not.a.valid.jwt")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == GENERIC_DETAIL
    assert ":" not in str(exc_info.value.detail)
