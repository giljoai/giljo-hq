# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import base64
import hashlib
import hmac
import inspect
import logging
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

import bcrypt
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp import branding
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import tenant_isolation_bypass, tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthAuthorizationCode
from giljo_mcp.services import oauth_token_idempotency as _idem


logger = logging.getLogger(__name__)


BUILTIN_CLIENT_ID = "giljo-mcp-default"
AUTHORIZATION_CODE_LIFETIME_MINUTES = 10
ACCESS_TOKEN_LIFETIME_SECONDS = 86400
REFRESH_TOKEN_LIFETIME_SECONDS = 30 * 86400
ALLOWED_REDIRECT_URI_PATTERNS = [
    r"^http://localhost(:\d+)?/",
    r"^http://127\.0\.0\.1(:\d+)?/",
    r"^http://\[::1\](:\d+)?/",
]

OAUTH_GRANTABLE_SCOPES: frozenset[str] = frozenset({"mcp:read", "mcp:write", "mcp:agent"})
DEFAULT_OAUTH_SCOPE: str = "mcp:read mcp:write mcp:agent"

MAX_RESOURCE_INDICATOR_LENGTH = 2048




@dataclass(frozen=True)
class ResolvedClient:

    client_id: str
    client_name: str
    redirect_uris: list[str] | None
    client_secret_hash: str | None


ClientResolver = Callable[
    [str, str],
    "ResolvedClient | None | Awaitable[ResolvedClient | None]",
]


def _builtin_single_client_resolver(client_id: str, tenant_key: str) -> ResolvedClient | None:
    _ = tenant_key
    if client_id != BUILTIN_CLIENT_ID:
        return None
    return ResolvedClient(
        client_id=BUILTIN_CLIENT_ID,
        client_name=f"{branding.PRODUCT_NAME} (built-in)",
        redirect_uris=None,
        client_secret_hash=None,
    )


_resolver: ClientResolver = _builtin_single_client_resolver


def set_client_resolver(resolver: ClientResolver) -> None:
    if not callable(resolver):
        raise TypeError(f"ClientResolver must be callable, got {type(resolver).__name__}")
    global _resolver  # noqa: PLW0603 — the seam IS the process-wide state
    _resolver = resolver


def get_client_resolver() -> ClientResolver:
    return _resolver


async def _resolve_client(client_id: str, tenant_key: str) -> ResolvedClient | None:
    resolved = _resolver(client_id, tenant_key)
    return await resolved if inspect.isawaitable(resolved) else resolved


