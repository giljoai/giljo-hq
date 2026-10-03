# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import io
import logging
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.http.url_resolver import get_public_base_url
from giljo_mcp.models import User
from giljo_mcp.platform_registry import (
    EXPORT_CLAUDE_CODE,
    EXPORT_CODEX_CLI,
    EXPORT_GENERIC,
    EXPORT_OPENCODE,
    export_platform_pattern,
)
from giljo_mcp.tools.slash_command_templates import (
    BOOTSTRAP_CLAUDE_CODE,
    BOOTSTRAP_CODEX_CLI,
    BOOTSTRAP_GENERIC,
    BOOTSTRAP_OPENCODE,
    get_all_templates,
)
from giljo_mcp.utils.log_sanitizer import mask_token, sanitize


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/download", tags=["downloads"])
INSTALL_SCRIPT_TEMPLATES_DIR = Path(__file__).parents[3] / "installer" / "templates"




def create_zip_archive(files: dict[str, str]) -> bytes:
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for filename, content in files.items():
            zipf.writestr(filename, content)

    zip_buffer.seek(0)
    return zip_buffer.read()


def render_install_script(
    template_content: str,
    server_url: str,
) -> str:
    return template_content.replace("{{SERVER_URL}}", server_url)




_BOOTSTRAP_TEMPLATES: dict[str, str] = {
    EXPORT_CLAUDE_CODE: BOOTSTRAP_CLAUDE_CODE,
    EXPORT_CODEX_CLI: BOOTSTRAP_CODEX_CLI,
    EXPORT_OPENCODE: BOOTSTRAP_OPENCODE,
    EXPORT_GENERIC: BOOTSTRAP_GENERIC,
}


@router.get("/slash-commands.zip")
async def download_slash_commands(
    request: Request,
    platform: str = Query(
        default="claude_code",
        pattern=export_platform_pattern(),
        description="Target CLI platform: claude_code, codex_cli, opencode, or generic",
    ),
):
    """
    Download slash command/skill templates as ZIP file.

    **Public endpoint** - No authentication required.
    Templates contain no sensitive data, only instructions.

    Returns platform-appropriate templates:
    - claude_code: .md files for ~/.claude/commands/
    - codex_cli: SKILL.md files for ~/.codex/skills/

    Returns:
        Response with complete ZIP file download

    Example:
        curl http://localhost:7272/api/download/slash-commands.zip?platform=claude_code
    """
    logger.info("Generating slash commands ZIP (public download, platform=%s)", sanitize(platform))

    templates = get_all_templates(platform=platform)

    server_url = get_public_base_url(request)

    for name, template_file in (
        ("install.sh", "install_slash_commands.sh"),
        ("install.ps1", "install_slash_commands.ps1"),
    ):
        script_path = INSTALL_SCRIPT_TEMPLATES_DIR / template_file
        if not script_path.exists():
            logger.error("install script template missing: %s", script_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Install script {name} is missing from this installation",
            )
        templates[name] = render_install_script(script_path.read_text(encoding="utf-8"), server_url)

    zip_bytes = create_zip_archive(templates)

    logger.info(f"Slash commands ZIP generated: {len(templates)} files, {len(zip_bytes)} bytes")

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=slash-commands.zip", "Cache-Control": "no-store"},
    )


@router.get("/install-script.{extension}")
async def download_install_script(
    request: Request,
    extension: str,
    script_type: str = Query(..., description="Script type: slash-commands"),
):
    """
    Download cross-platform install script.

    This endpoint generates install scripts for Unix/macOS (.sh) or Windows (.ps1)
    that download and extract ZIP files. Scripts use $GILJO_API_KEY environment
    variable for authentication.

    Supported extensions:
    - .sh (Unix/macOS bash)
    - .ps1 (Windows PowerShell)

    Supported script types:
    - slash-commands

    **Public endpoint** - No authentication required.
    Install scripts are public utilities that download from public/optional-auth endpoints.

    Args:
        extension: Script extension (sh or ps1)
        script_type: The bundle the script installs. Only "slash-commands" is
            accepted; any other value returns 400.

    Returns:
        Response with script file download

    Raises:
        HTTPException: 400 if invalid extension or type
        HTTPException: 500 if template not found

    Example:
        curl http://localhost:7272/api/download/install-script.sh?script_type=slash-commands -o install.sh
    """
    if extension not in ["sh", "ps1"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid extension. Must be 'sh' or 'ps1'",
        )

    if script_type != "slash-commands":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid type. Must be 'slash-commands'",
        )

    logger.info("Generating install script (public): extension=%s, type=%s", sanitize(extension), sanitize(script_type))

    server_url = get_public_base_url(request)

    template_filename = f"install_{script_type.replace('-', '_')}.{extension}"
    template_path = INSTALL_SCRIPT_TEMPLATES_DIR / template_filename

    if not template_path.exists():
        logger.error(f"Install script template not found: {template_path}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Install script template not found. Please contact administrator.",
        )

    template_content = template_path.read_text(encoding="utf-8")
    script_content = render_install_script(template_content, server_url)

    media_type = "application/x-sh" if extension == "sh" else "application/x-powershell"

    logger.info(f"Install script generated successfully: {len(script_content)} bytes")

    return Response(
        content=script_content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=install.{extension}", "Cache-Control": "no-store"},
    )


