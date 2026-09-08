# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Authentication Middleware for Giljo HQ
Supports auto-login for localhost and JWT/API key for network clients
"""

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


# SaaS hook: extension point for org-scoped API key resolution (SEC-0018b).
# CE leaves this as None — `_validate_network_credentials` skips the SaaS
# path entirely when no resolver is installed. SaaS bootstrap calls
# `set_saas_api_key_resolver` at startup with a DB-backed resolver via
# `giljo_mcp.saas.auth.org_api_key_resolver.install_saas_api_key_resolver`.
#
# Contract: ``Callable[[Request, str], Awaitable[dict | None]]``. Resolver
# receives the FastAPI Request (for db_manager lookup) and the plaintext
# inbound API key. Returns a dict shaped like the existing JWT/API-key
# result (``authenticated``, ``tenant_key``, ``user_id``, ``permissions``,
# ``user_obj`` optional) on success, or None if the key does not match any
# active org row. CE auth_manager itself never imports from saas/.
SaasApiKeyResolver = Callable[[Request, str], Awaitable[dict[str, Any] | None]]

_saas_api_key_resolver: SaasApiKeyResolver | None = None


def set_saas_api_key_resolver(resolver: SaasApiKeyResolver | None) -> None:
    """Install (or clear) the SaaS org-API-key resolver.

    Idempotent. Passing ``None`` clears the resolver (test helper).
    Raises TypeError if a non-callable, non-None value is supplied.
    """
    if resolver is not None and not callable(resolver):
        raise TypeError(f"SaaS API key resolver must be callable or None, got {type(resolver).__name__}")
    global _saas_api_key_resolver  # noqa: PLW0603 — process-wide extension seam
    _saas_api_key_resolver = resolver


def get_saas_api_key_resolver() -> SaasApiKeyResolver | None:
    """Return the currently installed SaaS API-key resolver (or None for CE)."""
    return _saas_api_key_resolver


class AuthManager:
    """
    Manages authentication with unified logic (production parity).

    All clients (localhost and network) require JWT Bearer token or API key.
    No special treatment for localhost - ensures consistent auth testing.
    """

    def __init__(self, config=None, db: AsyncSession | None = None):
        """
        Initialize authentication manager.

        Args:
            config: Optional configuration object
            db: Optional async database session for auto-login user management
        """
        self.config = config or get_config()
        self.db = db
        self.jwt_secret = self._get_or_create_jwt_secret()
        self.api_keys: dict[str, dict[str, Any]] = {}
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key)

    def _get_or_create_jwt_secret(self) -> str:
        """Get or create JWT secret for token signing"""
        # First check environment variables
        env_secret = os.getenv("JWT_SECRET") or os.getenv("GILJO_MCP_SECRET_KEY")
        if env_secret:
            logger.info("Using JWT secret from environment variable")
            return env_secret

        # Fall back to file-based secret
        secret_file = Path.home() / ".giljo-mcp" / "jwt_secret"
        secret = claim_or_read_secret_file(
            secret_file,
            generate=lambda: secrets.token_urlsafe(32).encode(),
            is_valid=lambda data: bool(data.strip()),
            description="JWT signing secret",
        )
        return secret.decode().strip()

    def _get_or_create_encryption_key(self) -> bytes:
        """Get or create Fernet encryption key for API key storage"""
        # Check environment variable first
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

        # Fall back to file-based key
        key_file = Path.home() / ".giljo-mcp" / "encryption_key"
        return claim_or_read_secret_file(
            key_file,
            generate=Fernet.generate_key,
            is_valid=is_valid_fernet_key,
            description="API-key encryption key",
        )

    def validate_api_key(self, api_key: str) -> dict[str, Any] | None:
        """Validate an API key for LAN mode"""
        # Load API keys from encrypted file if not in memory
        if not self.api_keys:
            api_keys_file = Path.home() / ".giljo-mcp" / "api_keys.json"
            if api_keys_file.exists():
                try:
                    # Decrypt and load keys
                    encrypted_data = api_keys_file.read_bytes()
                    decrypted_data = self.cipher.decrypt(encrypted_data)
                    self.api_keys = json.loads(decrypted_data.decode())
                except (InvalidToken, OSError, json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Could not decrypt API keys (might be unencrypted): {e}")
                    # Try reading as plaintext for migration
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
        """Validate JWT token for WAN mode"""
        try:
            return jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            return None

    async def authenticate_request(self, request: Request) -> dict[str, Any]:
        """
        Authenticate incoming request.

        Unified authentication for all clients (localhost and network):
        - Requires JWT Bearer token or API key for ALL connections
        - No special treatment for localhost (production parity)

        Args:
            request: FastAPI Request object

        Returns:
            dict: Authentication result with keys:
                - authenticated: bool
                - user: str (username)
                - user_id: str (username for consistency)
                - tenant_key: str (tenant key)
                - error: str (if authentication failed)
                - user_obj: User (if authenticated via database)

        Example:
            >>> result = await auth_manager.authenticate_request(request)
            >>> if result["authenticated"]:
            ...     print(f"User: {result['user']}")
        """
        # All clients require credentials (unified auth)
        return await self._validate_network_credentials(request)

    async def _validate_network_credentials(self, request: Request) -> dict[str, Any]:
        """
        Validate JWT token or API key for network clients.

        Priority:
        1. JWT token from httpOnly cookie (access_token)
        2. JWT Bearer token (Authorization: Bearer <token>)
        3. API key (X-API-Key header)
        4. Unauthenticated (return error)

        Args:
            request: FastAPI Request object

        Returns:
            dict: Authentication result with consistent user_id and user_obj
        """
        # Try httpOnly cookie FIRST (PRIMARY AUTH METHOD for web dashboard)
        token = None
        cookie_header = request.headers.get("cookie", "")
        if cookie_header:
            # Parse cookies from Cookie header
            cookies = {}
            for cookie_str in cookie_header.split(";"):
                cookie_clean = cookie_str.strip()
                if "=" in cookie_clean:
                    key, value = cookie_clean.split("=", 1)
                    cookies[key.strip()] = value.strip()

            # Get access_token from cookies
            token = cookies.get("access_token")
            if token:
                logger.debug("REST API: Found JWT token in httpOnly cookie")

        # Try Authorization header if no cookie token found
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]  # Remove "Bearer " prefix

        # Validate JWT token if found
        if token:
            logger.debug("[Network Auth] Found JWT token (length: %d)", len(token))
            db_manager = getattr(request.app.state, "db_manager", None)
            if db_manager is not None:
                # SEC-3004b: route the production JWT path through the single
                # validate_principal pipeline (decode → revocation → is_active),
                # closing the drift where this middleware decoded raw JWTs with
                # NO jti-revocation and NO is_active enforcement. The result-dict
                # shape is preserved exactly: user_id == username (the BE-6022
                # per-user rate limiter buckets off request.state.user_id), exp,
                # user_obj (the BE-6063a stash), tenant_key.
                from giljo_mcp.auth.principal import PrincipalValidationError, validate_principal

                try:
                    async with db_manager.get_session_async() as session:
                        principal = await validate_principal(session, jwt_token=token)
                        # Detach so the loaded column values stay readable after
                        # the session closes (the stash is reused downstream by
                        # get_current_user via merge(load=False)).
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
                    # Not an authorized JWT (invalid / expired / revoked /
                    # inactive / no-tenant). Fall through to the file-based
                    # API-key path — an inbound value may be a legacy file key.
                    logger.debug("[Network Auth] JWT rejected (%s); trying API-key paths", exc.reason.value)
            else:
                # Setup window only: no DB yet means no users and nothing
                # revocable, so validate on claims alone (prior no-DB behavior).
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

            # If JWT validation failed, try as API key (legacy file-based store)
            key_info = self.validate_api_key(token)
            if key_info:
                return await self._build_api_key_result(key_info, request)

        # Try API key (X-API-Key header)
        api_key = request.headers.get("X-API-Key")
        if api_key:
            key_info = self.validate_api_key(api_key)
            if key_info:
                return await self._build_api_key_result(key_info, request)

        # SaaS extension: org-scoped API keys (SEC-0018b). The resolver is
        # None in CE, so this branch is a no-op for CE auth. SaaS installs
        # a DB-backed resolver at startup via install_saas_api_key_resolver.
        # We try BOTH the bearer token (when it failed JWT *and* legacy API-key
        # validation) AND the X-API-Key header — an inbound caller may put the
        # org key in either slot.
        resolver = _saas_api_key_resolver
        if resolver is not None:
            for candidate in (api_key, token):
                if not candidate:
                    continue
                saas_result = await resolver(request, candidate)
                if saas_result is not None:
                    return saas_result

        # No valid credentials
        logger.warning("[Network Auth] Authentication failed - no valid credentials found")
        return {"authenticated": False, "error": "Authentication required for network access"}

    async def _build_api_key_result(self, key_info: dict[str, Any], request: Request) -> dict[str, Any]:
        """
        Build authentication result for API key with user object lookup.

        Args:
            key_info: API key information
            request: FastAPI Request object

        Returns:
            dict: Authentication result with user_obj if available
        """
        from sqlalchemy import select

        from .database import tenant_isolation_bypass
        from .models import User

        result = {
            "authenticated": True,
            "user": key_info["name"],
            "user_id": key_info["name"],
            "tenant_key": key_info.get("tenant_key"),  # Resolved from key or DB lookup below
            "is_auto_login": False,
            "permissions": key_info.get("permissions", ["*"]),
        }

        # Best-effort user-object enrichment. Resolve by the key's stored user_id
        # (and tenant_key) — NOT by matching the key's display label against
        # usernames. The label is free-text and is not a stable identity; a label
        # that happens to equal another user's username would otherwise resolve to
        # the wrong account. Mirrors auth/dependencies.py user resolution.
        # When the key record carries no user_id (e.g. installer-generated keys in
        # the file store), skip enrichment entirely — there is no user to resolve.
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
                        # Authoritative identity from the resolved user, mirroring the
                        # JWT path (which sets both user and user_id to the username).
                        # The initial values are the key's free-text LABEL, which is
                        # not a stable per-user identity; the SaaS per-user rate
                        # limiter (BE-6022) buckets off request.state.user_id, so it
                        # must be the username, not an arbitrary label.
                        result["user"] = user_obj.username
                        result["user_id"] = user_obj.username
                        result["tenant_key"] = user_obj.tenant_key
            except SQLAlchemyError as e:
                logger.debug(f"No user object found for API key: {e}")

        # Reject if tenant_key is still None after DB lookup attempt
        if not result.get("tenant_key"):
            logger.warning("API key authentication rejected: no tenant_key resolved")
            return {"authenticated": False, "error": "Missing tenant key"}

        return result
