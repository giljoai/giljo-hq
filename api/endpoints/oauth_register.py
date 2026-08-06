# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""RFC 7591 OAuth 2.0 Dynamic Client Registration — Community Edition (BE-6235).

``POST /api/oauth/register`` — public, rate-limited.

Why this exists (STEP-0, BE-6235): OAuth-capable MCP harnesses (Claude Code et al.)
have no path to adopt a server-advertised *static* ``client_id``. When a client_id
isn't pre-configured they either use CIMD (needs HTTPS + a hosted metadata doc — a
non-starter for a localhost/self-hosted box) or fall back to Dynamic Client
Registration (RFC 7591). Without a ``registration_endpoint`` a fresh CE server
cannot complete OAuth auto-attach, even though it already ships a built-in public
client (``giljo-mcp-default``). This endpoint closes that gap.

What it does NOT do (deliberately, unlike SaaS DCR in
``api/saas_endpoints/oauth_register.py``): it persists NOTHING and mints NO
per-client id. CE recognizes exactly one OAuth client — the built-in public PKCE
client — so this endpoint always returns it. That client is already resolvable by
the CE ``ClientResolver`` and is bound to the localhost-loopback redirect allowlist
(RFC 8252), so ``/authorize`` + ``/token`` work for the loopback case with zero new
state, no new table, and no migration. A CE served over HTTP on a LAN cannot OAuth
(its non-loopback ``http`` redirect is rejected) — those clients use an API key.

Edition Isolation: CE file. Never imports ``saas/``. Does NOT touch the SaaS-only
``oauth_clients`` table (Table Existence Rule). Client resolution stays GLOBAL by
``client_id`` (OAUTH-MT) — this endpoint adds no tenant scoping.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field, field_validator

from api.middleware.auth_rate_limiter import get_rate_limiter
from api.middleware.auth_rate_limits import limit_for
from giljo_mcp import branding
from giljo_mcp.services.oauth_service import (
    ALLOWED_REDIRECT_URI_PATTERNS,
    BUILTIN_CLIENT_ID,
)
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

router = APIRouter()

# Mirrors the SaaS DCR request caps so agent input is bounded before it reaches us.
MAX_CLIENT_NAME_LENGTH = 255
MAX_REDIRECT_URIS = 5
MAX_REDIRECT_URI_LENGTH = 2048

# CE recognizes only ``authorization_code`` (+ ``refresh_token`` for the rotating
# public-client flow) and the ``code`` response type — same surface the AS metadata
# advertises (oauth.py grant_types_supported / response_types_supported).
_ALLOWED_GRANT_TYPES = frozenset({"authorization_code", "refresh_token"})
_ALLOWED_RESPONSE_TYPES = frozenset({"code"})

# Compiled once. The built-in client validates redirect URIs against these same
# loopback patterns at /authorize (oauth_service.ALLOWED_REDIRECT_URI_PATTERNS), so
# rejecting non-loopback URIs here just fails fast with a clean 422 instead of a
# later 400 at consent.
_LOOPBACK_PATTERNS = [re.compile(pattern) for pattern in ALLOWED_REDIRECT_URI_PATTERNS]


def _is_loopback_redirect(uri: str) -> bool:
    return any(pattern.match(uri) for pattern in _LOOPBACK_PATTERNS)


class CeRegistrationRequest(BaseModel):
    """RFC 7591 §2 registration request (CE subset).

    Fields beyond what CE needs are ignored — agent input is untrusted. Length,
    count, and loopback shape are validated here so the handler never assumes
    sanity.
    """

    client_name: str = Field(default=f"{branding.PRODUCT_NAME} client", min_length=1, max_length=MAX_CLIENT_NAME_LENGTH)
    redirect_uris: list[str] = Field(..., min_length=1, max_length=MAX_REDIRECT_URIS)
    grant_types: list[str] | None = Field(default=None, max_length=8)
    response_types: list[str] | None = Field(default=None, max_length=8)
    token_endpoint_auth_method: str | None = Field(default=None, max_length=64)

    @field_validator("redirect_uris")
    @classmethod
    def _loopback_only(cls, v: list[str]) -> list[str]:
        for uri in v:
            if not isinstance(uri, str) or not uri:
                raise ValueError("redirect_uris must contain non-empty strings")
            if len(uri) > MAX_REDIRECT_URI_LENGTH:
                raise ValueError(f"redirect_uri exceeds {MAX_REDIRECT_URI_LENGTH} characters")
            if not _is_loopback_redirect(uri):
                raise ValueError(
                    "CE OAuth supports loopback redirect URIs only "
                    "(http://localhost, http://127.0.0.1, http://[::1]); "
                    "a server reachable over HTTP on a LAN must use an API key instead"
                )
        return v


class CeRegistrationResponse(BaseModel):
    """RFC 7591 §3.2.1 client information response (public PKCE client).

    No ``client_secret`` field at all: CE only issues the built-in PUBLIC client
    (``token_endpoint_auth_method=none``, PKCE-only), and RFC 7591 §3.2.1 requires
    the secret be ABSENT (not null) when none is issued.
    """

    client_id: str
    client_id_issued_at: int
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: str = "none"


@router.post(
    "/register",
    response_model=CeRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="RFC 7591 Dynamic Client Registration (CE built-in public client)",
    responses={
        422: {"description": "Validation error (e.g. non-loopback redirect_uri)"},
        429: {"description": "Rate limit exceeded"},
    },
    tags=["oauth"],
)
async def register_client(request: Request, body: CeRegistrationRequest):
    """Return the built-in public OAuth client so an OAuth harness can auto-attach.

    Public per RFC 7591 §3 (no initial access token). Rate-limited per IP. Persists
    nothing: CE has one client, the built-in public PKCE client. The requested
    (loopback-validated) redirect URIs are echoed back so the harness proceeds to
    ``/authorize``; everything else is fixed to the built-in client.
    """
    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(request, limit=limit_for("oauth_register"), window=60, raise_on_limit=True)

    # Filter the requested grant/response types to CE's supported subset; fall back
    # to the defaults when the caller omitted them or requested nothing supported
    # (RFC 7591 §3.2.1 filter-don't-reject; the response echoes what we registered).
    grant_types = [g for g in (body.grant_types or []) if g in _ALLOWED_GRANT_TYPES] or [
        "authorization_code",
        "refresh_token",
    ]
    response_types = [r for r in (body.response_types or []) if r in _ALLOWED_RESPONSE_TYPES] or ["code"]

    logger.info(
        "ce_oauth_dcr client_id=%s name=%r redirect_uris=%d",
        BUILTIN_CLIENT_ID,
        sanitize(body.client_name),
        len(body.redirect_uris),
    )

    return CeRegistrationResponse(
        client_id=BUILTIN_CLIENT_ID,
        client_id_issued_at=int(datetime.now(UTC).timestamp()),
        client_name=body.client_name,
        redirect_uris=body.redirect_uris,
        grant_types=grant_types,
        response_types=response_types,
        token_endpoint_auth_method="none",
    )
