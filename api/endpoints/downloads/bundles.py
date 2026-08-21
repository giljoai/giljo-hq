# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Asset/bundle download endpoints: slash-command and agent-template ZIPs,
install scripts, and the rendered bootstrap prompt.

Extracted verbatim from api/endpoints/downloads.py (TSK-9209 / IMP-9169 §3.1
route-group split). Behavior is unchanged. ``create_zip_archive`` and
``render_install_script`` live here as the shared helpers used by these routes.

The ``installer/templates`` lookups walk to ``parents[3]`` -- one level FURTHER UP
than the former single-file module's ``parents[2]``, because this file sits one
level deeper (``endpoints/downloads/bundles.py`` vs ``endpoints/downloads.py``).
That extra level is what KEEPS the anchor on the repo root. ``parents[2]`` would
fail SILENTLY: the ``.exists()`` guards below simply fall through and install.sh /
install.ps1 vanish from the ZIPs without raising.
"""

import io
import logging
import zipfile
from datetime import UTC
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.http.url_resolver import get_public_base_url
from giljo_mcp.models import AgentTemplate, User
from giljo_mcp.platform_registry import (
    EXPORT_ANTIGRAVITY_CLI,
    EXPORT_CLAUDE_CODE,
    EXPORT_CODEX_CLI,
    EXPORT_GEMINI_CLI,
    EXPORT_GENERIC,
    VALID_EXPORT_PLATFORMS,
    export_platform_pattern,
)
from giljo_mcp.repositories.product_agent_selection import (
    active_product_template_ids,
    build_export_context,
    filter_templates_by_ids,
    record_product_export,
)
from giljo_mcp.tools.slash_command_templates import get_all_templates
from giljo_mcp.utils.log_sanitizer import mask_token, sanitize


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/download", tags=["downloads"])


# Helper Functions


def create_zip_archive(files: dict[str, str]) -> bytes:
    """
    Create ZIP archive from file dictionary.

    Args:
        files: {filename: content} mapping

    Returns:
        ZIP file bytes

    Example:
        >>> files = {"test.md": "# Content"}
        >>> zip_bytes = create_zip_archive(files)
        >>> len(zip_bytes) > 0
        True
    """
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
    """
    Render install script template with server URL.

    Args:
        template_content: Script template with {{SERVER_URL}} placeholder
        server_url: Server URL to substitute

    Returns:
        Rendered script content
    """
    return template_content.replace("{{SERVER_URL}}", server_url)


# API Endpoints


@router.get("/slash-commands.zip")
async def download_slash_commands(
    request: Request,
    platform: str = Query(
        default="claude_code",
        pattern=export_platform_pattern(),
        description="Target CLI platform: claude_code, gemini_cli, codex_cli, antigravity_cli, or generic",
    ),
):
    """
    Download slash command/skill templates as ZIP file.

    **Public endpoint** - No authentication required.
    Templates contain no sensitive data, only instructions.

    Returns platform-appropriate templates:
    - claude_code: .md files for ~/.claude/commands/
    - gemini_cli: .toml files for ~/.gemini/commands/
    - codex_cli: SKILL.md files for ~/.codex/skills/

    Returns:
        Response with complete ZIP file download

    Example:
        curl http://localhost:7272/api/download/slash-commands.zip?platform=claude_code
    """
    logger.info("Generating slash commands ZIP (public download, platform=%s)", sanitize(platform))

    # Get platform-specific slash command templates
    templates = get_all_templates(platform=platform)

    # Add install scripts with server URL rendered
    server_url = get_public_base_url(request)

    # Read install scripts from templates
    sh_script_path = Path(__file__).parents[3] / "installer" / "templates" / "install_slash_commands.sh"
    ps1_script_path = Path(__file__).parents[3] / "installer" / "templates" / "install_slash_commands.ps1"

    # Read and render scripts
    if sh_script_path.exists():
        with open(sh_script_path) as f:
            sh_content = render_install_script(f.read(), server_url)
            templates["install.sh"] = sh_content

    if ps1_script_path.exists():
        with open(ps1_script_path) as f:
            ps1_content = render_install_script(f.read(), server_url)
            templates["install.ps1"] = ps1_content

    # Create ZIP archive
    zip_bytes = create_zip_archive(templates)

    logger.info(f"Slash commands ZIP generated: {len(templates)} files, {len(zip_bytes)} bytes")

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=slash-commands.zip"},
    )


def _bundle_files(export_data: dict, platform: str) -> dict[str, str]:
    """The ZIP's agent entries for one platform.

    Codex ships a single structured JSON document; every other platform ships the
    pre-assembled per-agent files under the names the assembler chose (which, since
    BE-9385b, are product-qualified).
    """
    if platform == EXPORT_CODEX_CLI:
        import json

        return {"agents.json": json.dumps(export_data, indent=2)}
    return {agent["filename"]: agent["content"] for agent in export_data["agents"]}


def _attach_install_scripts(files: dict[str, str], server_url: str) -> None:
    """Add the shell/PowerShell installers, rendered against ``server_url``.

    Both are optional on disk: a deployment that ships without the installer
    templates still serves a valid agent bundle, so a missing script is skipped
    rather than raised.
    """
    templates_dir = Path(__file__).parents[3] / "installer" / "templates"
    for filename, template_name in (
        ("install.sh", "install_agent_templates.sh"),
        ("install.ps1", "install_agent_templates.ps1"),
    ):
        script_path = templates_dir / template_name
        if script_path.exists():
            files[filename] = render_install_script(script_path.read_text(), server_url)


async def _record_export(db, selected, tenant_key: str, export_context) -> None:
    """Stamp this export on the templates AND on the product that performed it.

    Handover 0335 wrote only the tenant-wide ``agent_templates.last_exported_at``.
    BE-9385e adds the per-product record in the SAME transaction, so the staleness
    indicator stops showing one product's export as every other product's.

    Extracted from ``download_agent_templates`` rather than inlined: that handler
    sat exactly at the 200-line function cap, so the per-product write had to leave
    the function rather than push it over. The house rule is extract, never raise.

    This is a relocation, not a new write: the module held exactly one direct
    commit before this change and holds exactly one after. The per-product write
    it wraps does NOT touch raw ORM -- it goes through ``record_product_export``,
    which routes to the junction's own repository.

    Args:
        db: Active database session (this function owns the commit).
        selected: The templates included in this export.
        tenant_key: Tenant key for isolation.
        export_context: The active product's export identity, or None.
    """
    from datetime import datetime

    export_timestamp = datetime.now(UTC)

    for template in selected:
        template.last_exported_at = export_timestamp

    await record_product_export(
        db,
        export_context.product_id if export_context else None,
        tenant_key,
        [t.id for t in selected],
        export_timestamp,
    )

    await db.commit()  # single-writer-allow: relocated by the 200-line cap; net endpoint writes 1 before, 1 after
    logger.info("Updated last_exported_at for %d templates (tenant: %s)", len(selected), sanitize(tenant_key))


@router.get("/agent-templates.zip")
async def download_agent_templates(
    request: Request,
    access_token: str | None = Cookie(None),
    x_api_key: str | None = Header(None),
    db: AsyncSession = Depends(get_db_session),
    active_only: bool = Query(default=True, description="Only include active templates"),
    platform: str = Query(default="claude_code", description="Target platform: claude_code, codex_cli, gemini_cli"),
):
    """
    Download agent templates as complete ZIP file (dynamic content from database).

    **Authentication**: Optional - supports JWT cookie (browser) or API key header (MCP tools).
    - If authenticated: Returns user's tenant-specific customized templates
    - If unauthenticated: Returns system default templates (no sensitive data)

    This endpoint generates a ZIP file containing:
    - All active agent template markdown files with YAML frontmatter
    - install.sh (Unix/macOS/Linux installer for product/personal)
    - install.ps1 (Windows PowerShell installer for product/personal)

    Each template file includes:
    - YAML frontmatter (name, description, tools, model)
    - Template content
    - Behavioral rules (if defined)
    - Success criteria (if defined)

    Args:
        request: FastAPI request
        access_token: Optional JWT cookie (browser session)
        x_api_key: Optional API key header (MCP tools)
        db: Database session
        active_only: Only include active templates (default: True)

    Returns:
        Response with complete ZIP file download

    Example:
        # Authenticated (with browser cookie or API key)
        curl -H "X-API-Key: $KEY" http://localhost:7272/api/download/agent-templates.zip -o templates.zip

        # Unauthenticated (system defaults)
        curl http://localhost:7272/api/download/agent-templates.zip -o templates.zip
    """
    # Try to authenticate (JWT cookie or API key)
    # NOTE: Use get_current_user_optional to avoid raising on unauthenticated access.
    current_user = None
    try:
        from giljo_mcp.auth.dependencies import get_current_user_optional

        authorization = request.headers.get("authorization")
        current_user = await get_current_user_optional(
            request,
            access_token,
            x_api_key,
            authorization,
            db,
        )
    except HTTPException:
        # Safety: get_current_user_optional should already swallow HTTPException,
        # but keep this block to avoid leaking auth errors.
        current_user = None

    # Determine template source
    if current_user:
        # Authenticated: Use tenant-specific templates
        logger.info(
            "Generating agent templates ZIP for user: %s (tenant: %s, active_only: %s)",
            sanitize(current_user.username),
            sanitize(current_user.tenant_key),
            sanitize(active_only),
        )

        # Query templates with multi-tenant isolation.
        # BE-9325: soft-delete leaves is_active alone -- deleted_at IS NULL is
        # required unconditionally (not just under active_only) or a trashed
        # template ships back onto the user's own disk.
        stmt = (
            select(AgentTemplate)
            .where(
                AgentTemplate.tenant_key == current_user.tenant_key,
                AgentTemplate.deleted_at.is_(None),
            )
            .order_by(AgentTemplate.name)
        )

        if active_only:
            stmt = stmt.where(AgentTemplate.is_active)

        result = await db.execute(stmt)
        # BE-9385a: follows the ACTIVE PRODUCT's junction (the anonymous branch
        # below stays product-blind -- no tenant, so no active product).
        ids = await active_product_template_ids(db, current_user.tenant_key)
        templates = filter_templates_by_ids(result.scalars().all(), ids)

        if not templates:
            logger.warning(
                "No templates found for tenant: %s (active_only: %s)",
                sanitize(current_user.tenant_key),
                sanitize(active_only),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No agent templates found. Please create templates first.",
            )
    else:
        # Unauthenticated: Use system default templates (tenant_key IS NULL)
        logger.info("Generating agent templates ZIP (unauthenticated - system defaults)")

        stmt = select(AgentTemplate).where(AgentTemplate.tenant_key.is_(None)).order_by(AgentTemplate.name)

        if active_only:
            stmt = stmt.where(AgentTemplate.is_active)

        # BE6004C-5: anonymous request reads the system-default templates
        # (tenant_key IS NULL) -- there is no tenant to scope to. The audited,
        # model-scoped bypass is the correct mechanism for this public read.
        with tenant_isolation_bypass(
            db,
            reason="public download: read system-default agent templates (tenant_key IS NULL)",
            models=(AgentTemplate,),
        ):
            result = await db.execute(stmt)
            templates = result.scalars().all()

        if not templates:
            # Fallback: Use hardcoded default template names if no system defaults exist
            logger.warning("No system default templates found in database")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No system default templates available. Please authenticate to access your custom templates.",
            )

    # Validate platform parameter
    valid_platforms = VALID_EXPORT_PLATFORMS
    if platform not in valid_platforms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform '{platform}'. Must be one of: {', '.join(sorted(valid_platforms))}",
        )

    # Build file dictionary using assembler for platform-aware rendering (Handover 0836a)
    from giljo_mcp.template_renderer import select_templates_for_packaging
    from giljo_mcp.tools.agent_template_assembler import AgentTemplateAssembler

    selected = select_templates_for_packaging(templates)

    # BE-9385b: the authenticated download is product-qualified and marked; the
    # anonymous system-default branch above stays bare -- it has no tenant and no
    # product, so a marker there would name an owner that does not exist.
    export_context = await build_export_context(db, current_user.tenant_key) if current_user else None

    assembler = AgentTemplateAssembler()
    export_data = assembler.assemble(selected, platform, export_context=export_context)

    files = _bundle_files(export_data, platform)
    _attach_install_scripts(files, get_public_base_url(request))

    # Create ZIP archive
    zip_bytes = create_zip_archive(files)

    # Handover 0335: Update last_exported_at and emit WebSocket event (authenticated users only)
    if current_user and selected:
        await _record_export(db, selected, current_user.tenant_key, export_context)

    user_info = f"user: {sanitize(current_user.username)}" if current_user else "public/unauthenticated"
    logger.info("Agent templates ZIP generated (%s): %d files, %d bytes", user_info, len(files), len(zip_bytes))

    if current_user:
        # IMP-0023: per-user skills-version stamping removed; system_settings drives drift state.
        try:
            ws_manager = request.app.state.websocket_manager
            if ws_manager:
                from giljo_mcp.events.schemas import EventFactory

                event = EventFactory.setup_agents_downloaded(
                    tenant_key=current_user.tenant_key,
                    user_id=str(current_user.id),
                    agent_count=len(selected),
                )
                await ws_manager.broadcast_event_to_tenant(tenant_key=current_user.tenant_key, event=event)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Setup agents_downloaded event emission failed (non-blocking): %s", sanitize(str(e)))

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=agent-templates.zip"},
    )


@router.get("/install-script.{extension}")
async def download_install_script(
    request: Request,
    extension: str,
    script_type: str = Query(..., description="Script type: slash-commands or agent-templates"),
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
    - agent-templates

    **Public endpoint** - No authentication required.
    Install scripts are public utilities that download from public/optional-auth endpoints.

    Args:
        extension: Script extension (sh or ps1)
        script_type: Type of script (slash-commands or agent-templates)

    Returns:
        Response with script file download

    Raises:
        HTTPException: 400 if invalid extension or type
        HTTPException: 500 if template not found

    Example:
        curl http://localhost:7272/api/download/install-script.sh?script_type=slash-commands -o install.sh
    """
    # Validate extension
    if extension not in ["sh", "ps1"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid extension. Must be 'sh' or 'ps1'",
        )

    # Validate script type
    if script_type not in ["slash-commands", "agent-templates"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid type. Must be 'slash-commands' or 'agent-templates'",
        )

    logger.info("Generating install script (public): extension=%s, type=%s", sanitize(extension), sanitize(script_type))

    # Get server URL
    server_url = get_public_base_url(request)

    # Get template path
    template_dir = Path(__file__).parents[3] / "installer" / "templates"
    template_filename = f"install_{script_type.replace('-', '_')}.{extension}"
    template_path = template_dir / template_filename

    # Check if template exists
    if not template_path.exists():
        logger.error(f"Install script template not found: {template_path}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Install script template not found. Please contact administrator.",
        )

    # Read and render template
    template_content = template_path.read_text(encoding="utf-8")
    script_content = render_install_script(template_content, server_url)

    # Determine media type
    media_type = "application/x-sh" if extension == "sh" else "application/x-powershell"

    logger.info(f"Install script generated successfully: {len(script_content)} bytes")

    return Response(
        content=script_content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=install.{extension}"},
    )


