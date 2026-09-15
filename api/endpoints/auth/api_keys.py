# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.endpoints.dependencies import get_auth_service, get_notification_service
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session, require_browser_session
from giljo_mcp.models import User
from giljo_mcp.services import AuthService, NotificationService
from giljo_mcp.utils.log_sanitizer import sanitize

from .models import (
    APIKeyCreateRequest,
    APIKeyCreateResponse,
    APIKeyResponse,
    APIKeyRevokeResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api-keys/active", response_model=list[APIKeyResponse], tags=["auth"])
async def get_active_api_keys(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Return active API keys for current user (no plaintext). Used by setup wizard (Handover 0855a)."""
    from giljo_mcp.models.auth import APIKey

    stmt = select(APIKey).where(
        APIKey.user_id == str(current_user.id),
        APIKey.tenant_key == current_user.tenant_key,
        APIKey.is_active.is_(True),
    )
    result = await db.execute(stmt)
    keys = result.scalars().all()
    return [
        APIKeyResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            permissions=k.permissions or [],
            is_active=k.is_active,
            created_at=k.created_at.isoformat(),
            last_used=k.last_used.isoformat() if k.last_used else None,
            revoked_at=k.revoked_at.isoformat() if k.revoked_at else None,
            expires_at=k.expires_at.isoformat() if k.expires_at else None,
        )
        for k in keys
    ]


@router.get("/api-keys", response_model=list[APIKeyResponse], tags=["auth"])
async def list_api_keys(
    include_revoked: bool = Query(default=False, description="Include revoked keys in results"),
    current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    List all API keys for current user.

    This endpoint returns all API keys (active and revoked) for the authenticated user.
    Keys are masked - only the prefix is shown for security.

    Args:
        current_user: User from JWT token (dependency)
        auth_service: Auth service for API key operations

    Returns:
        List of API keys (masked)
    """
    keys = await auth_service.list_api_keys(str(current_user.id), include_revoked=include_revoked)

    return [
        APIKeyResponse(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            permissions=key.permissions,
            is_active=key.is_active,
            created_at=key.created_at,
            last_used=key.last_used,
            revoked_at=key.revoked_at,
            expires_at=key.expires_at,
        )
        for key in keys
    ]


@router.post("/api-keys", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED, tags=["auth"])
async def create_api_key(
    request: APIKeyCreateRequest = Body(...),
    current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
    _browser: None = Depends(require_browser_session),
):
    """
    Generate a new API key for current user.

    This endpoint creates a new API key and returns it in plaintext.
    WARNING: The key is only shown once! Store it securely.

    SEC-9171 #3: minting a key requires a browser session — a held API key or
    OAuth Bearer cannot self-replicate into a fresh long-lived key.

    Args:
        request: API key creation request (name, permissions)
        current_user: User from JWT token (dependency)
        auth_service: Auth service for API key operations

    Returns:
        API key response with plaintext key (shown only once)
    """
    key_data = await auth_service.create_api_key(
        user_id=str(current_user.id),
        tenant_key=current_user.tenant_key,
        name=request.name,
        permissions=request.permissions,
    )

    logger.info(
        f"API key created: {sanitize(key_data.name)} (user: {sanitize(current_user.username)}, prefix: {sanitize(key_data.key_prefix)})"
    )

    return APIKeyCreateResponse(
        id=key_data.id,
        name=key_data.name,
        api_key=key_data.api_key,
        key_prefix=key_data.key_prefix,
        message="API key created successfully. Store this key securely - it will not be shown again!",
        expires_at=key_data.expires_at,
    )


@router.delete("/api-keys/{key_id}", response_model=APIKeyRevokeResponse, tags=["auth"])
async def revoke_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """
    Revoke an API key.

    This endpoint revokes (deactivates) an API key. The key will no longer
    work for authentication after revocation.

    Args:
        key_id: UUID of API key to revoke
        current_user: User from JWT token (dependency)
        auth_service: Auth service for API key operations

    Returns:
        Revocation confirmation

    Raises:
        HTTPException: 404 if key not found or belongs to another user
    """
    await auth_service.revoke_api_key(str(key_id), str(current_user.id), notification_service=notification_service)

    logger.info(f"API key revoked (user: {sanitize(current_user.username)})")

    keys = await auth_service.list_api_keys(str(current_user.id), include_revoked=True)
    key_name = "Unknown"
    for key in keys:
        if key.id == str(key_id):
            key_name = key.name
            break

    return APIKeyRevokeResponse(id=str(key_id), name=key_name, message="API key revoked successfully")
