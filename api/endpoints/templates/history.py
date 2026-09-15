# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
from giljo_mcp.services.template_service import TemplateService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_template_service
from .models import TemplateHistoryResponse, TemplateResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{template_id}/history", response_model=list[TemplateHistoryResponse])
async def get_template_history(
    template_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> list[TemplateHistoryResponse]:
    """
    Get template version history.

    Migrated to TemplateService - Handover 1011 Phase 2.
    """
    logger.info("User %s requesting history for template %s", sanitize(current_user.username), sanitize(template_id))

    template = await template_service.get_template_by_id(session, template_id, current_user.tenant_key)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    archives = await template_service.get_template_history(session, template_id, current_user.tenant_key)

    return [
        TemplateHistoryResponse(
            id=archive.id,
            template_id=archive.template_id,
            name=archive.name,
            version=archive.version,
            system_instructions=archive.system_instructions,
            user_instructions=archive.user_instructions,
            archive_reason=archive.archive_reason,
            archive_type=archive.archive_type,
            archived_by=archive.archived_by,
            archived_at=archive.archived_at,
            is_restorable=archive.is_restorable,
            usage_count_at_archive=archive.usage_count_at_archive,
            avg_generation_ms_at_archive=archive.avg_generation_ms_at_archive,
        )
        for archive in archives
    ]


@router.post("/{template_id}/restore/{archive_id}", response_model=TemplateResponse)
async def restore_template(
    template_id: str,
    archive_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """
    Restore template from archive.

    Migrated to TemplateService - Handover 1011 Phase 2.
    """
    logger.info(
        "User %s restoring template %s from archive %s",
        sanitize(current_user.username),
        sanitize(template_id),
        sanitize(archive_id),
    )

    archive = await template_service.get_archive_by_id(session, archive_id, template_id, current_user.tenant_key)
    if not archive:
        raise HTTPException(status_code=404, detail="Archive entry not found")

    template = await template_service.get_template_by_id(session, template_id, current_user.tenant_key)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    await template_service.create_template_archive(
        session,
        template,
        archive_reason="Replaced by restoration",
        archive_type="auto",
        archived_by=current_user.username,
    )

    await template_service.restore_template_from_archive(session, template, archive, restored_by=current_user.username)

    await template_service.commit_and_refresh_template(session, template)

    from .crud import _convert_to_response

    return _convert_to_response(template)


@router.post("/{template_id}/reset", response_model=TemplateResponse)
async def reset_template(
    template_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """
    Reset template to default state.

    Migrated to TemplateService - Handover 1011 Phase 2.
    """
    logger.info("User %s resetting template %s", sanitize(current_user.username), sanitize(template_id))

    template = await template_service.get_template_by_id(session, template_id, current_user.tenant_key)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    await template_service.create_template_archive(
        session, template, archive_reason="Reset template", archive_type="auto", archived_by=current_user.username
    )

    await template_service.reset_template_to_defaults(session, template)

    await template_service.commit_and_refresh_template(session, template)

    from .crud import _convert_to_response

    return _convert_to_response(template)


@router.post("/{template_id}/reset-system", response_model=TemplateResponse)
async def reset_system_instructions(
    template_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """
    Reset system instructions to default.

    Migrated to TemplateService - Handover 1011 Phase 2.
    """
    logger.info(
        "User %s resetting system instructions for template %s", sanitize(current_user.username), sanitize(template_id)
    )

    template = await template_service.get_template_by_id(session, template_id, current_user.tenant_key)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    await template_service.create_template_archive(
        session,
        template,
        archive_reason="Reset system instructions",
        archive_type="auto",
        archived_by=current_user.username,
    )

    await template_service.reset_system_instructions(session, template)

    await template_service.commit_and_refresh_template(session, template)

    from .crud import _convert_to_response

    return _convert_to_response(template)
