# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The owning-service write paths for agent templates -- create and update (BE-9394).

Owns ONE question end to end: given a validated create/update request, what does the
persisted template become? That covers name generation and collision suffixing, the
canonical MCP bootstrap injection, the field allowlist apply, the active-slot gate,
and the junction join a tenant-active template earns -- all of which are steps of a
single write rather than separate concerns that merely run nearby.

Lives outside ``template_service.py`` for the reason ``orchestrator_product_resolver``
and ``conductor_staging_builder`` were extracted before it -- that module sat at its
shrink-only line budget plus the full tolerance band, so the next added line reddened
CI and the write paths had to leave the file rather than move within it. The entry
points take the calling service and its session, the shape
``_resolve_product_id(service, ...)`` already established, so this module constructs
no service wiring of its own and holds no state.

``TemplateService.create_template_from_request`` / ``update_template_from_request``
remain as thin delegators, so every caller and every existing test keeps calling the
same service methods it always did.

Edition Scope: Both.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import (
    AuthorizationError,
    ProjectStateError,
    TemplateNotFoundError,
    ValidationError,
)
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.product_agent_assignment_service import ProductAgentAssignmentService
from giljo_mcp.template_validation import get_role_color, slugify_name
from giljo_mcp.utils.log_sanitizer import sanitize


