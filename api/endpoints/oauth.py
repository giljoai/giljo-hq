# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
OAuth 2.1 Authorization Code endpoints with PKCE.

Provides REST API for the OAuth 2.1 authorization code flow:
- POST /authorize: Process user consent and generate authorization code
- POST /token: Exchange authorization code for JWT access token
- GET /.well-known/oauth-authorization-server: OAuth server metadata

The authorize endpoint requires authentication (user must be logged in).
The token and metadata endpoints are public (no authentication required).

Handover 0828 Phase 3.
"""

import base64
import binascii
import json
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from api.middleware.auth_rate_limiter import get_rate_limiter
from api.middleware.auth_rate_limits import limit_for
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.http.url_resolver import (
    get_canonical_mcp_resource_uri,
    get_public_base_url,
)
from giljo_mcp.models import User
from giljo_mcp.services.oauth_service import (
    DEFAULT_OAUTH_SCOPE,
    OAUTH_GRANTABLE_SCOPES,
    OAuthService,
)
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()

_EDITION_REGISTRATION_ENDPOINT_PATH: list[str] = []


def register_edition_registration_endpoint(path: str) -> None:
    """Allow private edition modules to advertise their DCR endpoint."""
    normalized = (path or "").strip()
    if normalized:
        _EDITION_REGISTRATION_ENDPOINT_PATH[:] = [normalized]


def _oauth_error(
    error: str,
    *,
    status_code: int,
    description: str | None = None,
    www_authenticate: str | None = None,
) -> JSONResponse:
    """Build an RFC 6749 §5.2 token-endpoint error response.

    BE-6040: the OAuth token/refresh/revoke error surface MUST carry the
    machine-readable error in a top-level ``error`` member (RFC 6749 §5.2,
    referenced by RFC 7009 §3) — spec-strict OAuth clients (claude.ai,
    ChatGPT connector, MCP Inspector) parse ``error`` to drive retry/reauth.
    Raising ``HTTPException(detail=...)`` instead routes through the global
    handler and serialises the code under ``message``/``error_code`` —
    interoperable enough by luck, but not conformant. Returning this response
    directly keeps the envelope correct without disturbing the app-wide
    exception handler.

    ``error_description`` is OPTIONAL (RFC 6749 §5.2) and intentionally kept
    terse — no PKCE/verifier/token internals leak through it.
    """
    content: dict[str, str] = {"error": error}
    if description:
        content["error_description"] = description
    headers = {"WWW-Authenticate": www_authenticate} if www_authenticate else None
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def _detail_description(exc: HTTPException) -> str:
    """Extract a terse ``error_description`` from a body-parse/cap HTTPException.

    The shared parse/cap helpers raise ``HTTPException(detail="invalid_request:
    <reason>")``. Strip the legacy code prefix so it becomes the RFC 6749 §5.2
    ``error_description`` while the top-level ``error`` member carries the code.
    """
    detail = exc.detail if isinstance(exc.detail, str) else "invalid request"
    return detail.split(": ", 1)[1] if ": " in detail else detail


# BE-5088: the root-level well-known discovery documents (RFC 8414 AS-metadata
# mirror, RFC 9728 protected-resource, OIDC 404, mcp-server-info) live in
# api/endpoints/oauth_well_known.py to keep this module under the 800-line
# guardrail. That module imports `oauth_metadata` + `OAuthMetadataResponse` +
# `MCP_SPEC_VERSIONS_SUPPORTED` from here (one-way; no import cycle).


# API-0021h — Declared MCP spec versions, single source of truth.
# Advertised in two places, both reading this constant: the AS-metadata
# `mcp_spec_versions_supported` custom claim (RFC 8414 §2 permits additional
# claims) and the GET /.well-known/mcp-server-info conformance discovery
# endpoint. Test file imports the same symbol so a drift between the constant,
# the advertised list, and the documented set fails CI immediately.
# Conformance verdicts and evidence are tracked in CONFORMANCE.md (see the
# project's drift-tracking process). 2025-11-25 is declared even though CIMD
# (OAuth Client ID Metadata Documents) is unimplemented. This is NOT an
# over-claim: CIMD is a SHOULD, and the spec signals support for it with a
# separate AS-metadata flag, `client_id_metadata_document_supported`, which we
# deliberately do NOT emit — so a spec-aware client falls back to the
# `registration_endpoint` (RFC 7591 DCR) we DO advertise and which is live,
# exactly as the spec prescribes.
# INF-9371: every revision here is proven served by tests/integration/test_inf9371_wire_revisions.py.
MCP_SPEC_VERSIONS_SUPPORTED: list[str] = ["2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"]


def _has_forbidden_log_chars(value: str) -> bool:
    """True if ``value`` holds a char that could inject into a log line (CWE-117).

    Rejects C0 controls + DEL (``< 0x20``, ``0x7F``), C1 controls
    (``0x80-0x9F``), and the Unicode line/paragraph separators
    (``U+2028``/``U+2029``) — all can smuggle a line break or terminal escape
    into a log line. Shared by the two OAuth field guards
    (``AuthorizeRequest._no_control_chars`` and ``_enforce_oauth_field_caps``)
    so they cannot drift apart again (SEC-9227i L2).
    """
    return any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or ord(c) in (0x2028, 0x2029) for c in value)


class AuthorizeRequest(BaseModel):
    """Request body for the OAuth authorize (consent) endpoint."""

    client_id: str = Field(..., max_length=256, description="OAuth client identifier")
    redirect_uri: str = Field(..., max_length=2048, description="URI to redirect after authorization")
    code_challenge: str = Field(..., max_length=512, description="PKCE S256 code challenge")
    code_challenge_method: str = Field(
        default="S256", max_length=16, description="PKCE challenge method (must be S256)"
    )
    scope: str = Field(
        default=DEFAULT_OAUTH_SCOPE,
        max_length=1024,
        description=(
            "Requested OAuth scope. Must be a subset of "
            f"{sorted(OAUTH_GRANTABLE_SCOPES)}. As of BE-6168 the orchestration "
            "scope (`mcp:agent`) IS grantable here so an OAuth client reaches "
            "API-key parity (guarded by the localhost redirect allowlist + consent)."
        ),
    )
    state: str = Field(default="", max_length=512, description="Opaque state value for CSRF protection")
    response_type: str = Field(default="code", max_length=32, description="OAuth response type (must be code)")
    # RFC 8707 — caps the URI length defensively at the route boundary; the
    # service layer re-validates shape (scheme/host/no-fragment) before any DB
    # write. Optional during the API-0021d transition window so older clients
    # that don't yet forward `resource` still complete /authorize.
    resource: str | None = Field(
        default=None,
        max_length=2048,
        description=(
            "RFC 8707 resource indicator. Identifies the target resource "
            "server (typically the canonical MCP URI). When supplied, it is "
            "persisted onto the auth-code record and re-asserted at /token."
        ),
    )

    @field_validator(
        "client_id",
        "redirect_uri",
        "code_challenge",
        "code_challenge_method",
        "scope",
        "state",
        "response_type",
    )
    @classmethod
    def _no_control_chars(cls, v: str) -> str:
        if v and _has_forbidden_log_chars(v):
            raise ValueError("control characters are not permitted")
        return v


class TokenResponse(BaseModel):
    """Response body for the OAuth token endpoint."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400
    refresh_token: str | None = None
    refresh_expires_in: int | None = None


class OAuthMetadataResponse(BaseModel):
    """OAuth 2.1 authorization server metadata (RFC 8414).

    All endpoint URLs are absolute (per RFC 8414 §2). The optional
    ``registration_endpoint`` is advertised only when DCR is available
    (SaaS/demo edition); CE omits the field rather than advertising a
    404 path.
    """

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    response_types_supported: list[str]
    code_challenge_methods_supported: list[str]
    grant_types_supported: list[str]
    # API-0021i: RFC 8414 §3.2 RECOMMENDED. Mirrors the protected-resource
    # document's scopes_supported so AS-metadata-first clients (claude.ai,
    # MCP Inspector) discover grantable scopes without a second probe.
    scopes_supported: list[str] = Field(
        default_factory=list,
        description="OAuth scopes this authorization server grants (RFC 8414 §3.2).",
    )
    # API-0021i: RFC 8414 §3.2. Declares the credential-presentation shapes
    # accepted by /token after API-0021e Phase 1.1+1.2 (2026-05-10).
    token_endpoint_auth_methods_supported: list[str] = Field(
        default_factory=list,
        description="Client auth methods supported by /token (RFC 8414 §3.2).",
    )
    registration_endpoint: str | None = None
    # BE-6040: RFC 8414 §2 + RFC 7009 §5 OPTIONAL — advertise the token
    # revocation endpoint so spec-aware clients discover /revoke from metadata
    # instead of guessing. The endpoint already exists (oauth_revoke.py); this
    # only surfaces it. Always present (CE + SaaS both mount /revoke).
    revocation_endpoint: str | None = None
    # API-0021h: custom claim advertising the MCP protocol versions this server
    # implements. RFC 8414 §2 permits additional metadata claims; spec-aware MCP
    # clients (claude.ai connector, Inspector) read this to negotiate version
    # without a round-trip through `initialize`.
    mcp_spec_versions_supported: list[str] = Field(
        default_factory=list,
        description="MCP protocol versions implemented by this server (API-0021h).",
    )


@router.post("/authorize", tags=["oauth"])
async def authorize(
    request: Request,
    body: AuthorizeRequest,
    current_user: User = Depends(get_current_active_user),
    db=Depends(get_db_session),
):
    """Process OAuth authorization consent and generate an authorization code.

    Requires the user to be authenticated via JWT cookie. Validates the OAuth
    parameters, generates an authorization code bound to the user and PKCE
    challenge, and returns the redirect URI with the code and state.

    Args:
        request: FastAPI request object.
        body: OAuth authorization parameters.
        current_user: Authenticated user from JWT dependency.
        db: Database session.

    Returns:
        JSON with the redirect_uri containing the authorization code and state.

    Raises:
        HTTPException 400: If OAuth parameter validation fails.
    """
    oauth_service = OAuthService(db_session=db)

    try:
        await oauth_service.validate_authorize_request(
            client_id=body.client_id,
            redirect_uri=body.redirect_uri,
            code_challenge=body.code_challenge,
            code_challenge_method=body.code_challenge_method,
            response_type=body.response_type,
            scope=body.scope,
            tenant_key=current_user.tenant_key,
            resource=body.resource,
        )
    except ValueError as exc:
        logger.warning("OAuth authorize validation failed: %s", sanitize(str(exc)))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid authorization request parameters.",
        ) from exc

    code = await oauth_service.generate_authorization_code(
        user_id=str(current_user.id),
        tenant_key=current_user.tenant_key,
        client_id=body.client_id,
        redirect_uri=body.redirect_uri,
        code_challenge=body.code_challenge,
        scope=body.scope,
        resource=body.resource,
    )

    params = {"code": code}
    if body.state:
        params["state"] = body.state

    separator = "&" if "?" in body.redirect_uri else "?"
    redirect_target = f"{body.redirect_uri}{separator}{urlencode(params)}"

    logger.info(
        "Authorization code issued for user_id=%s client_id=%s",
        current_user.id,
        sanitize(body.client_id),
    )

    return {"redirect_uri": redirect_target}


