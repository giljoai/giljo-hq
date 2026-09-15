# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import logging
from datetime import UTC, datetime, timedelta

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
from api.middleware.auth_rate_limiter import get_rate_limiter
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import User
from giljo_mcp.repositories.auth_repository import AuthRepository
from giljo_mcp.services.oauth_refresh_service import (
    revoke_all_for_user as revoke_all_refresh_tokens_for_user,
)


logger = logging.getLogger(__name__)
router = APIRouter()




@router.post("/verify-pin-and-reset-password", response_model=PinPasswordResetResponse, tags=["auth"])
async def verify_pin_and_reset_password(
    http_request: Request, request_data: PinPasswordResetRequest = Body(...), db: AsyncSession = Depends(get_db_session)
):
    """
    Verify recovery PIN and reset password (Handover 0023).

    Security Features:
    - Generic error messages (doesn't reveal username existence)
    - IP-based rate limiting: 3 attempts per minute (Handover 1009)
    - Account lockout: 5 failed attempts → 15 minute lockout (per-user)
    - Timing-safe PIN comparison (bcrypt)
    - PIN never stored in plaintext
    - Audit logging for security monitoring

    Flow:
    1. Check IP-based rate limit (3/min across all users)
    2. Find user by username
    3. Check per-user lockout status (pin_lockout_until)
    4. Verify PIN with bcrypt
    5. If invalid: Increment failed_pin_attempts, trigger lockout if >= 5
    6. If valid: Reset password, clear lockout

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
    await rate_limiter.check_rate_limit(http_request, limit=3, window=60, raise_on_limit=True)

    if request_data.new_password != request_data.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")

    user = await AuthRepository().get_user_by_username_or_email(db, request_data.username)

    if not user:
        logger.warning("PIN reset attempt for non-existent identifier")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid username or PIN")

    if not user.recovery_pin_hash:
        logger.warning(f"PIN reset attempt for user without PIN: {user.username}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid username or PIN")

    if user.pin_lockout_until and datetime.now(UTC) < user.pin_lockout_until:
        lockout_remaining = user.pin_lockout_until - datetime.now(UTC)
        minutes_remaining = int(lockout_remaining.total_seconds() / 60)
        logger.warning(
            f"PIN reset attempt while locked out - user: {user.username}, remaining: {minutes_remaining} minutes"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account locked out due to too many failed attempts. Try again in {minutes_remaining} minutes.",
        )

    if not await asyncio.to_thread(
        bcrypt.checkpw, request_data.recovery_pin.encode("utf-8"), user.recovery_pin_hash.encode("utf-8")
    ):
        user.failed_pin_attempts += 1

        if user.failed_pin_attempts >= 5:
            user.pin_lockout_until = datetime.now(UTC) + timedelta(minutes=15)
            await db.commit()

            logger.warning(
                f"PIN lockout triggered - user: {user.username}, "
                f"attempts: {user.failed_pin_attempts}, lockout until: {user.pin_lockout_until}"
            )

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Account locked out due to too many failed attempts. Try again in 15 minutes.",
            )

        await db.commit()

        attempts_remaining = 5 - user.failed_pin_attempts
        logger.warning(
            f"Invalid PIN attempt - user: {user.username}, "
            f"attempts: {user.failed_pin_attempts}, remaining: {attempts_remaining}"
        )

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid username or PIN")

    user.password_hash = (
        await asyncio.to_thread(bcrypt.hashpw, request_data.new_password.encode("utf-8"), bcrypt.gensalt())
    ).decode("utf-8")
    user.failed_pin_attempts = 0
    user.pin_lockout_until = None

    user.token_revocation_epoch = (user.token_revocation_epoch or 0) + 1
    with tenant_session_context(db, user.tenant_key):
        revoked_count = await revoke_all_refresh_tokens_for_user(db, user_id=str(user.id), tenant_key=user.tenant_key)

    from giljo_mcp.services.login_lockout_service import LoginLockoutService

    try:
        await LoginLockoutService().clear_for_identifiers(db, [user.username, user.email])
    except Exception:  # noqa: BLE001 - never block a password reset on lockout cleanup
        logger.warning("login lockout clear on PIN reset failed", exc_info=True)

    await db.commit()

    logger.info(
        f"Password reset successful via PIN - user: {user.username} "
        f"(revocation epoch bumped to {user.token_revocation_epoch}, {revoked_count} refresh token(s) revoked)"
    )

    return PinPasswordResetResponse(message="Password reset successful")


class VerifyPinRequest(BaseModel):
    username: str
    recovery_pin: str = Field(..., min_length=4, max_length=4, pattern="^[0-9]{4}$")


class VerifyPinResponse(BaseModel):
    valid: bool
    message: str


@router.post("/verify-pin", response_model=VerifyPinResponse, tags=["auth"])
async def verify_pin(request_data: VerifyPinRequest = Body(...), db: AsyncSession = Depends(get_db_session)):
    """
    Verify recovery PIN without resetting password.

    Used by the forgot-password UI to validate the PIN before
    showing the new password form. Does not modify any data.

    AUTH-EMAIL Phase 4: wire field `username` accepts either username OR email.
    """
    if GILJO_MODE not in ("", "ce"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    user = await AuthRepository().get_user_by_username_or_email(db, request_data.username)

    if not user or not user.recovery_pin_hash:
        return VerifyPinResponse(valid=False, message="Invalid username or PIN")

    if user.pin_lockout_until and datetime.now(UTC) < user.pin_lockout_until:
        lockout_remaining = user.pin_lockout_until - datetime.now(UTC)
        minutes_remaining = int(lockout_remaining.total_seconds() / 60)
        return VerifyPinResponse(valid=False, message=f"Account locked. Try again in {minutes_remaining} minutes.")

    if not await asyncio.to_thread(
        bcrypt.checkpw, request_data.recovery_pin.encode("utf-8"), user.recovery_pin_hash.encode("utf-8")
    ):
        user.failed_pin_attempts += 1
        if user.failed_pin_attempts >= 5:
            user.pin_lockout_until = datetime.now(UTC) + timedelta(minutes=15)
        await db.commit()
        attempts_remaining = max(0, 5 - user.failed_pin_attempts)
        return VerifyPinResponse(valid=False, message=f"Invalid PIN. {attempts_remaining} attempts remaining.")

    return VerifyPinResponse(valid=True, message="PIN verified")


@router.post("/check-first-login", response_model=CheckFirstLoginResponse, tags=["auth"])
async def check_first_login(
    request_data: CheckFirstLoginRequest = Body(...), db: AsyncSession = Depends(get_db_session)
):
    """
    Check if user must change password or set PIN on first login (Handover 0023).

    Used by frontend after successful login to determine if additional
    setup is required before accessing the dashboard.

    Args:
        request_data: Username to check
        db: Database session

    Returns:
        must_change_password and must_set_pin flags (safe defaults for unknown users)
    """
    user = await AuthRepository().get_user_by_username_or_email(db, request_data.username)

    if not user:
        return CheckFirstLoginResponse(must_change_password=False, must_set_pin=False)

    must_set_pin = bool(user.must_set_pin) if GILJO_MODE in ("", "ce") else False

    return CheckFirstLoginResponse(must_change_password=user.must_change_password or False, must_set_pin=must_set_pin)


@router.post("/complete-first-login", response_model=CompleteFirstLoginResponse, tags=["auth"])
async def complete_first_login(
    request_data: CompleteFirstLoginRequest = Body(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Complete first login by changing password and setting recovery PIN (Handover 0023).

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
    if not await asyncio.to_thread(
        bcrypt.checkpw, request_data.current_password.encode("utf-8"), current_user.password_hash.encode("utf-8")
    ):
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

    logger.info(
        f"First login completed - user: {current_user.username} "
        f"(revocation epoch bumped to {current_user.token_revocation_epoch}, {revoked_count} refresh token(s) revoked)"
    )

    return CompleteFirstLoginResponse(message="First login completed successfully")
