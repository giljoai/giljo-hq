# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.endpoints._boundary_types import ID_MAX, IdPath
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.exceptions import AuthorizationError, ProjectStateError, TemplateNotFoundError, ValidationError
from giljo_mcp.models import AgentTemplate, User
from giljo_mcp.services.template_service import USER_MANAGED_AGENT_LIMIT, TemplateService, factory_default_for
from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_template_service
from .models import TemplateCreate, TemplateResponse, TemplateUpdate


logger = logging.getLogger(__name__)

router = APIRouter()


def _is_system_managed_role(role: str | None) -> bool:
    return bool(role and role in SYSTEM_MANAGED_ROLES)


def _convert_to_response(template: AgentTemplate) -> TemplateResponse:
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
        model=template.model or "inherit",
        effort=template.effort or "inherit",
        tools=template.tools,
        behavioral_rules=template.behavioral_rules or [],
        success_criteria=template.success_criteria or [],
        tags=template.tags or [],
        is_default=template.is_default,
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
        category=template.category,
        variables=template.variables or [],
        version=template.version or "1.0.0",
        avg_generation_ms=template.avg_generation_ms,
        created_by=template.created_by,
        is_system_role=_is_system_managed_role(template.role),
        can_reset=factory_default_for(template) is not None,
    )


@router.get("/{template_id}/profile.md", response_class=Response)
async def download_template_profile(
    template_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> Response:
    """
    Download one agent's profile as a plain Markdown file.

    The document carries the agent's name, description, model / effort hints and
    profile instructions -- the same profile a spawned agent receives from
    ``get_job_mission`` -- with no harness-specific formatting, so you can hand it
    to any coding agent yourself. Returned as an attachment.
    """
    from giljo_mcp.services.mission_assembly import compose_agent_profile
    from giljo_mcp.template_renderer import profile_markdown_filename, render_profile_markdown

    template = await template_service.get_template_by_id(session, template_id, current_user.tenant_key)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    body = render_profile_markdown(compose_agent_profile(template))
    filename = profile_markdown_filename(template.name)
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """
    Get template by ID for the current tenant.

    """
    logger.debug("User %s getting template %s", sanitize(current_user.username), sanitize(template_id))

    template = await template_service.get_template_by_id(session, template_id, current_user.tenant_key)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    return _convert_to_response(template)


@router.get("/", response_model=list[TemplateResponse])
async def list_templates(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
    role: str | None = Query(None, max_length=ID_MAX, description="Filter by role"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    product_id: str | None = Query(None, max_length=ID_MAX, description="Show only the agents this product owns"),
) -> list[TemplateResponse]:
    """
    List agents for the current tenant.

    Pass ``product_id`` to list the agents that product owns -- the normal case,
    since each product has its own agents. Omit it to list every agent on the
    account.
    """
    templates = await template_service.list_templates_with_filters(
        session, current_user.tenant_key, role=role, is_active=is_active, product_id=product_id
    )

    return [_convert_to_response(t) for t in templates]


@router.post("/", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    template: TemplateCreate,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """
    Create a new template.

    Routes through ``TemplateService.create_template_from_request`` —
    the owning service performs all validation, materialization, and the write.
    This endpoint only translates the service's domain exceptions into their HTTP
    status codes: ``ValidationError`` -> 400, and ``ProjectStateError`` ->
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

    return _convert_to_response(new_template)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: IdPath,
    updates: TemplateUpdate,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """
    Update an existing template.

    Routes through ``TemplateService.update_template_from_request`` —
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

    response = _convert_to_response(template)

    try:
        from api.app_state import state

        if getattr(state, "event_bus", None):
            await state.event_bus.publish(
                "template:updated",
                {
                    "tenant_key": tenant_key,
                    "template_id": template.id,
                    "is_active": template.is_active,
                    "updated_fields": updated_fields,
                },
            )
    except Exception as pub_err:  # noqa: BLE001 - fire-and-forget WS event
        logger.warning("Failed to publish template update event: %s", sanitize(str(pub_err)))

    return response


@router.delete("/{template_id}")
async def delete_template(
    template_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> dict:
    """Soft-delete (trash) a template.

    Stamps ``deleted_at`` so the template drops out of every live read.
    ``POST /{template_id}/restore`` restores it within 30 days.

    Guards preserved from the former hard-delete:
    - 404 if not found for this tenant
    - 403 if the role is system-managed
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
        raise
    except Exception as e:
        logger.exception("Failed to delete template")
        await session.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete template. Check server logs.") from e


@router.post("/{template_id}/restore", response_model=TemplateResponse)
async def recover_template(
    template_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    template_service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    """Restore a soft-deleted (trashed) template within the 30-day window.

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
    product_id: str = Query(..., max_length=ID_MAX, description="Product that will own the imported agents"),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Add the default agents to a product — additive only.

    Agents belong to a product, so this names the product that will own them.
    Existing agents are NEVER modified: a free default name is created as seeded,
    a pristine copy this product already has is skipped, and a name taken
    elsewhere on the account gets the pristine copy added under a suffix (e.g.
    ``implementer-duplicate``). Imported agents arrive switched on.
    """
    from giljo_mcp.template_import import import_default_templates

    try:
        report = await import_default_templates(session, current_user.tenant_key, product_id)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    logger.info(
        "User %s imported default agents into product %s: %d added, %d duplicate, %d skipped",
        sanitize(current_user.username),
        sanitize(product_id),
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
    product_id: str = Query(..., max_length=ID_MAX, description="Product whose roster is being measured"),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    template_service: TemplateService = Depends(get_template_service),
) -> dict:
    """
    How many of this product's agent-role slots are in use.

    Per product, because the budget exists so one orchestrator's roster
    fits one context window, and a roster is assembled for one product. Counts
    distinct ROLES -- three copies of the same role share one slot, which is what
    the cap has always enforced.
    """
    count = await template_service.get_enabled_role_count(session, current_user.tenant_key, product_id)

    return {
        "active_count": count,
        "limit": USER_MANAGED_AGENT_LIMIT,
        "available": max(0, USER_MANAGED_AGENT_LIMIT - count),
        "max_slots": USER_MANAGED_AGENT_LIMIT + 1,
    }
