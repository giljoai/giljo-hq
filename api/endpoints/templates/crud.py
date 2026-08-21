# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Template CRUD Endpoints - Handover 0126

Handles template CRUD operations using TemplateService.

BE-8000j: the create/update write paths now route fully through the owning
service (``TemplateService.create_template_from_request`` /
``update_template_from_request``) — all validation, materialization, and the DB
write live there. These endpoints stay thin: request in, service call, translate
the service's domain exceptions to their existing HTTP status codes, and (for
update) fire the real-time WebSocket event.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.exceptions import AuthorizationError, ProjectStateError, TemplateNotFoundError, ValidationError
from giljo_mcp.models import AgentTemplate, User
from giljo_mcp.models.templates import effective_last_exported_at
from giljo_mcp.repositories.product_agent_selection import active_product_export_timestamps
from giljo_mcp.services.template_service import USER_MANAGED_AGENT_LIMIT, TemplateService
from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_template_service
from .models import TemplateCreate, TemplateResponse, TemplateUpdate


logger = logging.getLogger(__name__)

router = APIRouter()


def _is_system_managed_role(role: str | None) -> bool:
    """Check if role is system-managed"""
    return bool(role and role in SYSTEM_MANAGED_ROLES)


def _convert_to_response(template: AgentTemplate, product_export_times: dict | None = None) -> TemplateResponse:
    """Convert ORM model to response schema.

    BE-9385e: ``product_export_times`` carries the ACTIVE product's own export
    times, keyed by template id. Passing it is what makes the "last exported"
    fields describe the product the user is actually in; omitting it keeps the
    tenant-wide answer, which is still correct where no product is in context.

    Args:
        template: The ORM template.
        product_export_times: The active product's export times by template id
            (see :func:`effective_last_exported_at`), or None for no product
            context.
    """
    # Merge system and user instructions for backward compatibility
    merged_content = template.system_instructions or ""
    if template.user_instructions:
        merged_content = f"{merged_content}\n\n{template.user_instructions}"

    last_exported_at = effective_last_exported_at(template, product_export_times)
    may_be_stale = template.may_be_stale_against(last_exported_at)

    return TemplateResponse(
        id=template.id,
        tenant_key=template.tenant_key,
        product_id=template.product_id,
        name=template.name,
        role=template.role,
        cli_tool=template.cli_tool or "claude",
        background_color=template.background_color,
        description=template.description,
        system_instructions=template.system_instructions or "",
        user_instructions=template.user_instructions,
        model=template.model,
        tools=template.tools,
        behavioral_rules=template.behavioral_rules or [],
        success_criteria=template.success_criteria or [],
        tags=template.tags or [],
        is_default=template.is_default,
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
        # Handover 0335: Export tracking fields
        last_exported_at=last_exported_at,
        may_be_stale=may_be_stale,
        user_managed_export=template.user_managed_export or False,
        category=template.category,
        variables=template.variables or [],
        version=template.version or "1.0.0",
        avg_generation_ms=template.avg_generation_ms,
        created_by=template.created_by,
        is_system_role=_is_system_managed_role(template.role),
    )


async def _convert_in_product_context(
    session: AsyncSession, tenant_key: str, template: AgentTemplate
) -> TemplateResponse:
    """Convert one template, with the active product's export time applied (BE-9385e).

    Single-template responses go through here so a row the user just edited does
    not come back carrying another product's export time and re-displaying the
    lie the list view no longer tells.
    """
    export_times = await active_product_export_timestamps(session, tenant_key)
    return _convert_to_response(template, export_times)


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """
    Get template by ID for the current tenant.

    Migrated to TemplateService - Handover 1011 Phase 2.
    """
    logger.debug("User %s getting template %s", sanitize(current_user.username), sanitize(template_id))

    template = await template_service.get_template_by_id(session, template_id, current_user.tenant_key)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    return await _convert_in_product_context(session, current_user.tenant_key, template)


@router.get("/", response_model=list[TemplateResponse])
async def list_templates(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
    role: str | None = Query(None, description="Filter by role"),
    is_active: bool | None = Query(None, description="Filter by active status"),
) -> list[TemplateResponse]:
    """
    List templates for the current tenant with optional filters.
    """
    templates = await template_service.list_templates_with_filters(
        session, current_user.tenant_key, role=role, is_active=is_active
    )

    # BE-9385e: resolved ONCE for the whole list, not per row.
    export_times = await active_product_export_timestamps(session, current_user.tenant_key)

    return [_convert_to_response(t, export_times) for t in templates]


