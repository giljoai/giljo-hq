# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import ipaddress
import logging
from datetime import UTC, datetime

import bcrypt
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.app_state import GILJO_MODE
from api.endpoints.auth_models import (
    CheckFirstLoginRequest,
    CheckFirstLoginResponse,
    CompleteFirstLoginRequest,
    CompleteFirstLoginResponse,
    PinPasswordResetRequest,
    PinPasswordResetResponse,
)
from api.middleware._proxy_aware_ip import CLIENT_FROM_HEADER_SCOPE_KEY
from api.middleware.auth_rate_limiter import get_rate_limiter
from giljo_mcp.auth.dependencies import get_current_active_user, get_current_user, get_db_session
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import User
from giljo_mcp.repositories.auth_repository import AuthRepository
from giljo_mcp.services.oauth_refresh_service import (
    revoke_all_for_user as revoke_all_refresh_tokens_for_user,
)
from giljo_mcp.services.session_eviction import SESSION_REVOKED, close_live_user_sockets
from giljo_mcp.services.user_auth_service import (
    lock_pin_state,
    pin_locked,
    record_failed_pin_attempt,
    reset_password_via_pin,
    verify_current_password,
)
from giljo_mcp.utils.password_helper import DUMMY_BCRYPT_HASH, async_verify_password


logger = logging.getLogger(__name__)
router = APIRouter()

_GENERIC_INVALID_PIN_MESSAGE = "Invalid username or PIN"
_FORWARDING_HEADERS = frozenset({"forwarded", "x-forwarded-for", "x-real-ip", "cf-connecting-ip"})


def _is_console_caller(request: Request) -> bool:
    client = getattr(request, "client", None)
    if client is None or (getattr(request, "scope", None) or {}).get(CLIENT_FROM_HEADER_SCOPE_KEY):
        return False
    if any(name.lower() in _FORWARDING_HEADERS for name in request.headers):
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        return False


async def _pin_guess_allowed(db: AsyncSession, user: User, http_request: Request) -> bool:
    if _is_console_caller(http_request):
        return True
    if pin_locked(user):
        return False
    await lock_pin_state(db, user)
    return not pin_locked(user)


