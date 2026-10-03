# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    content: dict[str, str] = {"error": error}
    if description:
        content["error_description"] = description
    headers = {"WWW-Authenticate": www_authenticate} if www_authenticate else None
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def _detail_description(exc: HTTPException) -> str:
    detail = exc.detail if isinstance(exc.detail, str) else "invalid request"
    return detail.split(": ", 1)[1] if ": " in detail else detail




MCP_SPEC_VERSIONS_SUPPORTED: list[str] = ["2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"]


def _has_forbidden_log_chars(value: str) -> bool:
    return any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or ord(c) in (0x2028, 0x2029) for c in value)


class AuthorizeRequest(BaseModel):
    """Request body for the OAuth authorize (consent) endpoint."""

    client_id: str = Field(..., max_length=256, description="OAuth client identifier")
    redirect_uri: str = Field(..., max_length=2048, description="URI to redirect after authorization")
    code_challenge: str = Field(..., max_length=128, description="PKCE S256 code challenge")
    code_challenge_method: str = Field(
        default="S256", max_length=16, description="PKCE challenge method (must be S256)"
    )
    scope: str = Field(
        default=DEFAULT_OAUTH_SCOPE,
        max_length=1024,
        description=(
            "Requested OAuth scope. Must be a subset of "
            f"{sorted(OAUTH_GRANTABLE_SCOPES)}. The orchestration "
            "scope (`mcp:agent`) IS grantable here so an OAuth client reaches "
            "API-key parity (guarded by the localhost redirect allowlist + consent)."
        ),
    )
    state: str = Field(default="", max_length=4096, description="Opaque state value for CSRF protection")
    response_type: str = Field(default="code", max_length=32, description="OAuth response type (must be code)")
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
    scopes_supported: list[str] = Field(
        default_factory=list,
        description="OAuth scopes this authorization server grants (RFC 8414 §3.2).",
    )
    token_endpoint_auth_methods_supported: list[str] = Field(
        default_factory=list,
        description="Client auth methods supported by /token (RFC 8414 §3.2).",
    )
    registration_endpoint: str | None = None
    revocation_endpoint: str | None = None
    mcp_spec_versions_supported: list[str] = Field(
        default_factory=list,
        description="MCP protocol versions implemented by this server.",
    )


async def validate_consent_request(oauth_service: OAuthService, body: AuthorizeRequest, tenant_key: str) -> None:
    try:
        await oauth_service.validate_authorize_request(tenant_key=tenant_key, **body.model_dump(exclude={"state"}))
    except ValueError as exc:
        logger.warning("OAuth authorize validation failed: %s", sanitize(str(exc)))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid authorization request parameters.",
        ) from exc


def append_query_params(redirect_uri: str, params: dict[str, str]) -> str:
    separator = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{separator}{urlencode(params)}"


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
    await validate_consent_request(oauth_service, body, current_user.tenant_key)

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

    redirect_target = append_query_params(body.redirect_uri, params)

    logger.info(
        "Authorization code issued for user_id=%s client_id=%s",
        current_user.id,
        sanitize(body.client_id),
    )

    return {"redirect_uri": redirect_target}


_OAUTH_FIELD_MAX_LENGTHS = {
    "code": 512,
    "client_id": 256,
    "redirect_uri": 2048,
    "client_secret": 512,
    "resource": 2048,
    "code_verifier": 512,
    "refresh_token": 512,
}


