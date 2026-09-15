# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
from giljo_mcp.services.template_service import TemplateService
from giljo_mcp.template_renderer import hex_to_claude_color
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_template_service
from .models import TemplatePreviewRequest, TemplatePreviewResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{template_id}/preview/", response_model=TemplatePreviewResponse)
async def preview_template(
    template_id: str,
    request: TemplatePreviewRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplatePreviewResponse:
    """
    Preview template with variable substitutions.

    For Claude (cli_tool='claude'): returns YAML-style preview with frontmatter.
    For Codex/generic: returns plaintext/markdown preview.

    Migrated to TemplateService - Handover 1011 Phase 2.
    """
    logger.info("User %s previewing template %s", sanitize(current_user.username), sanitize(template_id))

    template = await template_service.get_template_by_id(session, template_id, current_user.tenant_key)

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    cli_tool = template.cli_tool or "claude"
    name = template.name
    description = template.description or ""
    model = template.model or "sonnet"
    system_text = template.system_instructions or ""
    user_text = template.user_instructions or ""

    variables = request.variables or {}

    def apply_vars(text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            return variables.get(key, match.group(0))

        return re.sub(r"\{(\w+)\}", repl, text)

    system_rendered = apply_vars(system_text)
    user_rendered = apply_vars(user_text)

    variables_used = re.findall(r"\{(\w+)\}", system_text + user_text)

    if cli_tool == "claude":
        lines = [
            "---",
            f"name: {name}",
            f"description: {description}",
            f"model: {model}",
        ]
        claude_color = hex_to_claude_color(getattr(template, "background_color", None))
        if claude_color:
            lines.append(f"color: {claude_color}")
        lines.append("---")
        lines.extend(
            [
                "",
                "## System Instructions",
                system_rendered,
            ]
        )
        if user_rendered:
            lines.extend(
                [
                    "",
                    "## User Instructions",
                    user_rendered,
                ]
            )
        if template.behavioral_rules:
            lines.extend(["", "## Behavioral Rules", *template.behavioral_rules])
        if template.success_criteria:
            lines.extend(["", "## Success Criteria", *template.success_criteria])
        preview_text = "\n".join(lines)
    else:
        header = f"# {name}"
        body_lines = [header, "", system_rendered]
        if user_rendered:
            body_lines.extend(["", user_rendered])
        preview_text = "\n".join(body_lines)

    return TemplatePreviewResponse(
        template_id=str(template.id),
        cli_tool=cli_tool,
        preview=preview_text,
        variables_used=list(set(variables_used)),
    )
