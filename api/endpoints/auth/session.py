# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Session lifecycle auth endpoints: login, logout, refresh, current-user profile.

Extracted verbatim from api/endpoints/auth.py (BE-6042f route-group split).
Auth/token/cookie behavior is unchanged. ``_build_cookie_params`` lives here as
the shared cookie builder used by login/logout/refresh and by first-admin
creation (imported from registration.py).
"""

import logging
import re
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.endpoints.dependencies import get_auth_service
from api.middleware._proxy_aware_ip import ProxyAwareIpResolver
from api.middleware.auth_rate_limiter import get_rate_limiter
from api.middleware.auth_rate_limits import limit_for
from giljo_mcp.auth.dependencies import get_db_session
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.config_manager import get_config
from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import AuthenticationError
from giljo_mcp.models import User
from giljo_mcp.services import AuthService
from giljo_mcp.services.login_lockout_service import (
    LOCKOUT_WINDOW,
    AccountLockedError,
    LoginLockoutService,
)
from giljo_mcp.utils.log_sanitizer import sanitize

from .models import LoginRequest, LoginResponse, LogoutResponse, UserProfileResponse


logger = logging.getLogger(__name__)
router = APIRouter()

# SEC-3001a Wave 2 item 6: per-(identifier, IP) login lockout. Stateless service.
_login_lockout = LoginLockoutService()


@lru_cache(maxsize=1)
def _get_ip_resolver() -> ProxyAwareIpResolver:
    """Build the proxy-aware IP resolver once, lazily (parses GILJO_TRUSTED_PROXIES
    on the first login, by which point the env is set — mirrors the rate limiter)."""
    return ProxyAwareIpResolver()


def _resolve_client_ip(request: Request | None) -> str:
    """Resolve the real client IP (honors X-Forwarded-For only behind a trusted proxy)."""
    if request is None:
        return "unknown"
    return _get_ip_resolver().resolve(request)


async def _notify_login_lockout(auth_service: AuthService, identifier: str, ip: str, locked_until) -> None:
    """Best-effort: publish a neutral ``user:login_lockout`` event when a lockout
    trips, so a SaaS subscriber can email the user (CE has no email; it no-ops).

    Edition-safe: CE publishes primitives only and imports nothing from saas/.
    Enumeration-safe: only emits when the identifier resolves to a real user with
    an email (an attacker locking a non-existent identifier notifies no one).
    """
    try:
        info = await auth_service.find_user_for_lockout_notice(identifier)
        if not info or not info.get("email"):
            return
        from api.app_state import state

        bus = getattr(state, "event_bus", None)
        if bus is None:
            return
        await bus.publish(
            "user:login_lockout",
            {
                "tenant_key": info.get("tenant_key"),
                "user_id": info.get("user_id"),
                "email": info["email"],
                "ip_address": ip,
                "locked_until": locked_until.isoformat() if locked_until else None,
            },
        )
    except Exception:  # noqa: BLE001 - notification must never fail the login response
        logger.warning("login lockout notice publish failed", exc_info=True)


async def _load_db_cookie_domains(db: AsyncSession, tenant_key: str | None) -> list[str]:
    """Read the cookie-domain whitelist from the DB-backed tenant settings store.

    This is the SAME store the admin Settings panel writes via ``SettingsService``
    (``Settings.settings_data['security']['cookie_domain_whitelist']``). BE-9152:
    enforcement now reads it directly so a domain added in the UI actually drives
    cookie scoping -- previously the panel wrote here while ``_build_cookie_params``
    read only the file-based ``config.yaml``, so the UI silently did nothing.

    The whitelist is tenant-scoped (per-user today, per-org after the Teams flip --
    ADR-009). Returns ``[]`` when no tenant_key is available or on any read error,
    so cookie building never fails and installs that never touched the panel keep
    their prior (file-config / origin-matching) behavior.
    """
    if not tenant_key:
        return []
    try:
        from giljo_mcp.services.settings_service import SettingsService

        security = await SettingsService(db, tenant_key).get_settings("security")
        domains = security.get("cookie_domain_whitelist", [])
        if not isinstance(domains, list):
            return []
        return [d for d in domains if isinstance(d, str)]
    except Exception:  # noqa: BLE001 - a whitelist read must never break login/logout/refresh
        logger.warning("cookie-domain whitelist DB read failed; using file config only", exc_info=True)
        return []


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_loopback_host(host_header: str) -> bool:
    """True when the Host header names a loopback address.

    BE-9328: ``localhost`` / ``127.0.0.1`` / ``::1`` are the documented default
    CE install posture (INF-6236: loopback bind over plain http, cross-domain
    auth opt-in), not unknown hosts. Used for LOG LEVEL only -- loopback still
    gets the same host-only cookie it always did.

    Handles the bracketed IPv6 form (``[::1]:7272``, RFC 3986) that the plain
    ``split(":")`` host parsing below mangles into ``"["``.
    """
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host[1:].partition("]")[0]
    elif host.count(":") == 1:
        host = host.split(":")[0]
    return host in _LOOPBACK_HOSTS


def _build_cookie_params(request: Request, db_cookie_domains: list[str] | None = None) -> dict:
    """Build cookie parameters for access_token cookie with secure domain validation.

    Extracts the request host header and applies security checks to determine
    the appropriate cookie domain:
    - IP addresses: domain omitted (browser uses origin-matching per RFC 6265)
    - Domain names: must be whitelisted (see below) or domain=None (fail secure)
    - Loopback hosts: domain omitted, logged at DEBUG (BE-9328 -- the default
      install posture, not something to warn a first-run user about)
    - Unknown hosts: domain=None (fail secure), logged at WARNING

    BE-9152: the whitelist is the union of the DB-backed tenant settings store the
    admin Settings panel writes (``db_cookie_domains``, the authoritative path) and
    the legacy file-based ``config.yaml`` list (still honored so installs that
    configured it there keep working -- data-shape DoD tolerance, no sync bridge).

    Args:
        request: FastAPI Request object for host header extraction.
        db_cookie_domains: whitelist read from the DB settings store for the acting
            tenant (via :func:`_load_db_cookie_domains`). None/empty for callers
            with no tenant context, which fall back to the file config alone.

    Returns:
        dict with keys: key, httponly, secure, samesite, path, domain, max_age.
        Suitable for unpacking into response.set_cookie().
    """
    config = get_config()
    secure_cookies = config.get("security", {}).get("cookies", {}).get("secure", False)
    file_domains = config.get("security", {}).get("cookie_domain_whitelist", []) or []
    allowed_domains = list(file_domains)
    for domain in db_cookie_domains or []:
        if domain not in allowed_domains:
            allowed_domains.append(domain)

    # SEC-3001a Wave 2 (item 3): the keystone auth cookie must carry the Secure
    # flag on any HTTPS deployment (SaaS prod, CE behind TLS) so it is never
    # sent in cleartext -- WITHOUT breaking CE-localhost http login, where a
    # Secure cookie would be silently dropped by the browser over plain http.
    # Mirror the CSRF cookie (api/middleware/csrf.py): derive Secure from the
    # effective connection scheme, which uvicorn resolves from X-Forwarded-Proto
    # behind a reverse proxy / the hosted platform. INF-6236: the effective scheme is now
    # AUTHORITATIVE over config -- https forces Secure on, http forces it off --
    # so a stale config security.cookies.secure=True can never brick http login.
    # config.security.cookies.secure only takes effect when there is no request
    # scheme to derive from.
    if request is not None and request.url.scheme == "https":
        secure_cookies = True
    elif request is not None and request.url.scheme == "http":
        # INF-6236: explicit http downgrade. A stale config security.cookies.secure=True
        # (or an X-Forwarded-Proto=https reaching an http browser through a misconfigured
        # proxy) would otherwise mark the keystone access_token cookie Secure over plain
        # http -- the browser then silently DROPS it, bricking login and 1008-rejecting the
        # WebSocket handshake. Deriving Secure purely from the effective scheme closes that
        # footgun and mirrors the CSRF cookie (api/middleware/csrf.py). The correct fix for a
        # TLS-terminating proxy is FORWARDED_ALLOW_IPS (so the app sees https), NOT forcing
        # Secure over http. SaaS prod is unaffected: it always sees scheme=https.
        secure_cookies = False

    cookie_domain = None
    if request and request.client:
        host_header = request.headers.get("host", "")
        if host_header:
            host_only = host_header.split(":")[0].lower()

            # IP addresses: omit domain so browser uses origin-matching.
            # Setting an explicit domain on IP addresses is unreliable per
            # RFC 6265 Section 5.2.3 (domain attribute is for DNS names).
            # Browsers handle domain=<IP> inconsistently — some reject the
            # cookie entirely. Omitting domain ensures the cookie is scoped
            # to the exact origin, consistent with how csrf_token is set.
            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", host_only):
                cookie_domain = None
                logger.debug(f"Cookie domain omitted for IP address: {host_only} (origin-matching)")

            # Domain names MUST be whitelisted (prevent header injection)
            elif host_only in allowed_domains:
                cookie_domain = host_only
                logger.info(f"Cookie domain set to whitelisted domain: {host_only}")
            # BE-9328: loopback is the default install posture, not an unknown
            # host. Same host-only cookie as before (domain=None, identical to
            # the branch below) -- only the log level changes, so a first-run
            # localhost install no longer warns about a setting it does not need.
            # Deliberately AFTER the whitelist check: an operator who explicitly
            # whitelisted "localhost" keeps the domain-scoped cookie they asked for.
            elif _is_loopback_host(host_header):
                cookie_domain = None
                # host_header, not host_only: the split(":") above mangles the
                # bracketed IPv6 form ("[::1]:7272") down to "[".
                logger.debug(f"Cookie domain omitted for loopback host: {sanitize(host_header)} (host-only cookie)")

            else:
                cookie_domain = None
                logger.warning(
                    f"Host '{host_only}' is not in the cookie-domain whitelist ({allowed_domains}), "
                    f"so the session cookie is scoped to this host only. "
                    f"That is fine for a single-host install; add the domain in "
                    f"Settings -> Network -> cookie domains only if you need cross-domain authentication."
                )

    return {
        "key": "access_token",
        "httponly": True,
        "secure": secure_cookies,
        "samesite": "lax",
        "path": "/",
        "domain": cookie_domain,
        "max_age": 86400,
    }


@router.post("/login", response_model=LoginResponse, tags=["auth"])
async def login(
    login_data: LoginRequest = Body(...),
    response: Response = None,
    request: Request = None,
    auth_service: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Login with username/password, returns JWT in httpOnly cookie.

    This endpoint authenticates a user and sets an httpOnly cookie
    containing a JWT access token valid for 24 hours.

    v3.0 Unified (Handover 0034): No more default password flow.
    Fresh installs go directly to "Create Admin Account" page.

    Rate Limiting (Handover 1009): 5 attempts per minute per IP

    Args:
        request: Login credentials (username, password)
        response: FastAPI response (to set cookie)
        auth_service: Auth service for authentication operations

    Returns:
        Login success message with user info

    Raises:
        HTTPException: 401 if credentials are invalid
        HTTPException: 429 if rate limit exceeded
    """
    # Rate limiting: 5 attempts per minute (Handover 1009)
    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(request, limit=limit_for("login"), window=60, raise_on_limit=True)

    # SEC-3001a Wave 2 item 6: per-(identifier, IP) login lockout. The rate
    # limiter throttles bursts per IP; this stops sustained guessing against one
    # account from one IP (10 fails -> 15-min auto-unlock) WITHOUT letting an
    # attacker from another IP lock the real user out.
    client_ip = _resolve_client_ip(request)
    identifier = login_data.username
    try:
        await _login_lockout.assert_not_locked(db, identifier, client_ip)
    except AccountLockedError as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    # Authenticate user via service
    # Service raises AuthenticationError on failure (0480 migration)
    try:
        auth_result = await auth_service.authenticate_user(login_data.username, login_data.password)
    except AuthenticationError:
        # Wrong password / unknown user counts toward lockout. An inactive-account
        # AuthorizationError (valid password) deliberately does NOT — it propagates
        # untouched. Commit the increment explicitly: this path raises, and the
        # session dependency rolls back on the resulting HTTP error otherwise.
        outcome = await _login_lockout.record_failure(db, identifier, client_ip)
        await db.commit()  # single-writer-allow: login endpoint owns the auth transaction boundary; lockout state is mutated+flushed by LoginLockoutService, the endpoint commits because this path raises
        if outcome.just_locked:
            await _notify_login_lockout(auth_service, identifier, client_ip, outcome.locked_until)
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Your account is temporarily locked.",
                headers={"Retry-After": str(int(LOCKOUT_WINDOW.total_seconds()))},
            ) from None
        raise

    # Successful login clears this (identifier, IP) counter.
    await _login_lockout.clear(db, identifier, client_ip)
    await db.commit()  # single-writer-allow: login endpoint owns the auth transaction boundary; lockout state is mutated+flushed by LoginLockoutService

    # Service now returns AuthResult with flat attributes (no nested "user" dict)
    token = auth_result.token

    # Update last login timestamp
    await auth_service.update_last_login(auth_result.user_id, datetime.now(UTC))

    # IMP-0023: post-login skills-version reminder removed; system_settings drives drift state.

    # v3.0 Unified (Handover 0034): No more default admin/admin password
    # Fresh installs go directly to "Create Admin Account" page
    # This flag is always False for v3.0+ (legacy field removed in Handover 0035)
    password_change_required = False

    # Set httpOnly cookie with secure domain validation. BE-9152: honor the
    # admin-configured cookie-domain whitelist stored per-tenant in the DB.
    db_cookie_domains = await _load_db_cookie_domains(db, auth_result.tenant_key)
    cookie_params = _build_cookie_params(request, db_cookie_domains)
    response.set_cookie(value=token, **cookie_params)

    logger.info(f"User logged in successfully: {sanitize(auth_result.username)} (role: {sanitize(auth_result.role)})")

    # v3.0 Unified: Include password change requirement in response for frontend handling
    response_data = {
        "message": "Login successful",
        "username": auth_result.username,
        "role": auth_result.role,
        "tenant_key": auth_result.tenant_key,
    }

    if password_change_required:
        response_data["password_change_required"] = True
        response_data["message"] = "Login successful - password change required"

    return LoginResponse(**response_data)


