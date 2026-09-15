# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest


pytestmark = pytest.mark.blocking


@pytest.fixture(autouse=True)
def set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-unit-tests")


@pytest.fixture
def sample_user_id():
    return uuid4()


@pytest.fixture
def secret_key():
    return "test-secret-key-for-unit-tests"


def _make_token(
    secret_key: str,
    user_id,
    expire_delta: timedelta | None = None,
    token_type: str = "access",
    algorithm: str = "HS256",
) -> str:
    now = datetime.now(UTC)
    expire = now + (expire_delta if expire_delta is not None else timedelta(hours=24))
    payload = {
        "sub": str(user_id),
        "username": "testuser",
        "role": "developer",
        "tenant_key": "test-tenant",
        "exp": expire,
        "iat": now,
        "type": token_type,
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


class TestVerifyTokenAllowExpired:

    def test_valid_non_expired_token_returns_payload(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, expire_delta=timedelta(hours=1))
        result = JWTManager.verify_token_allow_expired(token)

        assert result is not None
        assert result["sub"] == str(sample_user_id)
        assert result["username"] == "testuser"
        assert result["role"] == "developer"
        assert result["tenant_key"] == "test-tenant"
        assert result["type"] == "access"

    def test_expired_within_grace_period_returns_payload(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, expire_delta=timedelta(minutes=-30))
        result = JWTManager.verify_token_allow_expired(token)

        assert result is not None
        assert result["sub"] == str(sample_user_id)
        assert result["type"] == "access"

    def test_expired_beyond_grace_period_returns_none(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, expire_delta=timedelta(hours=-2))
        result = JWTManager.verify_token_allow_expired(token)

        assert result is None

    def test_expired_exactly_at_grace_boundary_returns_payload(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, expire_delta=timedelta(minutes=-59, seconds=-50))
        result = JWTManager.verify_token_allow_expired(token)

        assert result is not None

    def test_expired_just_beyond_grace_boundary_returns_none(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, expire_delta=timedelta(minutes=-61))
        result = JWTManager.verify_token_allow_expired(token)

        assert result is None

    def test_non_access_token_type_returns_none(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, token_type="refresh")
        result = JWTManager.verify_token_allow_expired(token)

        assert result is None

    def test_expired_non_access_token_type_returns_none(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(
            secret_key,
            sample_user_id,
            expire_delta=timedelta(minutes=-30),
            token_type="refresh",
        )
        result = JWTManager.verify_token_allow_expired(token)

        assert result is None

    def test_missing_type_claim_returns_none(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        now = datetime.now(UTC)
        payload = {
            "sub": str(sample_user_id),
            "username": "testuser",
            "role": "developer",
            "tenant_key": "test-tenant",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256")

        result = JWTManager.verify_token_allow_expired(token)

        assert result is None

    def test_tampered_token_returns_none(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token("wrong-secret-key", sample_user_id, expire_delta=timedelta(hours=1))
        result = JWTManager.verify_token_allow_expired(token)

        assert result is None

    def test_malformed_token_returns_none(self):
        from giljo_mcp.auth.jwt_manager import JWTManager

        result = JWTManager.verify_token_allow_expired("not.a.valid.jwt")
        assert result is None

    def test_empty_token_returns_none(self):
        from giljo_mcp.auth.jwt_manager import JWTManager

        result = JWTManager.verify_token_allow_expired("")
        assert result is None

    def test_missing_secret_key_returns_none(self, sample_user_id, monkeypatch):
        from giljo_mcp.auth.jwt_manager import JWTManager

        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.delenv("GILJO_MCP_SECRET_KEY", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)

        token = _make_token("any-key", sample_user_id, expire_delta=timedelta(hours=1))
        result = JWTManager.verify_token_allow_expired(token)

        assert result is None

    def test_custom_grace_hours_override(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, expire_delta=timedelta(hours=-3))

        assert JWTManager.verify_token_allow_expired(token) is None

        result = JWTManager.verify_token_allow_expired(token, grace_hours=4)
        assert result is not None
        assert result["sub"] == str(sample_user_id)

    def test_zero_grace_hours_rejects_all_expired(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, expire_delta=timedelta(seconds=-1))
        result = JWTManager.verify_token_allow_expired(token, grace_hours=0)

        assert result is None

    def test_class_attribute_exists(self):
        from giljo_mcp.auth.jwt_manager import JWTManager

        assert hasattr(JWTManager, "REFRESH_GRACE_PERIOD_HOURS")
        assert JWTManager.REFRESH_GRACE_PERIOD_HOURS == 1

    def test_returns_dict_type(self, sample_user_id, secret_key):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, expire_delta=timedelta(hours=1))
        result = JWTManager.verify_token_allow_expired(token)

        assert isinstance(result, dict)

    def test_does_not_raise_http_exception(self, sample_user_id, secret_key):
        from fastapi import HTTPException

        from giljo_mcp.auth.jwt_manager import JWTManager

        token = _make_token(secret_key, sample_user_id, expire_delta=timedelta(hours=-5))
        try:
            result = JWTManager.verify_token_allow_expired(token)
            assert result is None
        except HTTPException:
            pytest.fail("verify_token_allow_expired should not raise HTTPException")

    def test_token_created_by_create_access_token(self, sample_user_id):
        from giljo_mcp.auth.jwt_manager import JWTManager

        token = JWTManager.create_access_token(
            user_id=sample_user_id,
            username="testuser",
            role="developer",
            tenant_key="test-tenant",
        )
        result = JWTManager.verify_token_allow_expired(token)

        assert result is not None
        assert result["sub"] == str(sample_user_id)
        assert result["username"] == "testuser"
