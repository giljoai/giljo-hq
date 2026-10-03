# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.principal import PrincipalValidationError, validate_principal
from giljo_mcp.exceptions import AuthorizationError
from giljo_mcp.models import APIKey, User


logger = logging.getLogger(__name__)


async def get_db_session(request: Request = None):
    try:
        db_manager = request.app.state.api_state.db_manager
    except AttributeError as e:
        logger.exception("db_manager not available in app state")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized - system may be in setup mode",
        ) from e

    if db_manager is None:
        logger.error("db_manager is None - setup mode active")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized - complete setup wizard first",
        )

    tenant_key = getattr(request.state, "tenant_key", None) if request is not None else None

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        if request is not None:
            session.info["request_path"] = request.url.path
        yield session


async def _record_api_key_usage(db: AsyncSession, request: Request, api_key_id: str | None) -> None:
    if not api_key_id:
        return
    try:
        await db.execute(
            update(APIKey.__table__).where(APIKey.__table__.c.id == api_key_id).values(last_used=datetime.now(UTC))
        )
        await db.commit()

        from giljo_mcp.auth.ip_logger import log_api_key_ip

        client_ip = request.client.host if request.client else "unknown"
        await log_api_key_ip(db, str(api_key_id), client_ip)
    except SQLAlchemyError:
        await db.rollback()
        logger.warning("API-key usage bookkeeping failed (non-blocking)", exc_info=True)


async def get_current_user(
    request: Request,
    access_token: str | None = Cookie(None),
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    logger.debug(
        "[AUTH] get_current_user called - path: %s, cookie: %s, api_key: %s, auth_header: %s",
        request.url.path,
        bool(access_token),
        bool(x_api_key),
        bool(authorization),
    )

    bearer_token: str | None = None
    if authorization and str(authorization).lower().startswith("bearer "):
        bearer_token = str(authorization).split(" ", 1)[1].strip()

    prefetched = getattr(getattr(request, "state", None), "auth_user", None)

    if access_token:
        try:
            principal = await validate_principal(db, jwt_token=access_token, prefetched_user=prefetched)
            logger.debug("[AUTH] JWT cookie SUCCESS - User: %s, Tenant: %s", principal.username, principal.tenant_key)
            _stamp_auth_credential(request, "cookie")
            return principal.user
        except PrincipalValidationError as exc:
            logger.warning("[AUTH] JWT cookie rejected (%s)", exc.reason.value)

    if bearer_token and not access_token:
        try:
            principal = await validate_principal(db, jwt_token=bearer_token, prefetched_user=prefetched)
            logger.debug("[AUTH] Bearer JWT SUCCESS - User: %s, Tenant: %s", principal.username, principal.tenant_key)
            _stamp_auth_credential(request, "bearer")
            return principal.user
        except PrincipalValidationError as exc:
            logger.warning("[AUTH] Bearer JWT rejected (%s)", exc.reason.value)

    if x_api_key:
        try:
            principal = await validate_principal(db, api_key=x_api_key)
        except PrincipalValidationError as exc:
            logger.warning("[AUTH] API key rejected (%s)", exc.reason.value)
            from api.middleware.auth_rate_limiter import enforce_api_key_auth_failure

            await enforce_api_key_auth_failure(request)
        else:
            await _record_api_key_usage(db, request, principal.api_key_id)
            logger.debug("[AUTH] API key SUCCESS - User: %s, Tenant: %s", principal.username, principal.tenant_key)
            _stamp_auth_credential(request, "api_key")
            return principal.user

    credentials_supplied = bool(access_token) or bool(x_api_key)
    if credentials_supplied:
        logger.warning(
            f"[AUTH] FAILED - credentials supplied but invalid (path: {request.url.path}, cookie: {bool(access_token)}, api_key: {bool(x_api_key)})"
        )
    else:
        logger.info(f"[AUTH] anonymous request to {request.url.path} (no cookie, no api_key)")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated. Please login or provide a valid API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_active_user(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This endpoint requires authentication (not available in localhost mode)",
        )

    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account is inactive")

    route = request.scope.get("route")
    route_name = getattr(route, "name", None) or request.url.path
    violation = await act_first_gate_violation(
        must_change_password=current_user.must_change_password,
        tenant_key=current_user.tenant_key,
        db=db,
        route=route_name,
        browser_session=is_browser_session(request),
    )
    if violation is not None:
        raise violation

    from api.observability.sentry_init import set_tenant_context

    set_tenant_context(tenant_key=current_user.tenant_key, user_id=str(current_user.id))

    return current_user


ACT_FIRST_GATE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "complete_first_login",
        "change_password",
        "reaccept_terms",
        "get_account_status",
        "health_check",
    }
)

TermsAcceptedCheck = Callable[[AsyncSession, str], Awaitable[bool]]
_terms_accepted_check: TermsAcceptedCheck | None = None


def register_terms_accepted_check(check: TermsAcceptedCheck) -> None:
    global _terms_accepted_check  # noqa: PLW0603
    _terms_accepted_check = check


async def act_first_gate_violation(
    *,
    must_change_password: bool,
    tenant_key: str,
    db: AsyncSession | None,
    route: str,
    browser_session: bool,
) -> AuthorizationError | None:
    if route in ACT_FIRST_GATE_ALLOWLIST:
        return None
    if must_change_password:
        return AuthorizationError(
            message="A password change is required before continuing.",
            error_code="PASSWORD_CHANGE_REQUIRED",
        )
    if browser_session and _terms_accepted_check is not None:
        accepted = await _terms_accepted_check(db, tenant_key=tenant_key)
        if not accepted:
            return AuthorizationError(
                message="Updated Terms of Service must be accepted before continuing.",
                error_code="TERMS_REACCEPTANCE_REQUIRED",
            )
    return None


async def require_admin(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required. Your role: " + current_user.role
        )
    return current_user


async def require_ce_mode() -> None:
    from api.app_state import GILJO_MODE

    if GILJO_MODE not in ("", "ce"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)



SENSITIVE_ACCOUNT_FIELDS: frozenset[str] = frozenset({"password", "email", "is_active", "recovery_pin"})


def _stamp_auth_credential(request: Request, credential: str) -> None:
    if request is not None and hasattr(request, "state"):
        request.state.auth_method = credential


def is_browser_session(request: Request) -> bool:
    return getattr(getattr(request, "state", None), "auth_method", None) == "cookie"


async def require_browser_session(request: Request, _user: User = Depends(get_current_active_user)) -> None:
    if not is_browser_session(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires an interactive browser session; API keys and OAuth tokens cannot perform it.",
        )


def enforce_sensitive_account_field_guard(request: Request, payload: object) -> None:
    writing_sensitive = any(getattr(payload, field, None) is not None for field in SENSITIVE_ACCOUNT_FIELDS)
    if writing_sensitive and not is_browser_session(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password, email, and account-status changes require an interactive browser session; "
            "API keys and OAuth tokens cannot perform them.",
        )
    if getattr(payload, "recovery_pin", None) is not None:
        from api.app_state import GILJO_MODE

        if GILJO_MODE not in ("", "ce"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Recovery PIN is not available in hosted mode.",
            )


async def get_current_user_optional(
    request: Request,
    access_token: str | None = Cookie(None),
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db_session),
) -> User | None:
    try:
        return await get_current_user(
            request=request,
            access_token=access_token,
            x_api_key=x_api_key,
            authorization=authorization,
            db=db,
        )
    except HTTPException:
        return None
