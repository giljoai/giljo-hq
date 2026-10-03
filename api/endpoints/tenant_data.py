# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import shutil

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth_rate_limiter import get_rate_limiter
from api.middleware.auth_rate_limits import limit_for
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.http.url_resolver import get_public_base_url
from giljo_mcp.models import User
from giljo_mcp.services.tenant_export_service import TenantExportService
from giljo_mcp.utils.log_sanitizer import mask_token, sanitize


logger = logging.getLogger(__name__)
router = APIRouter(tags=["tenant-data"])


_EXPORT_FILENAME = "tenant_export.zip"
_EXPORT_WINDOW_SECONDS = 900


@router.post("/export", status_code=status.HTTP_200_OK)
async def export_tenant_data(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Export the authenticated user's tenant data as a downloadable ZIP.

    Returns a one-time download URL (15-minute TTL) plus per-model row counts.
    At most 3 exports per client every 15 minutes; more returns 429.
    """
    from api.app_state import GILJO_MODE

    if GILJO_MODE == "saas" and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Data export requires an organization admin role.",
        )

    await get_rate_limiter().check_rate_limit(
        request, limit=limit_for("account_export"), window=_EXPORT_WINDOW_SECONDS, raise_on_limit=True
    )

    tenant_key = current_user.tenant_key
    ws_manager = getattr(request.app.state, "websocket_manager", None)

    logger.info(
        "Starting tenant export for user=%s tenant=%s",
        sanitize(current_user.username),
        sanitize(tenant_key),
    )

    service = TenantExportService(db_session=db, websocket_manager=ws_manager)
    zip_path, model_counts = await service.export(tenant_key=tenant_key)

    from giljo_mcp.downloads.token_manager import TokenManager
    from giljo_mcp.file_staging import FileStaging

    token_manager = TokenManager(db_session=db)
    token = await token_manager.generate_token(
        tenant_key=tenant_key,
        download_type="tenant_export",
        filename=_EXPORT_FILENAME,
    )

    staging = FileStaging(db_session=db)
    staging_dir = await staging.create_staging_directory(tenant_key, token)
    staged_path = staging_dir / _EXPORT_FILENAME
    shutil.move(str(zip_path), str(staged_path))

    await token_manager.mark_ready(token, tenant_key=tenant_key)

    server_url = get_public_base_url(request)
    download_url = f"{server_url}/api/download/temp/{token}/{_EXPORT_FILENAME}"

    token_data = await token_manager.get_token_info(token, tenant_key)
    expires_at = token_data["expires_at"] if token_data else None

    logger.info(
        "Tenant export ready: tenant=%s token=%s bytes=%d models=%d",
        sanitize(tenant_key),
        mask_token(token),
        staged_path.stat().st_size,
        len(model_counts),
    )

    return {
        "download_url": download_url,
        "expires_at": expires_at,
        "model_counts": model_counts,
    }