# Field length caps mirror the original FastAPI ``Form(max_length=...)`` on
# /token + /refresh. Replicated here because Phase 1.2 replaces ``Form(...)``
# parameters with manual body parsing — the validation must move with them
# (agent input is untrusted; raise 400, not let the service produce a 500).
_OAUTH_FIELD_MAX_LENGTHS = {
    "client_secret": 512,
    "resource": 2048,
    "code_verifier": 512,
    "refresh_token": 512,
}


async def _parse_oauth_body(request: Request) -> dict:
    """Parse an OAuth /token or /refresh body.

    Accepts ``application/x-www-form-urlencoded`` (RFC 6749 §3.2 canonical)
    or ``application/json`` (de-facto modern client behavior — Google,
    GitHub, Auth0, Okta all accept it; ChatGPT requires it). Defaults to
    form-encoded when the content-type header is missing or unrecognized.

    Raises HTTPException 400 (``invalid_request``) on malformed JSON or a
    JSON body that is not an object.
    """
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_request: malformed JSON body",
            ) from exc
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_request: body must be a JSON object",
            )
        return data

    form = await request.form()
    return dict(form.items())


def _extract_basic_auth(request: Request) -> tuple[str | None, str | None]:
    """Return ``(client_id, client_secret)`` from HTTP Basic Auth, or ``(None, None)``.

    Implements RFC 6749 §2.3.1 (``client_secret_basic``). When the header is
    absent or malformed, both values are ``None`` and the caller falls back
    to body credentials. Empty fields after the colon are treated as
    missing — a Basic header carrying no credentials is no header.
    """
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        return None, None
    try:
        decoded = base64.b64decode(auth[6:].strip(), validate=False).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None, None
    if ":" not in decoded:
        return None, None
    cid, _, csec = decoded.partition(":")
    return (cid or None), (csec or None)