@router.post("/logout", response_model=LogoutResponse, tags=["auth"])
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Logout by revoking the JWT and clearing the cookie.

    SEC-6001: clearing the cookie alone left the bearer token valid until
    expiry, so a copied/leaked token survived "logout". We now write an
    ``OAuthRevokedToken`` row for the token's jti BEFORE clearing the cookie,
    so ``get_current_user`` rejects it on every future request. Revocation
    accepts an expired-in-grace token so a session on the edge of expiry still
    revokes. Cookie domain/path/secure/samesite must match the values used when
    setting the cookie, otherwise the browser will not clear it.

    Args:
        request: FastAPI request (for cookie domain resolution + access_token cookie)
        response: FastAPI response (to clear cookie)
        db: Database session for writing the revocation row

    Returns:
        Logout success message
    """
    access_token = request.cookies.get("access_token")
    tenant_key = None
    if access_token:
        from giljo_mcp.services.oauth_revocation_service import revoke_dashboard_access_jwt

        await revoke_dashboard_access_jwt(db, token=access_token)
        # BE-9152: resolve the tenant from the (possibly just-expired) cookie so the
        # clear uses the SAME whitelist-derived domain the cookie was set with --
        # a domain mismatch would leave the browser cookie uncleared after logout.
        payload = JWTManager.verify_token_allow_expired(access_token)
        if payload:
            tenant_key = payload.get("tenant_key")

    db_cookie_domains = await _load_db_cookie_domains(db, tenant_key)
    cookie_params = _build_cookie_params(request, db_cookie_domains)
    response.delete_cookie(
        key="access_token",
        path=cookie_params["path"],
        domain=cookie_params["domain"],
        secure=cookie_params["secure"],
        samesite=cookie_params["samesite"],
    )

    logger.info("User logged out successfully")

    return LogoutResponse(message="Logout successful")


@router.post("/refresh", tags=["auth"])
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
):
    """Silently refresh the access token.

    - If token is valid: issues new token (sliding window session extension)
    - If token expired within grace period (1h): validates user in DB, issues new token
    - If token beyond grace period or invalid: returns 401

    Args:
        request: FastAPI request (for cookie extraction and domain resolution)
        response: FastAPI response (to set new cookie)
        db: Database session (managed by FastAPI dependency injection)

    Returns:
        JSON with message and username on success

    Raises:
        HTTPException: 401 if no token, token beyond grace period, or user inactive
    """
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="No token present")

    payload = JWTManager.verify_token_allow_expired(access_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token expired beyond grace period")

    user_id = payload.get("sub")
    tenant_key = payload.get("tenant_key")

    # SEC-3001a Wave 2 (item 2): honor revocation on the refresh seam. Logout
    # (and RFC 7009 /oauth/revoke) write an OAuthRevokedToken row for the
    # token's jti, but until now /refresh never consulted it -- so a
    # logged-out-but-not-yet-expired cookie could be silently exchanged for a
    # brand-new 24h token, fully defeating logout revocation. This read-only
    # check introduces no concurrent-refresh race (it never revokes the
    # presented token). NOTE: jti-rotation (revoking the OLD jti on each
    # refresh) is deliberately NOT done here -- that carries a concurrent-
    # refresh logout race and is held for owner review (SEC-3001a Wave 2).
    jti = payload.get("jti")
    if jti and tenant_key:
        from giljo_mcp.services.oauth_revocation_service import is_access_token_jti_revoked

        if await is_access_token_jti_revoked(db, tenant_key=tenant_key, jti=jti):
            raise HTTPException(status_code=401, detail="Token has been revoked")

    with tenant_session_context(db, tenant_key):
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
        )
        user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer active")

    # SEC-6011: forced-logout epoch gate on the refresh seam. The presented
    # (expired) cookie carries the `rev` it was minted with; if an admin
    # force-logout has since bumped the user's epoch, refreshing that cookie
    # would mint a brand-new 24h token and defeat the logout — so reject it,
    # mirroring the jti-revocation gate above. A re-login (fresh epoch) works.
    try:
        token_epoch = int(payload.get("rev", 0) or 0)
    except (TypeError, ValueError):
        token_epoch = 0
    if (user.token_revocation_epoch or 0) > token_epoch:
        raise HTTPException(status_code=401, detail="Token has been revoked")

    new_token = JWTManager.create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        tenant_key=user.tenant_key,
        revocation_epoch=user.token_revocation_epoch or 0,
    )

    # TSK-9005: rotate the PRIOR jti so the just-superseded cookie cannot be
    # silently refreshed into a fresh 24h token indefinitely past revocation
    # (stolen-cookie containment). Grace-windowed inside rotate_access_token_jti
    # so an in-flight request or a concurrent second /refresh racing this
    # rotation is NOT locked out. Pre-API-0022 tokens carry no jti -> no-op.
    if jti:
        from giljo_mcp.services.oauth_revocation_service import rotate_access_token_jti

        await rotate_access_token_jti(db, tenant_key=tenant_key, jti=jti)

    # BE-9152: honor the admin-configured cookie-domain whitelist (DB store).
    db_cookie_domains = await _load_db_cookie_domains(db, tenant_key)
    cookie_params = _build_cookie_params(request, db_cookie_domains)
    response.set_cookie(value=new_token, **cookie_params)

    logger.info(f"Token refreshed for user: {sanitize(user.username)}")
    return {"message": "Token refreshed", "username": user.username}


@router.get("/me", tags=["auth"])
async def get_me(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get current user profile or return 401 if not authenticated.

    Two-Layout Pattern: Auth routes isolated in AuthLayout, app routes always require valid user.
    This endpoint returns authenticated user data with password_change_required flag when applicable.

    Args:
        request: FastAPI request
        db: Database session (managed by FastAPI dependency injection)

    Returns:
        User profile data if authenticated, 401 JSON response otherwise
    """
    # Try to get current user (optional - doesn't raise exceptions)

    from giljo_mcp.auth.dependencies import get_current_user_optional
    from giljo_mcp.models.organizations import Organization, OrgMembership

    current_user = await get_current_user_optional(
        request=request,
        access_token=request.cookies.get("access_token"),
        x_api_key=request.headers.get("x-api-key"),
        authorization=request.headers.get("authorization"),
        db=db,
    )

    # If no authenticated user, return clean 401 JSON response
    if current_user is None:
        return JSONResponse(
            status_code=401, content={"detail": "Not authenticated. Please login or provide a valid API key."}
        )

    # Handover 0424h: Load organization data if user has org_id
    org_name = None
    org_role = None

    if current_user.org_id:
        # Load organization
        org_stmt = select(Organization).where(Organization.id == current_user.org_id)
        org_result = await db.execute(org_stmt)
        org = org_result.scalar_one_or_none()

        if org:
            org_name = org.name

            # Load membership to get org_role
            membership_stmt = select(OrgMembership).where(
                OrgMembership.org_id == current_user.org_id,
                OrgMembership.user_id == str(current_user.id),
                OrgMembership.is_active,
            )
            membership_result = await db.execute(membership_stmt)
            membership = membership_result.scalar_one_or_none()

            if membership:
                org_role = membership.role

    # Check if password change is required (for admin user with default password)

    # v3.0 Unified (Handover 0034): No more default admin/admin password
    # Fresh installs go directly to "Create Admin Account" page via first_admin_created flag
    # This check removed in Handover 0035 (field no longer exists in SetupState model)
    password_change_required = None

    # Return authenticated user profile with org data (Handover 0424h)
    return UserProfileResponse(
        id=str(current_user.id),
        username=current_user.username,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        full_name=current_user.full_name,
        role=current_user.role,
        tenant_key=current_user.tenant_key,
        is_active=current_user.is_active,
        created_at=current_user.created_at.isoformat(),
        last_login=current_user.last_login.isoformat() if current_user.last_login else None,
        password_change_required=password_change_required,
        org_id=str(current_user.org_id) if current_user.org_id else None,
        org_name=org_name,
        org_role=org_role,
        setup_complete=current_user.setup_complete,
        setup_selected_tools=current_user.setup_selected_tools,
        setup_step_completed=current_user.setup_step_completed,
        learning_complete=current_user.learning_complete,
        learning_beat=current_user.learning_beat,
        router_choice=current_user.router_choice,
    )