@router.get("/bootstrap-prompt")
async def get_bootstrap_prompt(
    request: Request,
    platform: str = Query(
        ...,
        pattern=export_platform_pattern(),
        description="Target CLI platform: claude_code, codex_cli, opencode, or generic",
    ),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get a fully-rendered bootstrap prompt for the given platform.

    Returns a ready-to-paste prompt with a real one-time download URL
    already substituted into the template. This consolidates the
    template rendering that was previously duplicated across frontend
    and backend.

    **Authentication**: Required - JWT cookie or API key header

    Args:
        request: FastAPI request object
        platform: Target CLI platform (claude_code, codex_cli, opencode, generic)
        current_user: Authenticated user (injected via Depends)
        db: Database session

    Returns:
        {
            "prompt": "<ready-to-paste bootstrap text with download URL>",
            "expires_at": "2026-03-24T10:45:00Z",
            "platform": "claude_code"
        }

    Raises:
        HTTPException 401: Not authenticated
        HTTPException 500: Token generation or staging failed

    Example:
        curl http://localhost:7272/api/download/bootstrap-prompt?platform=claude_code \\
             -H "X-API-Key: $GILJO_API_KEY"
    """
    template = _BOOTSTRAP_TEMPLATES.get(platform)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "VALIDATION_ERROR",
                "field": "platform",
                "constraint": "must name a platform with a bootstrap prompt",
                "message": (
                    f"No bootstrap prompt exists for platform '{platform}'. "
                    f"Supported: {', '.join(sorted(_BOOTSTRAP_TEMPLATES))}."
                ),
            },
        )

    logger.info(
        "Generating bootstrap prompt for user: %s (tenant: %s, platform: %s)",
        sanitize(current_user.username),
        sanitize(current_user.tenant_key),
        sanitize(platform),
    )

    from giljo_mcp.downloads.token_manager import TokenManager
    from giljo_mcp.file_staging import FileStaging

    tenant_key = current_user.tenant_key
    token_manager = TokenManager(db_session=db)

    filename = "slash_commands.zip"
    token = await token_manager.generate_token(
        tenant_key=tenant_key,
        download_type="slash_commands",
        filename=filename,
    )

    staging = FileStaging(db_session=db)
    staging_path = await staging.create_staging_directory(tenant_key, token)
    zip_path, message = await staging.stage_slash_commands(staging_path, platform=platform)

    if not zip_path:
        await token_manager.mark_failed(token, message, tenant_key=tenant_key)
        logger.error("Failed to stage slash commands for bootstrap prompt: %s", sanitize(str(message)))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to stage download content"
        )

    await token_manager.mark_ready(token, tenant_key=tenant_key)

    server_url = get_public_base_url(request)
    download_url = f"{server_url}/api/download/temp/{token}/{filename}"

    if platform == EXPORT_CODEX_CLI:
        prompt = template.replace("{SKILLS_URL}", download_url)
    else:
        prompt = template.replace("{SLASH_COMMANDS_URL}", download_url)

    token_data = await token_manager.get_token_info(token, tenant_key)
    expires_at = token_data["expires_at"] if token_data else None

    logger.info(f"Bootstrap prompt generated: platform={sanitize(platform)}, token={mask_token(token)}")

    return {
        "prompt": prompt,
        "expires_at": expires_at,
        "platform": platform,
    }
