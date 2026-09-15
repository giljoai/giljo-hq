# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import (
    AuthorizationError,
    TemplateNotFoundError,
    ValidationError,
)
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.template_validation import MAX_NAME_SUFFIX, crew_suffixed_names, get_role_color, slugify_name
from giljo_mcp.utils.log_sanitizer import sanitize


async def require_own_product(session: AsyncSession, product_id: str, tenant_key: str) -> None:
    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.models.products import Product

    if not product_id or not isinstance(product_id, str):
        raise ValidationError(message="product_id is required: an agent belongs to a product")
    if len(product_id) > 36:
        raise ValidationError(message="product_id exceeds maximum length (36)")

    stmt = select(Product.id).where(
        Product.id == product_id,
        Product.tenant_key == tenant_key,
        Product.deleted_at.is_(None),
    )
    with tenant_session_context(session, tenant_key):
        found = (await session.execute(stmt)).scalar_one_or_none()

    if not found:
        raise ValidationError(
            message=f"Product '{product_id}' not found for this account",
            context={"product_id": product_id, "tenant_key": tenant_key},
        )


async def resolve_crew_suffix(
    service: Any,
    session: AsyncSession,
    tenant_key: str,
    base_names: list[str],
) -> list[str]:
    if not base_names:
        return []

    taken: set[str] = set()
    for base in base_names:
        for n in range(1, MAX_NAME_SUFFIX + 1):
            candidate = base if n == 1 else f"{base}-{n}"
            if await service.check_template_name_exists(session, tenant_key, candidate):
                taken.add(candidate)

    resolved = crew_suffixed_names(base_names, taken)
    if resolved is None:
        raise ValidationError(
            message=(f"Too many agent crews named '{base_names[0]}' and siblings — rename or delete some agents first")
        )
    return resolved[0]


async def create_from_request(
    service: Any,
    session: AsyncSession,
    data,
    tenant_key: str,
    created_by: str | None = None,
) -> AgentTemplate:
    from giljo_mcp.template_seeder import _get_mcp_bootstrap_section

    await require_own_product(session, data.product_id, tenant_key)

    raw_name = data.name or data.role or ""
    generated_name = slugify_name(data.role or raw_name, data.custom_suffix)

    if not generated_name or not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", generated_name):
        raise ValidationError(message="Name must use lowercase letters, numbers, and hyphens only")
    if len(generated_name) > 100:
        raise ValidationError(message="Name must be 100 characters or less")

    base_name = generated_name
    counter = 2
    while await service.check_template_name_exists(session, tenant_key, generated_name):
        generated_name = f"{base_name}-{counter}"
        counter += 1
        if counter > 20:
            raise ValidationError(message=f"Too many agents named '{base_name}' — use a custom suffix")

    canonical_bootstrap = _get_mcp_bootstrap_section()

    background_color = data.background_color or get_role_color(data.role)

    description = data.description
    if not description:
        if data.cli_tool == "claude":
            description = f"Subagent for {data.role}"
        else:
            description = f"{data.role} agent template" if data.role else "Agent template"

    variables = re.findall(r"\{(\w+)\}", data.user_instructions or "")

    new_template_id = str(uuid4())


    if data.is_default and data.role:
        existing_defaults = await service.get_default_templates_by_role(session, tenant_key, data.role)
        for existing in existing_defaults:
            existing.is_default = False

    new_template = AgentTemplate(
        id=new_template_id,
        tenant_key=tenant_key,
        product_id=data.product_id,
        name=generated_name,
        category=data.category or "role",
        role=data.role,
        cli_tool=data.cli_tool,
        background_color=background_color,
        description=description,
        system_instructions=canonical_bootstrap,
        user_instructions=data.user_instructions or "",
        model=(data.model or "").strip() or "inherit",
        effort=(getattr(data, "effort", None) or "").strip() or "inherit",
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
    from giljo_mcp.services.template_service import _ALLOWED_TEMPLATE_UPDATE_FIELDS

    template = await service.get_template_by_id(session, template_id, tenant_key)

    if not template:
        raise TemplateNotFoundError(
            message="Template not found",
            context={"template_id": template_id, "tenant_key": tenant_key},
        )

    if service._is_system_managed_role(template.role):
        raise AuthorizationError(message="Cannot modify system-managed templates")

    update_data = updates.model_dump(exclude_unset=True)

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


    metadata_only_fields = {"is_active"}
    is_metadata_only = set(update_data.keys()).issubset(metadata_only_fields)
    previous_updated_at = template.updated_at

    for field, value in update_data.items():
        if field == "user_instructions" and value:
            template.user_instructions = value
        elif field in _ALLOWED_TEMPLATE_UPDATE_FIELDS:
            setattr(template, field, value)

    if "cli_tool" in update_data:
        template.tool = template.cli_tool

    if "role" in update_data:
        template.background_color = get_role_color(template.role)

    await service.commit_and_refresh_template(session, template)

    if is_metadata_only and previous_updated_at is not None:
        from sqlalchemy import update as sql_update

        _t = AgentTemplate.__table__
        _stmt = sql_update(_t).where(_t.c.id == template.id).values(updated_at=previous_updated_at)
        await session.execute(_stmt)
        await session.commit()
        await session.refresh(template)


    service._logger.info("Updated template %s", sanitize(template_id))

    return template, list(update_data.keys())
