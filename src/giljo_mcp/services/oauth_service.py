# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
OAuthService - OAuth 2.1 Authorization Code flow with PKCE.

Implements the server-side logic for OAuth 2.1 with S256 PKCE:
- Authorization request validation
- Authorization code generation and storage
- Code-to-token exchange with PKCE verification
- Redirect URI validation (localhost-only for CE)
- Expired/used code cleanup

Design Principles:
- Single Responsibility: Only OAuth authorization logic
- Exception-based errors: Raises ValueError on validation failures
- Stateless: Each method operates on the provided DB session
- PKCE-only: No client_secret, S256 challenge method required

API-0021c: client lookup is performed through a pluggable
``ClientResolver`` (Callable). CE ships a built-in single-client resolver
that preserves identical pre-0021c behavior. SaaS replaces it at startup
via ``set_client_resolver()`` to look up clients in the ``oauth_clients``
table populated by RFC 7591 Dynamic Client Registration.

API-0021d: RFC 8707 resource indicator is bound to the auth-code record at
/authorize and re-asserted at /token. The matched value becomes the JWT
``aud`` claim, replacing the canonical-MCP-URI fallback used during the
audience-binding transition window.
"""

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
ACCESS_TOKEN_LIFETIME_SECONDS = 86400  # 24 hours
# Refresh tokens live longer than access tokens but still rotate every call.
# 30 days mirrors the de facto industry default (Auth0 / Okta / Azure AD) for
# long-lived sessions; rotation + family reuse detection is what actually
# bounds the security blast radius, not raw lifetime.
REFRESH_TOKEN_LIFETIME_SECONDS = 30 * 86400
ALLOWED_REDIRECT_URI_PATTERNS = [
    r"^http://localhost(:\d+)?/",
    r"^http://127\.0\.0\.1(:\d+)?/",
    r"^http://\[::1\](:\d+)?/",
]

# OAuth-grantable scopes (API-0021b; BE-6168 widened to include `mcp:agent` so an
# OAuth client — now the default auth — reaches API-key parity). The guard against
# a rogue client is no longer scope-withholding but the LOCALHOST-ONLY redirect
# allowlist below (CE) / DCR exact-match list (SaaS) + consent — do NOT weaken it.
# DEFAULT = full surface; a claim-less cookie JWT still defaults narrow at /mcp.
OAUTH_GRANTABLE_SCOPES: frozenset[str] = frozenset({"mcp:read", "mcp:write", "mcp:agent"})
DEFAULT_OAUTH_SCOPE: str = "mcp:read mcp:write mcp:agent"

# RFC 8707 resource indicator length cap. Mirrors the column width on
# ``oauth_authorization_codes.resource`` so validation never produces a 500
# from a column-overflow path that should have been a clean 400.
MAX_RESOURCE_INDICATOR_LENGTH = 2048


# ---------------------------------------------------------------------------
# Client resolver seam (API-0021c)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedClient:
    """OAuth client metadata returned by a ``ClientResolver``.

    ``redirect_uris`` semantics:
      - ``None`` → the validator falls back to :data:`ALLOWED_REDIRECT_URI_PATTERNS`
        (used by the CE built-in single-client default; preserves localhost
        regex matching for unchanged behavior).
      - ``list[str]`` → exact-match validation against the registered URIs
        (used by SaaS DCR clients per RFC 7591 §2).

    ``client_secret_hash`` is None for PKCE-only public clients (built-in
    case). DCR-registered confidential clients store a bcrypt hash; matching
    plaintext-secret verification at /token is out of scope for API-0021c
    (PKCE remains the proof-of-possession mechanism).
    """

    client_id: str
    client_name: str
    redirect_uris: list[str] | None
    client_secret_hash: str | None


# Resolver contract: positional ``(client_id, tenant_key)``.
# OAUTH-MT: client resolution is GLOBAL by ``client_id`` (a shared app identity,
# not tenant data); ``tenant_key`` is NOT a lookup filter — isolation is at the
# GRANT. See oauth_client.lookup_client + OAUTH_MULTITENANT_CLIENT_RESOLUTION.md.
#
# A resolver may return either ``ResolvedClient | None`` directly (sync) or
# an awaitable yielding the same (async). ``validate_authorize_request`` is
# async and awaits whichever shape the active resolver returns — this lets
# CE keep its sync built-in default while SaaS does a true cache-miss DB
# round-trip via :func:`giljo_mcp.saas.auth.oauth_client.lookup_client`.
ClientResolver = Callable[
    [str, str],
    "ResolvedClient | None | Awaitable[ResolvedClient | None]",
]


def _builtin_single_client_resolver(client_id: str, tenant_key: str) -> ResolvedClient | None:
    """CE default: only the built-in MCP client is recognized.

    The built-in client is global (CE has no multi-tenant DB lookup); the
    ``tenant_key`` argument is part of the ``ClientResolver`` contract but is
    ignored for lookup by BOTH CE and SaaS (OAUTH-MT: resolution is global by
    client_id). Returns ``None`` for any other ``client_id``, producing the
    same ``ValueError("Invalid client_id")`` that the previous hardcoded constant comparison raised.
    """
    _ = tenant_key  # contract-required positional arg; CE built-in is global
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
    """Install a process-wide ``ClientResolver``.

    SaaS bootstrap calls this once at startup with a DB-backed resolver that
    queries the ``oauth_clients`` table and falls back to the built-in
    resolver when no row matches. CE leaves the default in place.
    """
    if not callable(resolver):
        raise TypeError(f"ClientResolver must be callable, got {type(resolver).__name__}")
    global _resolver  # noqa: PLW0603 — the seam IS the process-wide state
    _resolver = resolver


def get_client_resolver() -> ClientResolver:
    """Return the currently active ``ClientResolver``."""
    return _resolver


class OAuthService:
    """OAuth 2.1 Authorization Code flow with PKCE support.

    Manages the full authorization code lifecycle: validation, generation,
    exchange, and cleanup. Supports the pluggable ClientResolver (API-0021c) —
    multi-client DCR and confidential clients, beyond the built-in default.

    Args:
        db_session: SQLAlchemy async session for database operations.
    """

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
        """Validate an OAuth authorization request.

        Checks all parameters against expected values and patterns.
        This is a synchronous validation step before any DB interaction.

        Args:
            client_id: Resolved through the active ``ClientResolver``.
                CE default: only ``BUILTIN_CLIENT_ID``. SaaS: any DCR-registered
                client, resolved GLOBALLY by ``client_id`` (OAUTH-MT), with the
                built-in client as a global fallback.
            redirect_uri: Validated against the resolved client's registered
                URIs (exact match) when ``ResolvedClient.redirect_uris`` is
                a list, or against ``ALLOWED_REDIRECT_URI_PATTERNS`` when
                None (built-in client localhost fallback).
            code_challenge: Base64url-encoded S256 challenge (non-empty).
            code_challenge_method: Must be "S256".
            response_type: Must be "code".
            scope: Requested scope. Must be a subset of OAUTH_GRANTABLE_SCOPES,
                which as of BE-6168 includes `mcp:agent` (OAuth-default parity
                with API keys). Any token outside the set is rejected outright.
            tenant_key: Authenticated user's tenant (router plumbs from
                ``current_user.tenant_key``). Required as a sanity check, and is
                the tenant the GRANT binds to — but NOT the client-lookup filter
                (OAUTH-MT: client resolution is global by ``client_id``).
            resource: Optional RFC 8707 resource indicator. Validated for
                URI shape, length, and absence of fragment. Persisted onto
                the auth-code record by ``generate_authorization_code`` so
                ``exchange_code_for_token`` can re-assert it at /token.

        Raises:
            ValueError: If any parameter fails validation.
        """
        if not tenant_key:
            raise ValueError("tenant_key is required for authorize-request validation")
        resolver_result = _resolver(client_id, tenant_key)
        if inspect.isawaitable(resolver_result):
            resolved = await resolver_result
        else:
            resolved = resolver_result
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
        """Validate an RFC 8707 §2 resource indicator URI.

        Requires an absolute http/https URI with a non-empty authority, no
        userinfo (``user:pass@``), and no fragment. Parsed with ``urllib``
        rather than a scheme prefix check so odd authorities cannot slip
        through (SEC-9227i L3); the canonical MCP resource URI must keep
        validating. http is accepted so localhost dev flows keep working;
        length is capped at :data:`MAX_RESOURCE_INDICATOR_LENGTH` to match the
        ``oauth_authorization_codes.resource`` column.
        """
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
        """Resolve the RFC 8707 resource indicator binding for token issuance.

        Three cases:
          1. Auth-code carries a resource (new flow, post-API-0021d): the
             bound value is authoritative. If the client also asserts
             ``resource`` at /token, it MUST equal the bound value
             (mismatch → invalid_grant per RFC 8707 §2.2). If the client
             omits ``resource`` at /token, RFC 8707 §2 says the server
             SHOULD use the value provided at /authorize — we do. API-0021e
             Phase 1.4: ChatGPT-class clients legitimately rely on this
             fallback; claude.ai-class clients echo the value (still
             verified to match).
          2. Auth-code has no resource (pre-API-0021d in-flight code) but
             the client asserted one: accept the client's value as
             authoritative for binding. Bounded validation (URI shape,
             length, no fragment) still applies — we must not let an
             unvalidated string land in the JWT aud.
          3. Neither side carries a resource (legacy aud-less flow): return
             None and the caller falls back to its ``audience`` argument
             (canonical MCP URI). Transition-window behavior — kept until
             the back-compat at /mcp closes.
        """
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
        """Verify a client's authentication at /token (API-0021e Phase 1).

        Resolves the client through the active ``ClientResolver`` (global by
        ``client_id`` — OAUTH-MT; ``tenant_key`` is not a lookup filter) and
        applies the auth method implied by the resolved record:

          - ``client_secret_hash is not None`` → confidential client
            (DCR ``client_secret_post``). ``client_secret`` MUST be present
            and bcrypt-verify against the stored hash. Mismatch / missing
            secret → ``invalid_client``.
          - ``client_secret_hash is None`` → public client (CE built-in PKCE
            only). ``client_secret`` MUST be absent. Sending a secret on a
            public client is treated as ``invalid_client`` to avoid silently
            accepting credentials the server isn't going to validate.
          - resolver returns ``None`` → unknown client → ``invalid_client``.

        Constant-time secret comparison: ``bcrypt.checkpw`` performs a
        constant-time comparison internally (RFC 6749 §10.2 + bcrypt design).
        We never compare hashes via ``==`` and never re-hash with a different
        salt — bcrypt's checkpw is the only correct verification primitive.

        Returns the resolved client so callers can branch on
        ``client_secret_hash`` (e.g. confidential clients receive a refresh
        token at /token, public clients don't — API-0021e Phase 2).
        """
        resolver_result = _resolver(client_id, tenant_key)
        if inspect.isawaitable(resolver_result):
            resolved = await resolver_result
        else:
            resolved = resolver_result

        if resolved is None:
            raise ValueError("invalid_client: unknown client_id")

        if resolved.client_secret_hash is None:
            # Public PKCE-only client. Must not present a secret.
            if client_secret is not None and client_secret != "":
                raise ValueError("invalid_client: public client must not present a client_secret")
            return resolved

        # Confidential client. Secret required + must verify.
        if not client_secret:
            raise ValueError("invalid_client: client_secret is required for confidential clients")

        try:
            # BE-6068 F1: bcrypt verify off the event loop (~250-400ms CPU); covers /token + /refresh.
            secret_ok = await asyncio.to_thread(
                bcrypt.checkpw, client_secret.encode("utf-8"), resolved.client_secret_hash.encode("ascii")
            )
        except (ValueError, TypeError):
            # Malformed stored hash: treat as auth failure rather than 500.
            raise ValueError("invalid_client: client_secret verification failed") from None

        if not secret_ok:
            raise ValueError("invalid_client: client_secret verification failed")

        return resolved

    @staticmethod
    def _redirect_uri_matches(resolved: ResolvedClient, redirect_uri: str) -> bool:
        """Apply the right redirect_uri policy for the resolved client.

        DCR clients (``redirect_uris`` is a concrete list) require exact match
        per RFC 7591 §3 / §3.2. The built-in single client (``redirect_uris``
        is None) keeps the legacy localhost-pattern behavior for backwards
        compatibility with existing CE OAuth flows.
        """
        if resolved.redirect_uris is None:
            return OAuthService.validate_redirect_uri(redirect_uri)
        if not redirect_uri:
            return False
        return redirect_uri in resolved.redirect_uris

    @staticmethod
    def _validate_scope_string(scope: str) -> None:
        """Reject any scope token outside OAUTH_GRANTABLE_SCOPES.

        Empty / whitespace-only `scope` is treated as the default grant
        (caller's choice — the route layer supplies DEFAULT_OAUTH_SCOPE as the
        Pydantic default). Non-empty values must be a subset of
        OAUTH_GRANTABLE_SCOPES — as of BE-6168 that includes `mcp:agent` (OAuth
        parity with API keys). Any token outside the set still raises.

        Args:
            scope: Space-separated scope string from the OAuth client.

        Raises:
            ValueError: If any token in `scope` is not in OAUTH_GRANTABLE_SCOPES.
        """
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
        """Generate and store a cryptographically random authorization code.

        Creates a single-use authorization code bound to the user, tenant,
        and PKCE challenge. The code expires after AUTHORIZATION_CODE_LIFETIME_MINUTES.

        Args:
            user_id: ID of the authenticated user.
            tenant_key: Tenant key for multi-tenant isolation.
            client_id: Client identifier (must be validated before calling).
            redirect_uri: Redirect URI registered for this request.
            code_challenge: Base64url-encoded S256 PKCE challenge.
            scope: Requested scope (default DEFAULT_OAUTH_SCOPE = "mcp:read mcp:write mcp:agent").
            resource: Optional RFC 8707 resource indicator already validated
                by ``validate_authorize_request``. Persisted onto the
                auth-code record so ``exchange_code_for_token`` can match
                the value re-asserted at /token.

        Returns:
            The generated authorization code string.
        """
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
        """Exchange an authorization code for a JWT access+refresh token pair.

        Authenticates the client (bcrypt secret for confidential clients) and
        REQUIRES + S256-verifies ``code_verifier`` for EVERY client type — a
        client secret never substitutes for PKCE (SEC-9227 H2 / RFC 9700 §2.1.1).
        Then atomically consumes the single-use code and issues the pair. Per-arg
        contract (``resource``/``audience`` RFC 8707 binding, ``client_secret``
        required-iff-hash, server-side ``tenant_key_hint``) is documented at each
        use site below.

        Raises ``ValueError`` on an invalid/expired/used code, PKCE failure,
        ``invalid_client``, or a resource-binding mismatch. Returns a dict with
        access_token, token_type, expires_in, refresh_token, refresh_expires_in.
        """
        from giljo_mcp.services import oauth_refresh_service as _refresh

        # API-0022 (folds API-0024): defense-in-depth. Bind the auth-code
        # lookup itself to the body-supplied client_id so a stolen code
        # presented under a different client never even resolves a row.
        # ``oauth_clients.client_id`` is a UUIDv4 primary key (globally
        # unique), so this is equivalent to binding to tenant_key without
        # a second round-trip. The explicit client_id mismatch guard below
        # stays as the second layer.
        #
        # BE6004C-5: public pre-auth /token -- the auth-code row carries the
        # not-yet-known tenant_key, so resolve it under an audited bypass.
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

        # API-0021e Phase 1: client authentication for confidential clients.
        # Looks up the client through the active resolver under the auth-code's
        # tenant_key (server-side, trustworthy). The presence of a
        # ``client_secret_hash`` on the resolved record IS the auth-method
        # signal: hash present → confidential (secret required), hash absent →
        # public PKCE-only (secret forbidden).
        #
        # API-0021l: client authentication runs BEFORE the used/expired
        # checks so a retry with a wrong client_secret produces a clean
        # 401 invalid_client (RFC 6749 §5.2 semantics) regardless of
        # whether the auth-code has already been consumed by a sibling
        # request inside the idempotency window.
        # Authenticates the client (raises invalid_client on a bad secret). Return
        # value now unused: SEC-9227 made PKCE mandatory for every client type.
        await self._verify_client_authentication(
            client_id=client_id,
            tenant_key=tenant_key_hint or auth_code.tenant_key,
            client_secret=client_secret,
        )

        # API-0021l: idempotency-window cache check. If a sibling request
        # inside the window has the SAME (tenant, code, client_id, proof,
        # redirect_uri) signature, return the previously-issued token pair
        # so concurrent retries from the same client see a consistent 200
        # instead of one 200 + one 400. Mismatched signature falls through
        # to the existing fail-closed path.
        # SEC-9227 (H2): the proof MUST key on the per-request PKCE verifier, not
        # client_secret — this cache hit returns tokens BEFORE the mandatory PKCE check.
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
            # SEC-9227 (M4): a code observed already-consumed at read time is a
            # committed prior use = genuine reuse (RFC 9700 §4.5.3). Revoke every
            # refresh family it minted (committed before we raise), then reject.
            # This is the ONLY reuse-revoke site; the concurrent path never revokes.
            await _refresh.revoke_families_for_code(self._db, code=code, tenant_key=auth_code.tenant_key)
            raise ValueError("Authorization code has already been used")

        if auth_code.expires_at < datetime.now(UTC):
            raise ValueError("Authorization code has expired")

        if auth_code.redirect_uri != redirect_uri:
            raise ValueError(f"redirect_uri mismatch: expected '{auth_code.redirect_uri}', got '{redirect_uri}'")

        # SEC-9227 (H2) / RFC 9700 §2.1.1: when a code_challenge was presented at
        # authorization, the AS MUST verify the code_verifier at token exchange for
        # EVERY client type. Codes minted here always carry an S256 challenge
        # (``code_challenge`` is ``nullable=False``), so the verifier is required
        # unconditionally. This replaced a branch that let a CONFIDENTIAL client
        # omit it — a stolen code plus the client secret then redeemed a token with
        # no proof-of-possession. (RFC 9700 supersedes the old RFC 6749 §6 "MAY omit".)
        if code_verifier is None:
            raise ValueError("code_verifier is required (PKCE challenge was presented at authorization)")
        if not self.verify_pkce(code_verifier, auth_code.code_challenge):
            raise ValueError("PKCE verification failed: code_verifier does not match challenge")

        bound_resource = self._resolve_bound_resource(
            client_resource=resource,
            code_resource=auth_code.resource,
        )

        # BE6004C-5: post-resolution work runs tenant-scoped, not under the bypass.
        with tenant_session_context(self._db, auth_code.tenant_key):
            # SEC-9227 (H1): atomic single-use consume. This one conditional
            # UPDATE (used=false -> true) IS the check-and-set, replacing a
            # non-atomic read-then-assign that let two concurrent exchanges both
            # pass the used check and double-issue. rowcount!=1 => a sibling won.
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
                # Concurrent-loss path — DO NOT revoke here (SEC-9227 M4 / FLAG 1).
                # Any request reaching this point already passed verify_pkce
                # above, so it holds the code_verifier: it is the legitimate
                # multi-egress twin (ChatGPT-class concurrent /token), not a
                # reuse attacker (no verifier -> died at the PKCE check, never
                # got here). The winner's just-issued family is legitimate, and
                # the atomic UPDATE already blocked the double-issue — revoking
                # here would self-DoS honest concurrent double-submits. Genuine
                # reuse (a committed prior use) is caught + revoked at the
                # used==true fast-path above; this loser just fails closed.
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

            # RFC 8707: the matched resource indicator IS the JWT audience. Fall back
            # to the caller-supplied ``audience`` only when no resource is in play on
            # either side (pre-API-0021d in-flight code + legacy caller; transition window).
            token_audience = bound_resource if bound_resource is not None else audience

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

            # API-0021e Phase 2 + BE-6161: issue a refresh token to BOTH
            # confidential AND public PKCE clients. Public clients (no
            # client_secret_hash) get a ROTATING one-time-use token (RFC 8252 /
            # OAuth 2.1 §4.3.1): each /refresh rotates it and reuse of a consumed
            # token revokes the whole family — that, not withholding the token,
            # bounds the blast radius while letting CLI sessions outlive access
            # expiry. Aud is NOT NULL on the row; fall back to "" when no resource.
            persisted_aud = token_audience or ""
            refresh_token = await _refresh.issue_refresh_token(
                self._db,
                family_id=_refresh.new_family_id(),
                client_id=client_id,
                tenant_key=user.tenant_key,
                user_id=user.id,
                scope=auth_code.scope,
                aud=persisted_aud,
                lifetime_seconds=REFRESH_TOKEN_LIFETIME_SECONDS,
                # SEC-9227b (M4): link this family to its originating code so a
                # later reuse of that code can revoke it.
                origin_code_hash=_refresh.hash_authorization_code(code),
            )
            response["refresh_token"] = refresh_token
            response["refresh_expires_in"] = REFRESH_TOKEN_LIFETIME_SECONDS

            # API-0021l + SEC-9227e (M2b): durably commit the issuance, THEN
            # cache the response so a concurrent in-window retry sees the same
            # pair — and never a pair whose rows a rollback erased. The
            # commit-before-cache ordering rationale lives on the helper.
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
        """Exchange a refresh token for a new access+refresh pair (API-0021e Phase 2).

        Thin delegator. Real implementation lives in
        :mod:`giljo_mcp.services.oauth_refresh_service` to keep this file
        under the 800-line guardrail. Kept here so callers retain the
        single ``OAuthService`` API surface.
        """
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
        """Verify a PKCE code_verifier against a stored S256 challenge.

        Computes base64url(SHA256(code_verifier)) and compares it to the
        stored challenge value. Comparison uses constant-time equality
        via hmac.compare_digest for security.

        Args:
            code_verifier: The plaintext verifier from the token request.
            stored_challenge: The base64url-encoded S256 challenge from authorization.

        Returns:
            True if the verifier matches, False otherwise.
        """
        import hmac

        if not code_verifier:
            return False

        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(computed_challenge, stored_challenge)

    async def cleanup_expired_codes(self) -> int:
        """Delete all expired/used authorization codes, across all tenants.

        Cross-tenant sweep with no ambient tenant context (BE-8000i, mirrors
        MCPSessionManager.cleanup_expired_sessions) -- needs the bypass below
        or the fail-closed guard raises TenantIsolationError. Returns the
        number of deleted records.
        """
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
        """Check if a redirect URI matches allowed localhost patterns.

        Args:
            redirect_uri: The URI to validate.

        Returns:
            True if the URI matches any allowed pattern, False otherwise.
        """
        if not redirect_uri:
            return False

        return any(re.match(pattern, redirect_uri) for pattern in ALLOWED_REDIRECT_URI_PATTERNS)