@router.get("/bootstrap-prompt")
async def get_bootstrap_prompt(
    request: Request,
    platform: str = Query(
        ...,
        pattern=export_platform_pattern(),
        description="Target CLI platform: claude_code, gemini_cli, codex_cli, antigravity_cli, or generic",
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
        platform: Target CLI platform (claude_code, gemini_cli, codex_cli)
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
    from giljo_mcp.tools.slash_command_templates import (
        BOOTSTRAP_ANTIGRAVITY_CLI,
        BOOTSTRAP_CLAUDE_CODE,
        BOOTSTRAP_CODEX_CLI,
        BOOTSTRAP_GEMINI_CLI,
        BOOTSTRAP_GENERIC,
    )

    bootstrap_templates = {
        EXPORT_CLAUDE_CODE: BOOTSTRAP_CLAUDE_CODE,
        EXPORT_GEMINI_CLI: BOOTSTRAP_GEMINI_CLI,
        EXPORT_CODEX_CLI: BOOTSTRAP_CODEX_CLI,
        EXPORT_ANTIGRAVITY_CLI: BOOTSTRAP_ANTIGRAVITY_CLI,
        EXPORT_GENERIC: BOOTSTRAP_GENERIC,
    }

    logger.info(
        "Generating bootstrap prompt for user: %s (tenant: %s, platform: %s)",
        sanitize(current_user.username),
        sanitize(current_user.tenant_key),
        sanitize(platform),
    )

    # Generate token and stage slash_commands ZIP (reuse generate-token logic)
    from giljo_mcp.downloads.token_manager import TokenManager
    from giljo_mcp.file_staging import FileStaging

    tenant_key = current_user.tenant_key
    token_manager = TokenManager(db_session=db)

    # 1) Generate token
    filename = "slash_commands.zip"
    token = await token_manager.generate_token(
        tenant_key=tenant_key,
        download_type="slash_commands",
        filename=filename,
    )

    # 2) Stage slash commands ZIP
    staging = FileStaging(db_session=db)
    staging_path = await staging.create_staging_directory(tenant_key, token)
    zip_path, message = await staging.stage_slash_commands(staging_path, platform=platform)

    if not zip_path:
        await token_manager.mark_failed(token, message)
        logger.error("Failed to stage slash commands for bootstrap prompt: %s", sanitize(str(message)))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message)

    # 3) Mark ready
    await token_manager.mark_ready(token)

    # 4) Build download URL
    server_url = get_public_base_url(request)
    download_url = f"{server_url}/api/download/temp/{token}/{filename}"

    # 5) Render the template with the download URL
    template = bootstrap_templates[platform]
    if platform == EXPORT_CODEX_CLI:
        prompt = template.replace("{SKILLS_URL}", download_url)
    else:
        prompt = template.replace("{SLASH_COMMANDS_URL}", download_url)

    # 6) Get expiry info
    token_data = await token_manager.get_token_info(token, tenant_key)
    expires_at = token_data["expires_at"] if token_data else None

    logger.info(f"Bootstrap prompt generated: platform={sanitize(platform)}, token={mask_token(token)}")

    return {
        "prompt": prompt,
        "expires_at": expires_at,
        "platform": platform,
    }