def _enforce_oauth_field_caps(**fields: str | None) -> None:
    """Reject oversized or control-char OAuth body fields with 400 ``invalid_request``.

    Untrusted agent input must produce 422/400, never flow to the service layer
    where a DB constraint would 500. Control chars are rejected to close the
    log-injection surface (SEC-5109, CodeQL #758).
    """
    for name, value in fields.items():
        if value is None:
            continue
        cap = _OAUTH_FIELD_MAX_LENGTHS.get(name)
        if cap is not None and len(value) > cap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"invalid_request: {name} exceeds maximum length {cap}",
            )
        if value and _has_forbidden_log_chars(value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"invalid_request: {name} contains invalid characters",
            )


async def _refresh_token_grant_response(
    data: dict, basic_id: str | None, basic_secret: str | None, db
) -> TokenResponse | JSONResponse:
    """Execute the RFC 6749 §6 ``refresh_token`` grant.

    Shared by ``POST /refresh`` and ``POST /token`` (BE-9409): the metadata
    advertises ``refresh_token`` against ``token_endpoint = /api/oauth/token``,
    so both routes run this ONE body — a second copy of the client-auth and
    validation rules would drift, and here a drift is a security defect.
    Callers own their rate-limit check and body parse and pass the parsed values
    in, so dispatching from /token neither double-consumes the shared per-IP
    rate-limit slot nor re-reads an exhausted body stream. Serves confidential
    and public PKCE clients alike (BE-6161).
    """
    grant_type = data.get("grant_type")
    refresh_token = data.get("refresh_token")
    client_id = basic_id or data.get("client_id")
    client_secret = basic_secret or data.get("client_secret")

    try:
        _enforce_oauth_field_caps(
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
    except HTTPException as exc:
        return _oauth_error(
            "invalid_request",
            status_code=status.HTTP_400_BAD_REQUEST,
            description=_detail_description(exc),
        )

    missing = [
        name
        for name, val in (
            ("grant_type", grant_type),
            ("refresh_token", refresh_token),
            ("client_id", client_id),
        )
        if not val
    ]
    if missing:
        return _oauth_error(
            "invalid_request",
            status_code=status.HTTP_400_BAD_REQUEST,
            description=f"missing required field(s): {', '.join(missing)}",
        )

    if grant_type != "refresh_token":
        return _oauth_error(
            "unsupported_grant_type",
            status_code=status.HTTP_400_BAD_REQUEST,
            description="expected grant_type 'refresh_token'",
        )

    oauth_service = OAuthService(db_session=db)
    try:
        result = await oauth_service.refresh_token_grant(
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("invalid_client"):
            logger.warning("OAuth refresh client authentication failed: %s", sanitize(str(exc)))
            return _oauth_error(
                "invalid_client",
                status_code=status.HTTP_401_UNAUTHORIZED,
                www_authenticate='Basic realm="oauth"',
            )
        if message.startswith("invalid_grant"):
            logger.warning("OAuth refresh invalid_grant: %s", sanitize(str(exc)))
            return _oauth_error(
                "invalid_grant",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        logger.warning("OAuth refresh request invalid: %s", sanitize(str(exc)))
        return _oauth_error(
            "invalid_request",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return TokenResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
        refresh_token=result.get("refresh_token"),
        refresh_expires_in=result.get("refresh_expires_in"),
    )


@router.post("/token", response_model=TokenResponse, response_model_exclude_none=True, tags=["oauth"])
async def token(
    request: Request,
    db=Depends(get_db_session),
):
    """Exchange an authorization code — or a refresh token — for a JWT access token.

    RFC 6749 §6 (BE-9409): serves BOTH advertised grant types —
    ``grant_type=refresh_token`` dispatches to the shared refresh body that
    ``POST /refresh`` also runs; that route stays for back-compat.

    Public endpoint (no authentication required). Accepts THREE request
    shapes (API-0021e Phase 1.2):

    1. ``application/x-www-form-urlencoded`` body — RFC 6749 §3.2 canonical
       (claude.ai uses this).
    2. ``application/json`` body — pragmatic norm matching Google / GitHub /
       Auth0 / Okta. ChatGPT connector uses this (observed in production,
       from an Azure egress range, e.g. 203.0.113.0/24).
    3. HTTP Basic Auth header (``Authorization: Basic
       <b64(client_id:client_secret)>``) for ``client_secret_basic`` clients
       — RFC 6749 §2.3.1. Header credentials take precedence over body
       values when both are supplied.

    The handler logic (validation, PKCE branching, secret verification) is
    identical regardless of input shape; only parsing differs.

    Body fields (form or JSON) — the authorization_code grant:
        grant_type: "authorization_code", or "refresh_token" to run the
            refresh grant (its fields are documented on ``POST /refresh``).
        code: The authorization code from the authorize step.
        client_id: OAuth client identifier (optional if Basic Auth header
            supplies it).
        redirect_uri: Must match the URI used during authorization.
        code_verifier: PKCE code verifier (RFC 7636). REQUIRED for every client
            type — public and confidential alike — and verified against the
            stored S256 challenge (SEC-9227 H2 / RFC 9700 §2.1.1). A
            confidential client's ``client_secret`` authenticates the client but
            does NOT substitute for the verifier.
        resource: RFC 8707 resource indicator. Optional at /token: when
            the auth-code record carries a bound resource, the bound value
            is authoritative — if the client asserts ``resource`` here it
            MUST equal the bound value (mismatch → ``invalid_grant`` 401);
            if the client omits it, the server falls back to the bound
            value per RFC 8707 §2 (SHOULD use the value from /authorize).
            API-0021e Phase 1.4 (ChatGPT compat).
        client_secret: Plaintext client secret for confidential clients
            registered via RFC 7591 DCR. Required when the resolved client
            carries a ``client_secret_hash``; rejected as ``invalid_client``
            (401) when missing or wrong. Public PKCE-only clients (built-in
            CE) MUST omit this field — sending it on a public client is also
            ``invalid_request`` (400). API-0021e Phase 1.

    Returns:
        TokenResponse with access_token, token_type, and expires_in.

    Raises:
        HTTPException 400: ``invalid_request`` (malformed body, missing
            required field, wrong grant_type, PKCE/expiry/code-reuse).
        HTTPException 401: ``invalid_grant`` (resource mismatch) or
            ``invalid_client`` (confidential auth failed).
        HTTPException 429: per-IP rate limit exceeded (SEC-9227d).
    """
    # SEC-9227d (M3): per-IP rate limit, FIRST — before any parsing (reject
    # cheap, parse later). Deliberately OUTSIDE the try blocks below: the 429
    # is NOT an OAuth protocol error and must propagate as-is, never rewritten
    # into the RFC 6749 §5.2 envelope.
    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(request, limit=limit_for("oauth_token"), window=60, raise_on_limit=True)

    # BE-6040: parse + field-cap failures must also use the RFC 6749 §5.2
    # envelope (they raise HTTPException with a string detail otherwise).
    try:
        data = await _parse_oauth_body(request)
        basic_id, basic_secret = _extract_basic_auth(request)
    except HTTPException as exc:
        return _oauth_error(
            "invalid_request",
            status_code=status.HTTP_400_BAD_REQUEST,
            description=_detail_description(exc),
        )

    grant_type = data.get("grant_type")

    # BE-9409: RFC 6749 §6 — the refresh grant belongs to the SAME token
    # endpoint the metadata advertises. Dispatch BEFORE per-grant validation:
    # the missing-field check below is the authorization_code contract, and
    # running it first rejected valid refreshes for lacking `code`.
    if grant_type == "refresh_token":
        return await _refresh_token_grant_response(data, basic_id, basic_secret, db)

    # A present-but-unknown grant_type is unsupported_grant_type. An ABSENT one
    # deliberately falls through to the missing-field check below: RFC 6749
    # §5.2 classes a missing required parameter as invalid_request.
    if grant_type and grant_type != "authorization_code":
        return _oauth_error(
            "unsupported_grant_type",
            status_code=status.HTTP_400_BAD_REQUEST,
            description="expected grant_type 'authorization_code'",
        )

    code = data.get("code")
    code_verifier = data.get("code_verifier")
    redirect_uri = data.get("redirect_uri")
    resource = data.get("resource")
    client_id = basic_id or data.get("client_id")
    client_secret = basic_secret or data.get("client_secret")

    # Field caps stay AHEAD of the missing-field check: an oversized field
    # reports as itself, not as whichever field is also absent.
    try:
        _enforce_oauth_field_caps(
            client_secret=client_secret,
            resource=resource,
            code_verifier=code_verifier,
        )
    except HTTPException as exc:
        return _oauth_error(
            "invalid_request",
            status_code=status.HTTP_400_BAD_REQUEST,
            description=_detail_description(exc),
        )

    missing = [
        name
        for name, val in (
            ("grant_type", grant_type),
            ("code", code),
            ("client_id", client_id),
            ("redirect_uri", redirect_uri),
        )
        if not val
    ]
    if missing:
        return _oauth_error(
            "invalid_request",
            status_code=status.HTTP_400_BAD_REQUEST,
            description=f"missing required field(s): {', '.join(missing)}",
        )

    oauth_service = OAuthService(db_session=db)

    try:
        result = await oauth_service.exchange_code_for_token(
            code=code,
            client_id=client_id,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            audience=get_canonical_mcp_resource_uri(request),
            resource=resource,
            client_secret=client_secret,
            tenant_key_hint=None,
        )
    except ValueError as exc:
        message = str(exc)
        # RFC 6749 §5.2: failed client authentication is invalid_client (401).
        # RFC 8707 §2.2: a resource mismatch at /token is invalid_grant (401).
        # All other validation failures (PKCE, code reuse, expired, missing
        # resource when required) stay invalid_request (400).
        if "invalid_client" in message:
            logger.warning("OAuth token client authentication failed: %s", sanitize(str(exc)))
            # RFC 6749 §5.2: a 401 invalid_client SHOULD carry WWW-Authenticate
            # naming the auth schemes /token accepts (Basic + form/JSON post).
            return _oauth_error(
                "invalid_client",
                status_code=status.HTTP_401_UNAUTHORIZED,
                www_authenticate='Basic realm="oauth"',
            )
        if "resource does not match" in message:
            logger.warning("OAuth token resource mismatch: %s", sanitize(str(exc)))
            return _oauth_error(
                "invalid_grant",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        logger.warning("OAuth token exchange failed: %s", sanitize(str(exc)))
        return _oauth_error(
            "invalid_request",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return TokenResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
        refresh_token=result.get("refresh_token"),
        refresh_expires_in=result.get("refresh_expires_in"),
    )


@router.post("/refresh", response_model=TokenResponse, response_model_exclude_none=True, tags=["oauth"])
async def refresh(
    request: Request,
    db=Depends(get_db_session),
):
    """Exchange a refresh token for a new access+refresh pair (API-0021e Phase 2).

    Public (unauthenticated) endpoint. Serves BOTH confidential clients
    (``client_secret_post`` / ``client_secret_basic``) AND public PKCE clients
    (BE-6161). Public clients present no secret — possession of the one-time-use
    rotating refresh token is the proof-of-possession (RFC 8252 / OAuth 2.1
    §4.3.1); the service rotates the token on every call and revokes the whole
    family on reuse of a consumed token.

    Accepts the same three request shapes as /token (API-0021e Phase 1.2):
    form-encoded body, JSON body, or HTTP Basic Auth header for the client
    credentials.

    Body fields (form or JSON):
        grant_type: Must be ``"refresh_token"`` (RFC 6749 §6).
        refresh_token: Plaintext refresh token from the prior /token or
            /refresh response.
        client_id: Client identifier (DCR-registered) — optional when
            supplied via Basic Auth header.
        client_secret: Confidential client secret (required + verified) —
            optional when supplied via Basic Auth header.

    Returns:
        TokenResponse with new ``access_token`` + rotated ``refresh_token``.
        The previous refresh token is marked revoked; reuse triggers
        family-wide revocation per RFC 6749 §10.4.

    Raises:
        HTTPException 400: ``invalid_request`` (grant_type wrong, missing field).
        HTTPException 401: ``invalid_client`` (auth failed) or
            ``invalid_grant`` (token unknown / revoked / expired).
        HTTPException 429: per-IP rate limit exceeded (SEC-9227d).
    """
    # SEC-9227d (M3): per-IP rate limit, FIRST — before any parsing (reject
    # cheap, parse later). Deliberately OUTSIDE the try blocks below: the 429
    # is NOT an OAuth protocol error and must propagate as-is, never rewritten
    # into the RFC 6749 §5.2 envelope.
    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(request, limit=limit_for("oauth_refresh"), window=60, raise_on_limit=True)

    # BE-6040: parse + field-cap failures must also use the RFC 6749 §5.2
    # envelope (they raise HTTPException with a string detail otherwise).
    try:
        data = await _parse_oauth_body(request)
        basic_id, basic_secret = _extract_basic_auth(request)
    except HTTPException as exc:
        return _oauth_error(
            "invalid_request",
            status_code=status.HTTP_400_BAD_REQUEST,
            description=_detail_description(exc),
        )

    # BE-9409: body shared with /token. Behavior here is unchanged.
    return await _refresh_token_grant_response(data, basic_id, basic_secret, db)


@router.get(
    "/.well-known/oauth-authorization-server",
    response_model=OAuthMetadataResponse,
    response_model_exclude_none=True,  # CE omits registration_endpoint cleanly
    tags=["oauth"],
)
async def oauth_metadata(request: Request):
    """Return OAuth 2.1 authorization server metadata (RFC 8414).

    This is a public endpoint. Returns the server's OAuth configuration
    so clients can discover endpoints and supported features.

    Args:
        request: FastAPI request object (for building issuer URL).

    Returns:
        OAuthMetadataResponse with server metadata.
    """
    base_url = get_public_base_url(request)

    # RFC 8414 §2 — absolute endpoint URLs. Pre-fix returned bare paths
    # ("/oauth/authorize"); some clients (claude.ai) coped via issuer-resolution
    # but others fail or skip optional endpoints when paths aren't absolute.
    authorization_endpoint = f"{base_url}/oauth/authorize"
    token_endpoint = f"{base_url}/api/oauth/token"
    # BE-6040: RFC 7009 revocation endpoint (mounted under /api/oauth).
    revocation_endpoint = f"{base_url}/api/oauth/revoke"

    # RFC 7591 dynamic client registration endpoint. CE omits this field;
    # private edition modules register it at startup when available.
    registration_endpoint: str | None = None
    if _EDITION_REGISTRATION_ENDPOINT_PATH:
        registration_endpoint = f"{base_url}{_EDITION_REGISTRATION_ENDPOINT_PATH[0]}"

    return OAuthMetadataResponse(
        issuer=base_url,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        response_types_supported=["code"],
        code_challenge_methods_supported=["S256"],
        # API-0021e Phase 3 + BE-6161: advertise refresh_token grant for both confidential DCR and public PKCE clients (public = rotating one-time tokens, RFC 8252 / OAuth 2.1 §4.3.1).
        grant_types_supported=["authorization_code", "refresh_token"],
        # API-0021i: same source of truth as the protected-resource document
        # at /.well-known/oauth-protected-resource (RFC 9728).
        scopes_supported=sorted(OAUTH_GRANTABLE_SCOPES),
        # API-0021i: reflects /token's real client-auth surface after
        # API-0021e Phase 1.1+1.2 — JSON/form body, HTTP Basic, and PKCE-only
        # public clients with `none`.
        token_endpoint_auth_methods_supported=[
            "client_secret_post",
            "client_secret_basic",
            "none",
        ],
        registration_endpoint=registration_endpoint,
        revocation_endpoint=revocation_endpoint,
        # API-0021h: copy (not reference) the declared-versions list so any
        # downstream mutation of the response payload cannot poison the
        # module-level constant.
        mcp_spec_versions_supported=list(MCP_SPEC_VERSIONS_SUPPORTED),
    )