def _lockout_detail(user: User) -> str:
    minutes = max(1, int((user.pin_lockout_until - datetime.now(UTC)).total_seconds() // 60))
    return f"Account locked out due to too many failed attempts. Try again in {minutes} minutes."




@router.post("/verify-pin-and-reset-password", response_model=PinPasswordResetResponse, tags=["auth"])
async def verify_pin_and_reset_password(
    http_request: Request, request_data: PinPasswordResetRequest = Body(...), db: AsyncSession = Depends(get_db_session)
):
    """
    Verify recovery PIN and reset password.

    Security Features:
    - Generic error messages (doesn't reveal username existence)
    - IP-based rate limiting: 3 attempts per minute
    - Account lockout: after 5 failed attempts recovery locks for 15 minutes,
      and each further failure locks for longer (1 hour, 4 hours, then 24 hours)
      until a successful reset or a password sign-in
    - A request made directly on the server machine (localhost, no proxy) is
      never locked out
    - Timing-safe PIN comparison (bcrypt)
    - PIN never stored in plaintext
    - Audit logging for security monitoring

    Args:
        http_request: FastAPI request object
        request_data: Username, PIN, new password
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: 400 if username/PIN invalid
        HTTPException: 429 if rate limit exceeded or user is locked out
    """
    if GILJO_MODE not in ("", "ce"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(http_request, limit=3, window=60, raise_on_limit=True, policy="pin_recovery")

    if request_data.new_password != request_data.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")

    user = await AuthRepository().get_user_by_username_or_email(db, request_data.username)

    if not user:
        logger.warning("PIN reset attempt for non-existent identifier")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid username or PIN")

    if not user.recovery_pin_hash:
        logger.warning(f"PIN reset attempt for user without PIN: {user.username}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid username or PIN")

    if not await _pin_guess_allowed(db, user, http_request):
        logger.warning(f"PIN reset attempt while locked out - user: {user.username}")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_lockout_detail(user))

    if not await async_verify_password(request_data.recovery_pin, user.recovery_pin_hash):
        await record_failed_pin_attempt(db, user)

        if pin_locked(user):
            logger.warning(
                f"PIN lockout triggered - user: {user.username}, "
                f"attempts: {user.failed_pin_attempts}, lockout until: {user.pin_lockout_until}"
            )
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_lockout_detail(user))

        logger.warning(f"Invalid PIN attempt - user: {user.username}, attempts: {user.failed_pin_attempts}")

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid username or PIN")

    await reset_password_via_pin(db, user, request_data.new_password)

    logger.info("Password reset successful via PIN; live sessions revoked")

    return PinPasswordResetResponse(message="Password reset successful")


class VerifyPinRequest(BaseModel):
    username: str = Field(..., max_length=255)
    recovery_pin: str = Field(..., min_length=4, max_length=4, pattern="^[0-9]{4}$")


class VerifyPinResponse(BaseModel):
    valid: bool
    message: str


@router.post("/verify-pin", response_model=VerifyPinResponse, tags=["auth"])
async def verify_pin(
    http_request: Request, request_data: VerifyPinRequest = Body(...), db: AsyncSession = Depends(get_db_session)
):
    """
    Verify recovery PIN without resetting password.

    Used by the forgot-password UI to validate the PIN before
    showing the new password form. Does not modify any data.

    The `username` field accepts either a username or an email.

    Every failure (unknown username, no PIN set, locked out, wrong PIN)
    returns the same generic message and a comparable bcrypt-verify time.
    Rate-limited to 3 requests per minute per IP.
    """
    if GILJO_MODE not in ("", "ce"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(http_request, limit=3, window=60, raise_on_limit=True, policy="pin_recovery")

    user = await AuthRepository().get_user_by_username_or_email(db, request_data.username)

    if not user or not user.recovery_pin_hash:
        await async_verify_password(request_data.recovery_pin, DUMMY_BCRYPT_HASH)
        return VerifyPinResponse(valid=False, message=_GENERIC_INVALID_PIN_MESSAGE)

    if not await _pin_guess_allowed(db, user, http_request):
        await async_verify_password(request_data.recovery_pin, DUMMY_BCRYPT_HASH)
        return VerifyPinResponse(valid=False, message=_GENERIC_INVALID_PIN_MESSAGE)

    if not await async_verify_password(request_data.recovery_pin, user.recovery_pin_hash):
        await record_failed_pin_attempt(db, user)
        return VerifyPinResponse(valid=False, message=_GENERIC_INVALID_PIN_MESSAGE)

    return VerifyPinResponse(valid=True, message="PIN verified")


@router.post("/check-first-login", response_model=CheckFirstLoginResponse, tags=["auth"])
async def check_first_login(
    request_data: CheckFirstLoginRequest = Body(...),
    current_user: User = Depends(get_current_user),
):
    """
    Check if the signed-in user must change password or set PIN on first login.

    Used by frontend after successful login to determine if additional
    setup is required before accessing the dashboard.

    The flags always describe the signed-in caller, whatever ``username`` the
    request carries (the field is accepted for older clients and not used), so
    the endpoint never tells one account about another.

    Args:
        request_data: Accepted for compatibility; not used
        current_user: The signed-in caller

    Returns:
        must_change_password and must_set_pin flags
    """
    must_set_pin = bool(current_user.must_set_pin) if GILJO_MODE in ("", "ce") else False

    return CheckFirstLoginResponse(
        must_change_password=current_user.must_change_password or False, must_set_pin=must_set_pin
    )


@router.post("/complete-first-login", response_model=CompleteFirstLoginResponse, tags=["auth"])
async def complete_first_login(
    request_data: CompleteFirstLoginRequest = Body(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Complete first login by changing password and setting recovery PIN.

    Requires authentication (JWT token from initial login with default password).

    Flow:
    1. Verify current password
    2. Validate new password != current password
    3. Validate PIN confirmation match
    4. Update password_hash
    5. Set recovery_pin_hash (bcrypt)
    6. Clear must_change_password and must_set_pin flags

    Args:
        request_data: Password change and PIN setup data
        current_user: Authenticated user from JWT token
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: 400 if validation fails
    """
    if not await verify_current_password(db, current_user, request_data.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    if request_data.new_password == request_data.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different from current password"
        )

    if request_data.new_password != request_data.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")

    pin_required = GILJO_MODE in ("", "ce")
    if pin_required:
        if not request_data.recovery_pin or not request_data.confirm_pin:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Recovery PIN is required")
        if request_data.recovery_pin != request_data.confirm_pin:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PINs do not match")

    current_user.password_hash = (
        await asyncio.to_thread(bcrypt.hashpw, request_data.new_password.encode("utf-8"), bcrypt.gensalt())
    ).decode("utf-8")

    if pin_required:
        current_user.recovery_pin_hash = (
            await asyncio.to_thread(bcrypt.hashpw, request_data.recovery_pin.encode("utf-8"), bcrypt.gensalt())
        ).decode("utf-8")

    current_user.must_change_password = False
    current_user.must_set_pin = False

    current_user.token_revocation_epoch = (current_user.token_revocation_epoch or 0) + 1
    with tenant_session_context(db, current_user.tenant_key):
        revoked_count = await revoke_all_refresh_tokens_for_user(
            db, user_id=str(current_user.id), tenant_key=current_user.tenant_key
        )

    await db.commit()
    await close_live_user_sockets(current_user.tenant_key, logger, reason=SESSION_REVOKED)

    logger.info(
        f"First login completed - user: {current_user.username} "
        f"(revocation epoch bumped to {current_user.token_revocation_epoch}, {revoked_count} refresh token(s) revoked)"
    )

    return CompleteFirstLoginResponse(message="First login completed successfully")