@router.post("/", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    template: TemplateCreate,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """
    Create a new template.

    Routes through ``TemplateService.create_template_from_request`` (BE-8000j) —
    the owning service performs all validation, materialization, and the write.
    This endpoint only translates the service's domain exceptions into their HTTP
    status codes: ``ValidationError`` -> 400, and (BE-9394) ``ProjectStateError`` ->
    409 when a born-active template would exceed the active-slot cap. The update
    endpoint has always translated that same rejection to 409; without this arm the
    create-side refusal would surface as an unhandled 500.
    """
    try:
        new_template = await template_service.create_template_from_request(
            session,
            template,
            current_user.tenant_key,
            current_user.username,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ProjectStateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc

    return await _convert_in_product_context(session, current_user.tenant_key, new_template)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: str,
    updates: TemplateUpdate,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """
    Update an existing template.

    Routes through ``TemplateService.update_template_from_request`` (BE-8000j) —
    the owning service performs the guards, archive, active-limit check, and write.
    This endpoint translates the service's domain exceptions to their existing HTTP
    status codes and fires the (unchanged) real-time WebSocket event.
    """
    tenant_key = current_user.tenant_key

    try:
        template, updated_fields = await template_service.update_template_from_request(
            session,
            template_id,
            updates,
            tenant_key,
            current_user.username,
        )
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Template not found") from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    except ProjectStateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc

    logger.info("Updated template %s", sanitize(template_id))

    response = await _convert_in_product_context(session, tenant_key, template)

    # Broadcast template update via EventBus for real-time UI refresh
    try:
        from api.app_state import state

        if getattr(state, "event_bus", None):
            await state.event_bus.publish(
                "template:updated",
                {
                    "tenant_key": tenant_key,
                    "template_id": template.id,
                    "is_active": template.is_active,
                    # BE-9385e: the PRODUCT-AWARE value the response carries, not the
                    # tenant-wide property. The UI updates the row's staleness badge
                    # from this event, so broadcasting the tenant-wide answer here
                    # would flip the badge straight back to another product's export
                    # the moment the user edits an agent.
                    "may_be_stale": response.may_be_stale,
                    "updated_fields": updated_fields,
                },
            )
    except Exception as pub_err:  # noqa: BLE001 - fire-and-forget WS event
        logger.warning("Failed to publish template update event: %s", sanitize(str(pub_err)))

    return response


@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> dict:
    """Soft-delete (trash) a template — BE-6137.

    Stamps ``deleted_at`` so the template drops out of every live read.
    ``POST /{template_id}/restore`` restores it within 30 days.

    Guards preserved from the former hard-delete:
    - 404 if not found for this tenant
    - 403 if the role is system-managed

    ``hard_delete_template`` is retained for the future permanent-purge path
    (TSK-6132). It is no longer called from this default delete route.
    """
    try:
        tenant_key = current_user.tenant_key

        template = await template_service.get_template_by_id(session, template_id, tenant_key)

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        if _is_system_managed_role(template.role):
            raise HTTPException(status_code=403, detail="Cannot delete system-managed templates")

        template_name = template.name

        deleted = await template_service.delete_template(session, template_id, tenant_key)

        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete template")

        logger.info("Soft-deleted template %s (%s)", sanitize(template_id), sanitize(template_name))

        return {"message": f"Template '{template_name}' moved to trash", "template_id": template_id}

    except HTTPException:
        raise  # Re-raise HTTP exceptions (403, 404, 500, etc.) without modification
    except Exception as e:  # Broad catch: API boundary, converts to HTTP error
        logger.exception("Failed to delete template")
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete template. Check server logs.") from e


@router.post("/{template_id}/restore", response_model=TemplateResponse)
async def recover_template(
    template_id: str,
    current_user: User = Depends(get_current_active_user),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """Restore a soft-deleted (trashed) template within the 30-day window — BE-6137.

    Clears ``deleted_at`` so the template re-enters every live read. Archives
    survive and re-surface automatically.

    Raises:
        HTTPException 400: Recovery window expired (>30 days since deletion)
        HTTPException 404: No trashed template matched the id for this tenant
    """
    from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError

    try:
        tenant_key = current_user.tenant_key
        template = await template_service.restore_template(template_id, tenant_key)
        logger.info("Recovered template %s by user %s", sanitize(template_id), sanitize(current_user.username))
        return _convert_to_response(template)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found in trash") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to recover template %s", sanitize(template_id))
        raise HTTPException(status_code=500, detail="Failed to recover template. Check server logs.") from exc


@router.post("/import-defaults", response_model=dict)
async def import_default_agent_templates(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Import the seeded default agent templates — additive only (FE-9203).

    Delegates to ``giljo_mcp.template_import.import_default_templates`` (the
    seeder-content sibling module routing writes through the owning
    ``TemplateService``). Existing templates are NEVER modified: a free default
    name is created as seeded, a pristine copy already present is skipped, and
    a user-edited default name gets the pristine copy added under the existing
    suffix machinery (e.g. ``implementer-duplicate``). Takes no request body.
    """
    from giljo_mcp.template_import import import_default_templates

    try:
        report = await import_default_templates(session, current_user.tenant_key)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    logger.info(
        "User %s imported default templates: %d added, %d duplicate, %d skipped",
        sanitize(current_user.username),
        len(report.added),
        len(report.added_as_duplicate),
        len(report.skipped_identical),
    )
    return {
        "added": report.added,
        "added_as_duplicate": report.added_as_duplicate,
        "skipped_identical": report.skipped_identical,
    }


@router.get("/stats/active-count", response_model=dict)
async def get_active_count(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> dict:
    """
    Get count of active user-managed templates for the current tenant.
    """
    count = await template_service.get_active_user_managed_count(session, current_user.tenant_key)

    return {
        "active_count": count,
        "limit": USER_MANAGED_AGENT_LIMIT,
        "available": max(0, USER_MANAGED_AGENT_LIMIT - count),
        # max_slots = total active slots (user-managed limit + 1 reserved
        # orchestrator). The "N / max_slots" home badge reads this so it always
        # tracks the server-enforced cap instead of a hardcoded frontend default.
        "max_slots": USER_MANAGED_AGENT_LIMIT + 1,
    }
