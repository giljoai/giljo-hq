# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.http.url_resolver import get_public_base_url
from giljo_mcp.models import User
from giljo_mcp.platform_registry import VALID_EXPORT_PLATFORMS
from giljo_mcp.utils.log_sanitizer import mask_token, sanitize


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/download", tags=["downloads"])




@router.post("/generate-token", status_code=status.HTTP_201_CREATED)
async def generate_download_token(
    request: Request,
    content_type: str | None = Query(None, pattern="^(slash_commands)$"),
    platform: str = Query(
        default="claude_code", description="Target platform: claude_code, codex_cli, opencode, generic"
    ),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    body: dict | None = Body(None),
) -> dict:
    """
    Generate one-time download token (requires authentication).

    This endpoint creates a temporary download token that can be used once
    to download the requested content type. Token expires after 15 minutes.

    **Authentication**: Required - JWT cookie or API key header
    **Rate Limiting**: Standard rate limits apply

    Args:
        request: FastAPI request object
        content_type: Type of content to download ('slash_commands')
        current_user: Authenticated user (injected via Depends)
        db: Database session

    Returns:
        {
            "download_url": "https://mcp.example.com/api/download/temp/{token}/file.zip",
            "expires_at": "2025-11-04T10:45:00Z",
            "content_type": "slash_commands",
            "one_time_use": true
        }

    Raises:
        HTTPException 400: Invalid content_type
        HTTPException 401: Not authenticated
        HTTPException 500: Token generation failed

    Example:
        curl -X POST http://localhost:7272/api/download/generate-token \\
             -H "X-API-Key: $GILJO_API_KEY" \\
             -H "Content-Type: application/json" \\
             -d '{"content_type": "slash_commands"}'
    """
    if not content_type and body:
        content_type = body.get("content_type")
    if body and body.get("platform"):
        platform = body.get("platform", platform)

    if content_type != "slash_commands":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid content_type. Must be 'slash_commands'",
        )

    valid_platforms = VALID_EXPORT_PLATFORMS
    if platform not in valid_platforms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform '{platform}'. Must be one of: {', '.join(sorted(valid_platforms))}",
        )

    logger.info(
        "Generating download token for user: %s (tenant: %s, content_type: %s)",
        sanitize(current_user.username),
        sanitize(current_user.tenant_key),
        sanitize(str(content_type)),
    )

    from giljo_mcp.downloads.token_manager import TokenManager
    from giljo_mcp.file_staging import FileStaging

    tenant_key = current_user.tenant_key
    token_manager = TokenManager(db_session=db)

    filename = "slash_commands.zip"
    token = await token_manager.generate_token(
        tenant_key=tenant_key,
        download_type=content_type,
        filename=filename,
    )

    staging = FileStaging(db_session=db)
    staging_path = await staging.create_staging_directory(tenant_key, token)
    zip_path, message = await staging.stage_slash_commands(staging_path, platform=platform)

    if not zip_path:
        await token_manager.mark_failed(token, message)
        logger.error(f"Failed to stage content for token {mask_token(token)}: {message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to stage download content"
        )

    await token_manager.mark_ready(token)

    server_url = get_public_base_url(request)
    download_url = f"{server_url}/api/download/temp/{token}/{filename}"

    token_data = await token_manager.get_token_info(token, tenant_key)
    expires_at = token_data["expires_at"] if token_data else None

    logger.info(
        f"Token generated and staged successfully: token={mask_token(token)}, type={content_type}, file={zip_path}"
    )
    return {
        "download_url": download_url,
        "expires_at": expires_at,
        "content_type": content_type,
        "one_time_use": True,
    }


@router.get("/temp/{token}/{filename}")
async def download_temp_file(
    token: str,
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    Download file using one-time token (public, no auth required).

    This endpoint validates the token and serves the requested file.
    Token validation includes:
    - Token exists and is valid
    - Token not expired (15 minute lifetime)
    - Token not already used (one-time use)
    - Filename matches token metadata

    **Authentication**: NOT required - token IS the authentication
    **Security**: Multi-tenant isolation via token validation

    Args:
        token: One-time download token (UUID)
        filename: Expected filename (must match token metadata)
        request: FastAPI request object
        db: Database session

    Returns:
        File download response with ZIP content

    Raises:
        HTTPException 404: Token invalid, expired, or already used
        HTTPException 410: Token already downloaded (one-time use)
        HTTPException 500: File not found or internal error

    Security Notes:
        - Directory traversal attacks prevented
        - Cross-tenant access denied (returns 404, not 403)
        - No-cache headers prevent stale links
        - File cleanup after download

    Example:
        curl -O http://localhost:7272/api/download/temp/{token}/slash_commands.zip
    """
    logger.info(f"Download request: token={mask_token(token)}, filename={sanitize(filename)}")

    try:
        from giljo_mcp.downloads.token_manager import TokenManager
        from giljo_mcp.file_staging import FileStaging

        if not FileStaging.validate_filename(filename):
            logger.warning(f"Invalid filename requested: {sanitize(filename)}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid token or file")

        token_manager = TokenManager(db_session=db)

        token_info = await token_manager.get_token_info_by_token(token)
        if not token_info:
            logger.warning(f"Token validation failed: token={mask_token(token)}, reason=not_found")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token invalid or not ready")

        if token_info["is_expired"]:
            logger.warning(f"Token validation failed: token={mask_token(token)}, reason=expired")
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Download token expired")

        if token_info.get("staging_status") != "ready":
            logger.warning(
                f"Token validation failed: token={mask_token(token)}, reason=not_ready, "
                f"status={sanitize(token_info.get('staging_status'))}"
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token invalid or not ready")

        expected_filename = token_info.get("filename", "")
        if expected_filename != filename:
            logger.warning(f"Token validation failed: token={mask_token(token)}, reason=filename_mismatch")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        tenant_key = token_info["tenant_key"]

        safe_token = token_info["token"]

        file_path = Path.cwd() / "temp" / tenant_key / safe_token / filename

        if not file_path.exists():
            logger.error(f"File not found for valid token: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error: staged file not found",
            )

        try:
            content = file_path.read_bytes()
        except (OSError, ValueError, KeyError) as e:
            logger.exception("Failed reading file {file_path}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server error") from e

        if not await token_manager.claim_download(token, tenant_key):
            logger.warning(f"Token validation failed: token={mask_token(token)}, reason=already_used")
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Download token already used")

        logger.info(f"Download served: {sanitize(filename)} ({len(content)} bytes) token={mask_token(token)}")

        try:
            ws_manager = request.app.state.websocket_manager
            if ws_manager and tenant_key and filename in ("slash_commands.zip", "giljo_setup.zip"):
                from giljo_mcp.events.schemas import EventFactory

                event = EventFactory.setup_commands_installed(
                    tenant_key=tenant_key,
                    user_id="cli_download",
                    tool_name="all",
                    command_count=0,
                )
                await ws_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
            pass

        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except (OSError, ValueError, KeyError) as e:
        logger.exception("Unexpected error during download")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error") from e