async def create_from_request(
    service: Any,
    session: AsyncSession,
    data,
    tenant_key: str,
    created_by: str | None = None,
) -> AgentTemplate:
    """Create a template from a validated create request (owning-service write path).

    BE-8000j: this owns the FULL create materialization the REST endpoint
    previously performed inline -- name generation + collision suffixing,
    canonical MCP bootstrap injection (system_instructions is always the
    canonical bootstrap, never the caller-supplied value), background-color /
    description defaults, ``{var}`` extraction from user_instructions, and
    ``is_default`` sibling clearing -- then delegates the commit to
    :meth:`TemplateService.add_and_commit_template`. The endpoint stays thin and
    only translates the raised domain exceptions into their HTTP status codes.

    Args:
        service: The calling TemplateService -- the resolver shape established by
            ``_resolve_product_id(service, ...)``, so this module reads the
            repository, session factory and logger it needs without a
            nine-argument call.
        session: Caller-owned DB session (transaction boundary owned by caller).
        data: A ``TemplateCreate``-shaped request object (attribute access:
            ``name``/``role``/``cli_tool``/``custom_suffix``/``background_color``/
            ``description``/``user_instructions``/``model``/``behavioral_rules``/
            ``success_criteria``/``tags``/``is_default``/``is_active``/``category``).
            Duck-typed on purpose so the service does not import the API layer.
        tenant_key: Tenant key for isolation (REQUIRED).
        created_by: Username stamped as the template author.

    Returns:
        The persisted (flushed + refreshed) AgentTemplate.

    Raises:
        ValidationError: Name shape invalid, name too long, or suffix exhaustion.
        ProjectStateError: active-slot limit exceeded by a born-active template (HTTP 409).
    """
    from giljo_mcp.template_seeder import _get_mcp_bootstrap_section

    # Generate name from role + suffix (always slugify for safety)
    raw_name = data.name or data.role or ""
    generated_name = slugify_name(data.role or raw_name, data.custom_suffix)

    if not generated_name or not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", generated_name):
        raise ValidationError(message="Name must use lowercase letters, numbers, and hyphens only")
    if len(generated_name) > 100:
        raise ValidationError(message="Name must be 100 characters or less")

    # Auto-suffix if name already taken for this tenant
    base_name = generated_name
    counter = 2
    while await service.check_template_name_exists(session, tenant_key, generated_name):
        generated_name = f"{base_name}-{counter}"
        counter += 1
        if counter > 20:
            raise ValidationError(message=f"Too many agents named '{base_name}' — use a custom suffix")

    # Inject canonical MCP bootstrap -- ignore whatever the frontend sends
    canonical_bootstrap = _get_mcp_bootstrap_section()

    # Auto-assign background color
    background_color = data.background_color or get_role_color(data.role)

    # Set default description when missing
    description = data.description
    if not description:
        if data.cli_tool == "claude":
            description = f"Subagent for {data.role}"
        else:
            # Generic fallback for non-Claude templates
            description = f"{data.role} agent template" if data.role else "Agent template"

    # Extract variables from user_instructions (if any)
    variables = re.findall(r"\{(\w+)\}", data.user_instructions or "")

    new_template_id = str(uuid4())

    # BE-9394: a template born tenant-ACTIVE consumes a slot, so it passes the same
    # gate the update path uses. Until BE-9391 every template was born INACTIVE, so
    # the only route to "active" ran through update_from_request and its check --
    # that side effect was the sole thing enforcing the cap, and making creation
    # activate turned it into a bypass. Same validator, same error contract
    # (ProjectStateError -> HTTP 409). The not-yet-persisted id excludes nothing from
    # the count, which is exactly right for a create; test_be9211_active_slot_limit
    # already pins that shape with a candidate id of its own.
    if data.is_active and not service._is_system_managed_role(data.role):
        is_valid, error_msg = await service.validate_active_agent_limit(
            session=session,
            tenant_key=tenant_key,
            template_id=new_template_id,
            new_is_active=True,
            role=data.role,
        )
        if not is_valid:
            raise ProjectStateError(message=error_msg)

    if data.is_default and data.role:
        existing_defaults = await service.get_default_templates_by_role(session, tenant_key, data.role)
        for existing in existing_defaults:
            existing.is_default = False

    new_template = AgentTemplate(
        id=new_template_id,
        tenant_key=tenant_key,
        name=generated_name,
        category=data.category or "role",
        role=data.role,
        cli_tool=data.cli_tool,
        background_color=background_color,
        description=description,
        system_instructions=canonical_bootstrap,
        user_instructions=data.user_instructions or "",
        model=data.model or "sonnet",
        tools=None,
        variables=variables,
        behavioral_rules=data.behavioral_rules or [],
        success_criteria=data.success_criteria or [],
        version="1.0.0",
        is_active=data.is_active,
        is_default=data.is_default,
        tags=data.tags or [],
        tool=data.cli_tool,
        created_by=created_by,
    )

    await service.add_and_commit_template(session, new_template)

    # BE-9400: creation makes the agent AVAILABLE, never ACTIVE-HERE. The tenant
    # flag the caller sent stays as-is ("Available in all products" is ON at birth,
    # so the agent is visible and editable); what changes is that it arrives
    # switched OFF in the current product, because activation is an explicit user
    # act. Both switches off would make it invisible twice over -- BE-9391's defect.
    # Still gated on the tenant flag (BE-9391): a template born tenant-INACTIVE gets
    # no row at all, so the tenant-wide switch-on in ``update_from_request`` remains
    # what places it -- unchanged, and BE-9391's create-then-activate flow with it.
    if new_template.is_active:
        svc = ProductAgentAssignmentService(service.db_manager, tenant_key, test_session=service._session)
        await svc.place_in_active_product_switched_off(session, new_template.id, new_template.name)

    service._logger.info("Created template %s for tenant %s", new_template.id, tenant_key)

    return new_template