async def _parse_oauth_body(request: Request) -> dict:
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
    for name, value in fields.items():
        if value is None:
            continue
        if not isinstance(value, str):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid_request: {name} must be a string")
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
    grant_type = data.get("grant_type")
    refresh_token = data.get("refresh_token")
    client_id = basic_id or data.get("client_id")
    client_secret = basic_secret or data.get("client_secret")

    try:
        _enforce_oauth_field_caps(
            client_id=client_id,
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

    RFC 6749 §6: serves BOTH advertised grant types —
    ``grant_type=refresh_token`` dispatches to the shared refresh body that
    ``POST /refresh`` also runs; that route stays for back-compat.

    Public endpoint (no authentication required). Accepts THREE request
    shapes:

    1. ``application/x-www-form-urlencoded`` body — RFC 6749 §3.2 canonical
       (claude.ai uses this).
    2. ``application/json`` body — pragmatic norm matching Google / GitHub /
       Auth0 / Okta. The ChatGPT connector uses this.
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
            stored S256 challenge (RFC 9700 §2.1.1). A
            confidential client's ``client_secret`` authenticates the client but
            does NOT substitute for the verifier.
        resource: RFC 8707 resource indicator. Optional at /token: when
            the auth-code record carries a bound resource, the bound value
            is authoritative — if the client asserts ``resource`` here it
            MUST equal the bound value (mismatch → ``invalid_grant`` 401);
            if the client omits it, the server falls back to the bound
            value per RFC 8707 §2 (SHOULD use the value from /authorize).
        client_secret: Plaintext client secret for confidential clients
            registered via RFC 7591 DCR. Required when the resolved client
            carries a ``client_secret_hash``; rejected as ``invalid_client``
            (401) when missing or wrong. Public PKCE-only clients (built-in
            CE) MUST omit this field — sending it on a public client is also
            ``invalid_request`` (400).

    Returns:
        TokenResponse with access_token, token_type, and expires_in.

    Raises:
        HTTPException 400: ``invalid_request`` (malformed body, missing
            required field, wrong grant_type, PKCE/expiry/code-reuse).
        HTTPException 401: ``invalid_grant`` (resource mismatch) or
            ``invalid_client`` (confidential auth failed).
        HTTPException 429: per-IP rate limit exceeded.
    """
    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(request, limit=limit_for("oauth_token"), window=60, raise_on_limit=True)

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

    if grant_type == "refresh_token":
        return await _refresh_token_grant_response(data, basic_id, basic_secret, db)

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

    try:
        _enforce_oauth_field_caps(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
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
        if "invalid_client" in message:
            logger.warning("OAuth token client authentication failed: %s", sanitize(str(exc)))
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
    """Exchange a refresh token for a new access+refresh pair.

    Public (unauthenticated) endpoint. Serves BOTH confidential clients
    (``client_secret_post`` / ``client_secret_basic``) AND public PKCE clients.
    Public clients present no secret — possession of the one-time-use
    rotating refresh token is the proof-of-possession (RFC 8252 / OAuth 2.1
    §4.3.1); the service rotates the token on every call and revokes the whole
    family on reuse of a consumed token.

    Accepts the same three request shapes as /token:
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
        HTTPException 429: per-IP rate limit exceeded.
    """
    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(request, limit=limit_for("oauth_refresh"), window=60, raise_on_limit=True)

    try:
        data = await _parse_oauth_body(request)
        basic_id, basic_secret = _extract_basic_auth(request)
    except HTTPException as exc:
        return _oauth_error(
            "invalid_request",
            status_code=status.HTTP_400_BAD_REQUEST,
            description=_detail_description(exc),
        )

    return await _refresh_token_grant_response(data, basic_id, basic_secret, db)


@router.get(
    "/.well-known/oauth-authorization-server",
    response_model=OAuthMetadataResponse,
    response_model_exclude_none=True,
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

    authorization_endpoint = f"{base_url}/oauth/authorize"
    token_endpoint = f"{base_url}/api/oauth/token"
    revocation_endpoint = f"{base_url}/api/oauth/revoke"

    registration_endpoint: str | None = None
    if _EDITION_REGISTRATION_ENDPOINT_PATH:
        registration_endpoint = f"{base_url}{_EDITION_REGISTRATION_ENDPOINT_PATH[0]}"

    return OAuthMetadataResponse(
        issuer=base_url,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        response_types_supported=["code"],
        code_challenge_methods_supported=["S256"],
        grant_types_supported=["authorization_code", "refresh_token"],
        scopes_supported=sorted(OAUTH_GRANTABLE_SCOPES),
        token_endpoint_auth_methods_supported=[
            "client_secret_post",
            "client_secret_basic",
            "none",
        ],
        registration_endpoint=registration_endpoint,
        revocation_endpoint=revocation_endpoint,
        mcp_spec_versions_supported=list(MCP_SPEC_VERSIONS_SUPPORTED),
    )
