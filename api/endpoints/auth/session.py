# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

_login_lockout = LoginLockoutService()


@lru_cache(maxsize=1)
def _get_ip_resolver() -> ProxyAwareIpResolver:
    return ProxyAwareIpResolver()


def _resolve_client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    return _get_ip_resolver().resolve(request)


async def _notify_login_lockout(auth_service: AuthService, identifier: str, ip: str, locked_until) -> None:
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
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host[1:].partition("]")[0]
    elif host.count(":") == 1:
        host = host.split(":")[0]
    return host in _LOOPBACK_HOSTS


def _build_cookie_params(request: Request, db_cookie_domains: list[str] | None = None) -> dict:
    config = get_config()
    secure_cookies = config.get("security", {}).get("cookies", {}).get("secure", False)
    file_domains = config.get("security", {}).get("cookie_domain_whitelist", []) or []
    allowed_domains = list(file_domains)
    for domain in db_cookie_domains or []:
        if domain not in allowed_domains:
            allowed_domains.append(domain)

    if request is not None and request.url.scheme == "https":
        secure_cookies = True
    elif request is not None and request.url.scheme == "http":
        secure_cookies = False

    cookie_domain = None
    if request and request.client:
        host_header = request.headers.get("host", "")
        if host_header:
            host_only = host_header.split(":")[0].lower()

            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", host_only):
                cookie_domain = None
                logger.debug(f"Cookie domain omitted for IP address: {host_only} (origin-matching)")

            elif host_only in allowed_domains:
                cookie_domain = host_only
                logger.info(f"Cookie domain set to whitelisted domain: {host_only}")
            elif _is_loopback_host(host_header):
                cookie_domain = None
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
    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(request, limit=limit_for("login"), window=60, raise_on_limit=True)

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

    try:
        auth_result = await auth_service.authenticate_user(login_data.username, login_data.password)
    except AuthenticationError:
        outcome = await _login_lockout.record_failure(db, identifier, client_ip)
        await db.commit()
        if outcome.just_locked:
            await _notify_login_lockout(auth_service, identifier, client_ip, outcome.locked_until)
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Your account is temporarily locked.",
                headers={"Retry-After": str(int(LOCKOUT_WINDOW.total_seconds()))},
            ) from None
        raise

    await _login_lockout.clear(db, identifier, client_ip)
    await db.commit()

    token = auth_result.token

    await auth_service.update_last_login(auth_result.user_id, datetime.now(UTC))


    password_change_required = False

    db_cookie_domains = await _load_db_cookie_domains(db, auth_result.tenant_key)
    cookie_params = _build_cookie_params(request, db_cookie_domains)
    response.set_cookie(value=token, **cookie_params)

    logger.info(f"User logged in successfully: {sanitize(auth_result.username)} (role: {sanitize(auth_result.role)})")

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

    if jti:
        from giljo_mcp.services.oauth_revocation_service import rotate_access_token_jti

        await rotate_access_token_jti(db, tenant_key=tenant_key, jti=jti)

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

    from giljo_mcp.auth.dependencies import get_current_user_optional
    from giljo_mcp.models.organizations import Organization, OrgMembership

    current_user = await get_current_user_optional(
        request=request,
        access_token=request.cookies.get("access_token"),
        x_api_key=request.headers.get("x-api-key"),
        authorization=request.headers.get("authorization"),
        db=db,
    )

    if current_user is None:
        return JSONResponse(
            status_code=401, content={"detail": "Not authenticated. Please login or provide a valid API key."}
        )

    org_name = None
    org_role = None

    if current_user.org_id:
        org_stmt = select(Organization).where(Organization.id == current_user.org_id)
        org_result = await db.execute(org_stmt)
        org = org_result.scalar_one_or_none()

        if org:
            org_name = org.name

            membership_stmt = select(OrgMembership).where(
                OrgMembership.org_id == current_user.org_id,
                OrgMembership.user_id == str(current_user.id),
                OrgMembership.is_active,
            )
            membership_result = await db.execute(membership_stmt)
            membership = membership_result.scalar_one_or_none()

            if membership:
                org_role = membership.role


    password_change_required = None

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