async def update_from_request(
    service: Any,
    session: AsyncSession,
    template_id: str,
    updates,
    tenant_key: str,
    username: str | None = None,
) -> tuple[AgentTemplate, list[str]]:
    """Update a template from a validated update request (owning-service write path).

    BE-8000j: owns the FULL update logic the REST endpoint previously ran
    inline -- the system-managed guard, the read-only ``system_instructions``
    guard, archive-on-user_instructions-change, the 16-slot active-limit
    check, the metadata-only ``updated_at`` preservation, the field-allowlist
    apply, legacy ``tool``/``cli_tool`` mirroring, and role->background-color.
    The endpoint stays thin and translates the raised domain exceptions to
    their existing HTTP status codes.

    Args:
        service: The calling TemplateService (see :func:`create_from_request`).
        session: Caller-owned DB session.
        template_id: Template UUID.
        updates: A ``TemplateUpdate``-shaped request object exposing
            ``model_dump(exclude_unset=True)`` (duck-typed; the service does
            not import the API layer).
        tenant_key: Tenant key for isolation (REQUIRED).
        username: Username stamped on the auto-archive.

    Returns:
        ``(template, updated_fields)`` -- the refreshed template and the list of
        request field names applied (for the caller's WebSocket event payload).

    Raises:
        TemplateNotFoundError: No live template with this id for the tenant (HTTP 404).
        AuthorizationError: System-managed template, or system_instructions write (HTTP 403).
        ProjectStateError: active-slot limit exceeded (HTTP 409).
    """
    # Imported here rather than at module scope: the allowlist stays defined in
    # template_service.py because tests/unit/test_write_discipline_hardening.py
    # imports it from there, and a module-scope import back into that module
    # would be a cycle.
    from giljo_mcp.services.template_service import _ALLOWED_TEMPLATE_UPDATE_FIELDS

    template = await service.get_template_by_id(session, template_id, tenant_key)

    if not template:
        raise TemplateNotFoundError(
            message="Template not found",
            context={"template_id": template_id, "tenant_key": tenant_key},
        )

    # Check if system-managed
    if service._is_system_managed_role(template.role):
        raise AuthorizationError(message="Cannot modify system-managed templates")

    # Apply updates
    update_data = updates.model_dump(exclude_unset=True)
    was_tenant_active = bool(template.is_active)  # BE-9391: detect the False -> True switch-on below.

    # Block attempts to modify system_instructions via API
    if "system_instructions" in update_data:
        raise AuthorizationError(message="system_instructions is read-only; use reset-system to restore defaults")

    if "user_instructions" in update_data:
        await service.create_template_archive(
            session,
            template,
            archive_reason="Update user instructions",
            archive_type="auto",
            archived_by=username,
        )

    # Enforce the active-slot limit when toggling is_active for user-managed roles
    if "is_active" in update_data and update_data["is_active"] is not None:
        new_is_active = bool(update_data["is_active"])
        if new_is_active != bool(template.is_active) and not service._is_system_managed_role(template.role):
            is_valid, error_msg = await service.validate_active_agent_limit(
                session=session,
                tenant_key=tenant_key,
                template_id=template.id,
                new_is_active=new_is_active,
                role=template.role,
            )
            if not is_valid:
                raise ProjectStateError(message=error_msg)

    # Metadata-only updates (e.g. is_active toggle) should not bump updated_at,
    # otherwise the staleness check falsely triggers after enable/disable.
    metadata_only_fields = {"is_active"}
    is_metadata_only = set(update_data.keys()).issubset(metadata_only_fields)
    previous_updated_at = template.updated_at

    # Clear user_managed_export when content fields change (re-triggers staleness)
    content_fields = {"user_instructions", "role", "model", "tools", "description", "cli_tool"}
    if update_data.keys() & content_fields and "user_managed_export" not in update_data:
        template.user_managed_export = False

    for field, value in update_data.items():
        if field == "user_instructions" and value:
            template.user_instructions = value
        elif field in _ALLOWED_TEMPLATE_UPDATE_FIELDS:
            setattr(template, field, value)

    # INF-6049c: keep the legacy "tool" column (Handover 0045) mirrored to the live
    # cli_tool so it cannot drift. create mirrors on insert; do the same on update.
    if "cli_tool" in update_data:
        template.tool = template.cli_tool

    # If role changed, auto-update background color to match new role
    if "role" in update_data:
        template.background_color = get_role_color(template.role)

    await service.commit_and_refresh_template(session, template)

    # Restore updated_at when only metadata changed -- use raw SQL to bypass onupdate
    if is_metadata_only and previous_updated_at is not None:
        from sqlalchemy import update as sql_update

        _t = AgentTemplate.__table__  # SEC-9093: raw table -> guard injects tenant_key predicate
        _stmt = sql_update(_t).where(_t.c.id == template.id).values(updated_at=previous_updated_at)
        await session.execute(_stmt)
        await session.commit()
        await session.refresh(template)

    if not was_tenant_active and bool(template.is_active):  # BE-9391: switching ON is the second door.
        svc = ProductAgentAssignmentService(service.db_manager, tenant_key, test_session=service._session)
        await svc.include_in_active_product(session, template.name)

    service._logger.info("Updated template %s", sanitize(template_id))

    return template, list(update_data.keys())