class OAuthService:

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session

    async def validate_authorize_request(
        self,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str,
        response_type: str,
        scope: str,
        *,
        tenant_key: str,
        resource: str | None = None,
    ) -> None:
        if not tenant_key:
            raise ValueError("tenant_key is required for authorize-request validation")
        resolved = await _resolve_client(client_id, tenant_key)
        if resolved is None:
            raise ValueError(f"Invalid client_id: no client registered for '{client_id}'")

        if response_type != "code":
            raise ValueError(f"Invalid response_type: expected 'code', got '{response_type}'")

        if code_challenge_method != "S256":
            raise ValueError(f"Invalid code_challenge_method: expected 'S256', got '{code_challenge_method}'")

        if not code_challenge:
            raise ValueError("code_challenge is required and must be non-empty")

        if not self._redirect_uri_matches(resolved, redirect_uri):
            raise ValueError(f"Invalid redirect_uri: '{redirect_uri}' is not registered for this client")

        self._validate_scope_string(scope)

        if resource is not None:
            self._validate_resource_indicator(resource)

    @staticmethod
    def _validate_resource_indicator(resource: str) -> None:
        if not resource or not isinstance(resource, str):
            raise ValueError("resource must be a non-empty string")
        if len(resource) > MAX_RESOURCE_INDICATOR_LENGTH:
            raise ValueError(f"resource exceeds {MAX_RESOURCE_INDICATOR_LENGTH} characters")
        if "#" in resource:
            raise ValueError("resource must not contain a URI fragment (RFC 8707 §2)")
        parsed = urlsplit(resource)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ValueError("resource must be an absolute https:// or http:// URI")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("resource must not carry userinfo in the authority (RFC 8707 §2)")

    @staticmethod
    def _resolve_bound_resource(
        *,
        client_resource: str | None,
        code_resource: str | None,
    ) -> str | None:
        if code_resource is not None:
            if client_resource is not None and client_resource != code_resource:
                raise ValueError("resource does not match the value bound to the authorization code")
            return code_resource
        if client_resource is not None:
            OAuthService._validate_resource_indicator(client_resource)
            return client_resource
        return None

    @staticmethod
    async def _verify_client_authentication(
        *,
        client_id: str,
        tenant_key: str,
        client_secret: str | None,
    ) -> ResolvedClient:
        resolved = await _resolve_client(client_id, tenant_key)

        if resolved is None:
            raise ValueError("invalid_client: unknown client_id")

        if resolved.client_secret_hash is None:
            if client_secret is not None and client_secret != "":
                raise ValueError("invalid_client: public client must not present a client_secret")
            return resolved

        if not client_secret:
            raise ValueError("invalid_client: client_secret is required for confidential clients")

        try:
            secret_ok = await asyncio.to_thread(
                bcrypt.checkpw, client_secret.encode("utf-8"), resolved.client_secret_hash.encode("ascii")
            )
        except (ValueError, TypeError):
            raise ValueError("invalid_client: client_secret verification failed") from None

        if not secret_ok:
            raise ValueError("invalid_client: client_secret verification failed")

        return resolved

    @staticmethod
    def _redirect_uri_matches(resolved: ResolvedClient, redirect_uri: str) -> bool:
        if resolved.redirect_uris is None:
            return OAuthService.validate_redirect_uri(redirect_uri)
        if not redirect_uri:
            return False
        return redirect_uri in resolved.redirect_uris

    @staticmethod
    def _validate_scope_string(scope: str) -> None:
        if not scope or not scope.strip():
            return
        requested = {token for token in scope.split() if token}
        forbidden = requested - OAUTH_GRANTABLE_SCOPES
        if forbidden:
            raise ValueError(
                f"Scope contains non-grantable token(s): {sorted(forbidden)}. Allowed: {sorted(OAUTH_GRANTABLE_SCOPES)}"
            )

    async def generate_authorization_code(
        self,
        user_id: str,
        tenant_key: str,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        scope: str = DEFAULT_OAUTH_SCOPE,
        resource: str | None = None,
    ) -> str:
        code = secrets.token_urlsafe(64)
        expires_at = datetime.now(UTC) + timedelta(minutes=AUTHORIZATION_CODE_LIFETIME_MINUTES)

        auth_code = OAuthAuthorizationCode(
            code=code,
            client_id=client_id,
            user_id=user_id,
            tenant_key=tenant_key,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method="S256",
            scope=scope,
            resource=resource,
            expires_at=expires_at,
            used=False,
        )

        self._db.add(auth_code)
        await self._db.flush()

        logger.info(
            "Generated authorization code for user_id=%s tenant_key=%s",
            user_id,
            tenant_key,
        )
        return code

    async def exchange_code_for_token(
        self,
        code: str,
        client_id: str,
        code_verifier: str | None,
        redirect_uri: str,
        audience: str | None = None,
        resource: str | None = None,
        client_secret: str | None = None,
        tenant_key_hint: str | None = None,
    ) -> dict:
        from giljo_mcp.services import oauth_refresh_service as _refresh

        with tenant_isolation_bypass(
            self._db,
            reason="oauth /token: resolve authorization code before tenant is known",
            models=(OAuthAuthorizationCode,),
        ):
            result = await self._db.execute(
                select(OAuthAuthorizationCode).where(
                    OAuthAuthorizationCode.code == code,
                    OAuthAuthorizationCode.client_id == client_id,
                )
            )
            auth_code = result.scalar_one_or_none()

        if auth_code is None:
            raise ValueError("Authorization code not found")

        if auth_code.client_id != client_id:
            raise ValueError(f"client_id mismatch: expected '{auth_code.client_id}', got '{client_id}'")

        await self._verify_client_authentication(
            client_id=client_id,
            tenant_key=tenant_key_hint or auth_code.tenant_key,
            client_secret=client_secret,
        )

        idem_proof = code_verifier or ""
        idem_signature = _idem.compute_body_signature(
            client_id=client_id,
            proof=idem_proof or "",
            redirect_uri=redirect_uri,
        )
        cached = await _idem.cache_get(auth_code.tenant_key, code)
        if cached is not None and hmac.compare_digest(cached.body_signature, idem_signature):
            logger.info(
                "oauth_token_idempotency_hit tenant=%s",
                auth_code.tenant_key[:12] if auth_code.tenant_key else "",
            )
            return dict(cached.response_body)

        if auth_code.used:
            await _refresh.revoke_families_for_code(self._db, code=code, tenant_key=auth_code.tenant_key)
            raise ValueError("Authorization code has already been used")

        if auth_code.expires_at < datetime.now(UTC):
            raise ValueError("Authorization code has expired")

        if auth_code.redirect_uri != redirect_uri:
            raise ValueError(f"redirect_uri mismatch: expected '{auth_code.redirect_uri}', got '{redirect_uri}'")

        if code_verifier is None:
            raise ValueError("code_verifier is required (PKCE challenge was presented at authorization)")
        if not self.verify_pkce(code_verifier, auth_code.code_challenge):
            raise ValueError("PKCE verification failed: code_verifier does not match challenge")

        bound_resource = self._resolve_bound_resource(
            client_resource=resource,
            code_resource=auth_code.resource,
        )

        return await self._consume_code_and_issue_pair(
            code=code,
            client_id=client_id,
            auth_code=auth_code,
            token_audience=bound_resource if bound_resource is not None else audience,
            idem_signature=idem_signature,
        )

    async def _consume_code_and_issue_pair(
        self,
        *,
        code: str,
        client_id: str,
        auth_code: OAuthAuthorizationCode,
        token_audience: str | None,
        idem_signature: str,
    ) -> dict:
        from giljo_mcp.services import oauth_refresh_service as _refresh

        with tenant_session_context(self._db, auth_code.tenant_key):
            consumed = await self._db.execute(
                update(OAuthAuthorizationCode)
                .where(
                    OAuthAuthorizationCode.code == code,
                    OAuthAuthorizationCode.tenant_key == auth_code.tenant_key,
                    OAuthAuthorizationCode.used == False,  # noqa: E712 — SQLAlchemy needs ==
                )
                .values(used=True)
            )
            if consumed.rowcount != 1:
                raise ValueError("Authorization code has already been used")

            user_result = await self._db.execute(
                select(User).where(
                    User.id == auth_code.user_id,
                    User.tenant_key == auth_code.tenant_key,
                )
            )
            user = user_result.scalar_one_or_none()

            if user is None:
                raise ValueError("User associated with authorization code not found")

            access_token = JWTManager.create_access_token(
                user_id=UUID(user.id),
                username=user.username,
                role=user.role,
                tenant_key=user.tenant_key,
                audience=token_audience,
                scope=auth_code.scope,
                revocation_epoch=user.token_revocation_epoch or 0,
            )

            logger.info(
                "Exchanged authorization code for token: user_id=%s tenant_key=%s",
                user.id,
                user.tenant_key,
            )

            response: dict = {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": ACCESS_TOKEN_LIFETIME_SECONDS,
            }

            refresh_token = await _refresh.issue_refresh_token(
                self._db,
                family_id=_refresh.new_family_id(),
                client_id=client_id,
                tenant_key=user.tenant_key,
                user_id=user.id,
                scope=auth_code.scope,
                aud=token_audience or "",
                lifetime_seconds=REFRESH_TOKEN_LIFETIME_SECONDS,
                origin_code_hash=_refresh.hash_authorization_code(code),
            )
            response["refresh_token"] = refresh_token
            response["refresh_expires_in"] = REFRESH_TOKEN_LIFETIME_SECONDS

            await _idem.commit_then_cache_pair(
                self._db,
                tenant_key=auth_code.tenant_key,
                code=code,
                response_body=response,
                body_signature=idem_signature,
            )

        return response

    async def refresh_token_grant(
        self,
        *,
        refresh_token: str,
        client_id: str,
        client_secret: str | None,
    ) -> dict:
        from giljo_mcp.services import oauth_refresh_service as _refresh

        return await _refresh.refresh_token_grant(
            self,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            access_token_lifetime_seconds=ACCESS_TOKEN_LIFETIME_SECONDS,
            refresh_token_lifetime_seconds=REFRESH_TOKEN_LIFETIME_SECONDS,
        )

    @staticmethod
    def verify_pkce(code_verifier: str, stored_challenge: str) -> bool:
        import hmac

        if not code_verifier:
            return False

        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(computed_challenge, stored_challenge)

    async def cleanup_expired_codes(self) -> int:
        now = datetime.now(UTC)
        expired_or_used = or_(OAuthAuthorizationCode.expires_at < now, OAuthAuthorizationCode.used == True)  # noqa: E712
        with tenant_isolation_bypass(
            self._db, reason="cross-tenant sweep: purge expired/used oauth codes", models=(OAuthAuthorizationCode,)
        ):
            result = await self._db.execute(delete(OAuthAuthorizationCode).where(expired_or_used))
        await self._db.flush()

        deleted_count = result.rowcount
        if deleted_count > 0:
            logger.info("Cleaned up %d expired/used authorization codes", deleted_count)
        return deleted_count

    @staticmethod
    def validate_redirect_uri(redirect_uri: str) -> bool:
        if not redirect_uri:
            return False

        return any(re.match(pattern, redirect_uri) for pattern in ALLOWED_REDIRECT_URI_PATTERNS)
