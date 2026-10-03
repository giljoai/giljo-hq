# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
import logging
import os
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .config_manager import get_config
from .secret_files import claim_or_read_secret_file, is_valid_fernet_key


logger = logging.getLogger(__name__)


SaasApiKeyResolver = Callable[[Request, str], Awaitable[dict[str, Any] | None]]

_saas_api_key_resolver: SaasApiKeyResolver | None = None


def set_saas_api_key_resolver(resolver: SaasApiKeyResolver | None) -> None:
    if resolver is not None and not callable(resolver):
        raise TypeError(f"SaaS API key resolver must be callable or None, got {type(resolver).__name__}")
    global _saas_api_key_resolver  # noqa: PLW0603 — process-wide extension seam
    _saas_api_key_resolver = resolver


def get_saas_api_key_resolver() -> SaasApiKeyResolver | None:
    return _saas_api_key_resolver


class AuthManager:

    def __init__(self, config=None, db: AsyncSession | None = None):
        self.config = config or get_config()
        self.db = db
        self.jwt_secret = self._get_or_create_jwt_secret()
        self.api_keys: dict[str, dict[str, Any]] = {}
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key)

    def _get_or_create_jwt_secret(self) -> str:
        env_secret = os.getenv("JWT_SECRET") or os.getenv("GILJO_MCP_SECRET_KEY")
        if env_secret:
            logger.info("Using JWT secret from environment variable")
            return env_secret

        secret_file = Path.home() / ".giljo-mcp" / "jwt_secret"
        secret = claim_or_read_secret_file(
            secret_file,
            generate=lambda: secrets.token_urlsafe(32).encode(),
            is_valid=lambda data: bool(data.strip()),
            description="JWT signing secret",
        )
        return secret.decode().strip()

    def _get_or_create_encryption_key(self) -> bytes:
        env_key = os.getenv("GILJO_MCP_ENCRYPTION_KEY")
        if env_key:
            key = env_key.encode()
            if not is_valid_fernet_key(key):
                raise ValueError(
                    "GILJO_MCP_ENCRYPTION_KEY is set but is not a valid Fernet key. "
                    "It must be 32 url-safe base64-encoded bytes (a 44-character "
                    "value ending in '='), as produced by: python -c "
                    '"from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())". Unset the variable to '
                    "let Giljo HQ generate and store one instead."
                )
            logger.info("Using encryption key from environment variable")
            return key

        key_file = Path.home() / ".giljo-mcp" / "encryption_key"
        return claim_or_read_secret_file(
            key_file,
            generate=Fernet.generate_key,
            is_valid=is_valid_fernet_key,
            description="API-key encryption key",
        )

    def validate_api_key(self, api_key: str) -> dict[str, Any] | None:
        if not self.api_keys:
            api_keys_file = Path.home() / ".giljo-mcp" / "api_keys.json"
            if api_keys_file.exists():
                try:
                    encrypted_data = api_keys_file.read_bytes()
                    decrypted_data = self.cipher.decrypt(encrypted_data)
                    self.api_keys = json.loads(decrypted_data.decode())
                except (InvalidToken, OSError, json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Could not decrypt API keys (might be unencrypted): {e}")
                    try:
                        self.api_keys = json.loads(api_keys_file.read_text())
                        logger.info("Loaded plaintext API keys - will encrypt on next save")
                    except (OSError, json.JSONDecodeError, ValueError):
                        logger.exception("Could not load API keys from file")
                        self.api_keys = {}

        if api_key in self.api_keys:
            key_info = self.api_keys[api_key]
            if key_info.get("active", True):
                return key_info

        return None

    def validate_jwt_token(self, token: str) -> dict[str, Any] | None:
        try:
            return jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            return None

    async def authenticate_request(self, request: Request) -> dict[str, Any]:
        return await self._validate_network_credentials(request)

    async def _validate_network_credentials(self, request: Request) -> dict[str, Any]:
        token = None
        cookie_header = request.headers.get("cookie", "")
        if cookie_header:
            cookies = {}
            for cookie_str in cookie_header.split(";"):
                cookie_clean = cookie_str.strip()
                if "=" in cookie_clean:
                    key, value = cookie_clean.split("=", 1)
                    cookies[key.strip()] = value.strip()

            token = cookies.get("access_token")
            if token:
                logger.debug("REST API: Found JWT token in httpOnly cookie")

        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if token:
            logger.debug("[Network Auth] Found JWT token (length: %d)", len(token))
            db_manager = getattr(request.app.state, "db_manager", None)
            if db_manager is not None:
                from giljo_mcp.auth.principal import PrincipalValidationError, validate_principal

                try:
                    async with db_manager.get_session_async() as session:
                        principal = await validate_principal(session, jwt_token=token)
                        session.expunge(principal.user)
                    return {
                        "authenticated": True,
                        "user": principal.username,
                        "user_id": principal.username,
                        "tenant_key": principal.tenant_key,
                        "is_auto_login": False,
                        "permissions": ["*"],
                        "exp": principal.exp,
                        "user_obj": principal.user,
                    }
                except PrincipalValidationError as exc:
                    logger.debug("[Network Auth] JWT rejected (%s); trying API-key paths", exc.reason.value)
            else:
                token_info = self.validate_jwt_token(token)
                if token_info and token_info.get("tenant_key"):
                    return {
                        "authenticated": True,
                        "user": token_info.get("username"),
                        "user_id": token_info.get("username"),
                        "tenant_key": token_info.get("tenant_key"),
                        "is_auto_login": False,
                        "permissions": ["*"],
                        "exp": token_info.get("exp"),
                    }

            key_info = self.validate_api_key(token)
            if key_info:
                return await self._build_api_key_result(key_info, request)

        api_key = request.headers.get("X-API-Key")
        if api_key:
            key_info = self.validate_api_key(api_key)
            if key_info:
                return await self._build_api_key_result(key_info, request)

        resolver = _saas_api_key_resolver
        if resolver is not None:
            for candidate in (api_key, token):
                if not candidate:
                    continue
                saas_result = await resolver(request, candidate)
                if saas_result is not None:
                    return saas_result

        logger.warning("[Network Auth] Authentication failed - no valid credentials found")
        return {"authenticated": False, "error": "Authentication required for network access"}

    async def _build_api_key_result(self, key_info: dict[str, Any], request: Request) -> dict[str, Any]:
        from sqlalchemy import select

        from .database import tenant_isolation_bypass
        from .models import User

        result = {
            "authenticated": True,
            "user": key_info["name"],
            "user_id": key_info["name"],
            "tenant_key": key_info.get("tenant_key"),
            "is_auto_login": False,
            "permissions": key_info.get("permissions", ["*"]),
        }

        key_user_id = key_info.get("user_id")
        key_tenant_key = key_info.get("tenant_key")
        db_manager = getattr(request.app.state, "db_manager", None)
        if db_manager and key_user_id and key_tenant_key:
            try:
                async with db_manager.get_session_async() as session:
                    stmt = select(User).where(
                        User.id == key_user_id,
                        User.is_active,
                        User.tenant_key == key_tenant_key,
                    )
                    with tenant_isolation_bypass(
                        session,
                        reason="API key authentication resolves tenant from key identity",
                        models=(User,),
                    ):
                        db_result = await session.execute(stmt)
                    user_obj = db_result.scalar_one_or_none()

                    if user_obj:
                        result["user_obj"] = user_obj
                        result["user"] = user_obj.username
                        result["user_id"] = user_obj.username
                        result["tenant_key"] = user_obj.tenant_key
            except SQLAlchemyError:
                logger.exception("API key user lookup failed: database unavailable")
                raise

        if not result.get("tenant_key"):
            logger.warning("API key authentication rejected: no tenant_key resolved")
            return {"authenticated": False, "error": "Missing tenant key"}

        return result
