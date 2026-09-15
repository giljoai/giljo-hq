# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, status


class JWTAudienceMismatchError(Exception):
    pass


class JWTManager:

    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS = 24
    REFRESH_GRACE_PERIOD_HOURS = 1

    @classmethod
    def _get_secret_key(cls) -> str:
        secret_key = os.getenv("JWT_SECRET") or os.getenv("GILJO_MCP_SECRET_KEY") or os.getenv("SECRET_KEY")

        if not secret_key:
            raise RuntimeError(
                "JWT secret key not found in environment variables. "
                "Please ensure JWT_SECRET, GILJO_MCP_SECRET_KEY, or SECRET_KEY is set in .env file. "
                "Run 'python install.py' to regenerate configuration if needed."
            )

        return secret_key

    @classmethod
    def get_secret_key(cls) -> str:
        return cls._get_secret_key()

    @classmethod
    def create_access_token(
        cls,
        user_id: UUID,
        username: str,
        role: str,
        tenant_key: str,
        audience: str | None = None,
        scope: str | None = None,
        revocation_epoch: int = 0,
    ) -> str:
        secret_key = cls._get_secret_key()

        expire = datetime.now(UTC) + timedelta(hours=cls.ACCESS_TOKEN_EXPIRE_HOURS)
        payload: dict = {
            "sub": str(user_id),
            "username": username,
            "role": role,
            "tenant_key": tenant_key,
            "exp": expire,
            "iat": datetime.now(UTC),
            "type": "access",
            "jti": uuid4().hex,
            "rev": int(revocation_epoch or 0),
        }
        if audience is not None:
            payload["aud"] = audience
        if scope is not None:
            payload["scope"] = scope
        return jwt.encode(payload, secret_key, algorithm=cls.ALGORITHM)

    @classmethod
    def verify_token(cls, token: str, expected_audience: str | None = None) -> dict:
        try:
            secret_key = cls._get_secret_key()
        except RuntimeError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"JWT configuration error: {e}"
            ) from e

        try:
            payload = jwt.decode(
                token,
                secret_key,
                algorithms=[cls.ALGORITHM],
                options={"verify_aud": False},
            )

            if payload.get("type") != "access":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

            if expected_audience is not None:
                token_aud = payload.get("aud")
                if token_aud is None or token_aud == "":
                    raise JWTAudienceMismatchError(
                        f"JWT missing required 'aud' claim for resource '{expected_audience}' "
                        "(API-0022: legacy aud-less tokens no longer accepted)"
                    )
                if token_aud != expected_audience:
                    raise JWTAudienceMismatchError(
                        f"JWT aud '{token_aud}' does not match expected '{expected_audience}'"
                    )

            return payload

        except jwt.ExpiredSignatureError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired. Please login again."
            ) from e
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials"
            ) from e

    @classmethod
    def verify_token_allow_expired(cls, token: str, grace_hours: int | None = None) -> dict | None:
        grace = grace_hours if grace_hours is not None else cls.REFRESH_GRACE_PERIOD_HOURS
        try:
            secret_key = cls._get_secret_key()
        except RuntimeError:
            return None

        try:
            payload = jwt.decode(token, secret_key, algorithms=[cls.ALGORITHM])
            if payload.get("type") != "access":
                return None
            return payload
        except jwt.ExpiredSignatureError:
            try:
                payload = jwt.decode(
                    token,
                    secret_key,
                    algorithms=[cls.ALGORITHM],
                    options={"verify_exp": False},
                )
                if payload.get("type") != "access":
                    return None
                exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
                now = datetime.now(UTC)
                if (now - exp) <= timedelta(hours=grace):
                    return payload
                return None
            except jwt.InvalidTokenError:
                return None
        except jwt.InvalidTokenError:
            return None
