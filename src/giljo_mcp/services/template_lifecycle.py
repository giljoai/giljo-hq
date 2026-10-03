# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.soft_delete import RECOVER_WINDOW_DAYS, recover_window_expired
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.utils.log_sanitizer import sanitize


async def purge_expired_deleted_templates(service: Any, tenant_key: str | None = None) -> int:
    effective_tenant_key = tenant_key or service.tenant_manager.get_current_tenant()
    if not effective_tenant_key:
        raise ValidationError(
            message="No tenant context available", context={"operation": "purge_expired_deleted_templates"}
        )
    purged = 0
    async with service._get_session(effective_tenant_key) as session:
        with tenant_session_context(session, effective_tenant_key):
            for template in await service._repo.list_deleted(session, effective_tenant_key):
                if not recover_window_expired(template.deleted_at):
                    continue
                try:
                    async with session.begin_nested():
                        await service._repo.nullify_job_template_refs(session, template.id)
                        await service._repo.delete_archives(session, template.id)
                        await service._repo.delete_template(session, template)
                        await service._repo.flush(session)
                    purged += 1
                except Exception:
                    service._logger.exception("Reaper failed to purge template %s", template.id)
    return purged


async def delete_template(
    service: Any,
    session: AsyncSession,
    template_id: str,
    tenant_key: str,
) -> bool:
    try:
        async with service._get_session(tenant_key) as _session:
            template = await service._repo.get_by_id(_session, template_id, tenant_key)
            if not template:
                return False

            template.deleted_at = datetime.now(UTC)
            await service._repo.flush(_session)

        service._logger.info("Soft-deleted template %s (tenant %s)", sanitize(template_id), tenant_key)
        return True
    except BaseGiljoError:
        raise
    except Exception as e:
        service._logger.exception("Failed to soft-delete template %s", sanitize(template_id))
        raise BaseGiljoError(
            message=str(e),
            context={"operation": "delete_template", "template_id": template_id},
        ) from e


async def restore_template(
    service: Any,
    template_id: str,
    tenant_key: str,
) -> AgentTemplate:
    try:
        if not tenant_key:
            tenant_key = service.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available",
                context={"operation": "restore_template", "template_id": template_id},
            )

        async with service._get_session(tenant_key) as session:
            template = await service._repo.get_deleted_template_by_id(session, template_id, tenant_key)
            if not template:
                raise ResourceNotFoundError(
                    message="Deleted template not found",
                    context={"template_id": template_id, "tenant_key": tenant_key},
                )

            if recover_window_expired(template.deleted_at):
                raise ValidationError(
                    message=(
                        f"This template was deleted more than {RECOVER_WINDOW_DAYS} days ago "
                        "and can no longer be recovered."
                    ),
                    context={"template_id": template_id, "tenant_key": tenant_key},
                )

            template.deleted_at = None
            await service._repo.flush_and_refresh(session, template)

        service._logger.info("Restored template %s (tenant %s)", sanitize(template_id), tenant_key)
        return template
    except BaseGiljoError:
        raise
    except Exception as e:
        service._logger.exception("Failed to restore template %s", sanitize(template_id))
        raise BaseGiljoError(
            message=str(e),
            context={"operation": "restore_template", "template_id": template_id},
        ) from e


async def list_deleted_templates(
    service: Any,
    tenant_key: str | None = None,
) -> list[AgentTemplate]:
    try:
        if not tenant_key:
            tenant_key = service.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(
                message="No tenant context available",
                context={"operation": "list_deleted_templates"},
            )

        async with service._get_session(tenant_key) as session:
            return await service._repo.list_deleted(session, tenant_key)
    except BaseGiljoError:
        raise
    except Exception as e:
        service._logger.exception("Failed to list deleted templates")
        raise BaseGiljoError(
            message=str(e),
            context={"operation": "list_deleted_templates"},
        ) from e
