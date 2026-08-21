# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Trash, recover and reap agent templates -- the soft-delete lifecycle (BE-9394).

Owns ONE question end to end: where is a template in its soft-delete lifecycle, and
what may move it? Trash it (stamp ``deleted_at``), list what is trashed, restore it
inside the 30-day window, and hard-delete what has aged past that window. The four
share one boundary -- ``RECOVER_WINDOW_DAYS`` -- so they belong together rather than
beside the create/update writes, which never consult it.

Lives outside ``template_service.py`` for the reason ``orchestrator_product_resolver``
and ``conductor_staging_builder`` were extracted before it -- that module sat at its
shrink-only line budget plus the full tolerance band, with no headroom for the next
line. Extracting this group alongside the write paths took the parent back under the
flat 800-line cap, so it stops being a permanently-budgeted oversize file rather than
merely dropping under a ceiling it would soon re-approach.

Entry points take the calling service, the shape ``_resolve_product_id(service, ...)``
already established; the ``TemplateService`` methods remain as thin delegators, so
every caller and every existing test keeps calling the same service methods.

Edition Scope: Both.
"""

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
    """Hard-delete trashed templates past the recovery window (TSK-6132 reaper).

    Walks this tenant's soft-deleted templates and permanently removes those
    whose ``deleted_at`` is past ``RECOVER_WINDOW_DAYS`` (the same boundary
    ``restore_template`` refuses to recover past). Performs the same hard-delete
    steps the removed ``hard_delete_template`` method used (nullify historical
    AgentJob refs -> delete TemplateArchive version history -> delete the
    template); those steps are FK-safe for the template's self-references.
    Returns the count purged; tenant-isolated and idempotent (re-running finds
    none).
    """
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
    """Soft-delete (trash) a template by stamping deleted_at.

    Drops the template out of every live read; ``restore_template`` recovers
    it within the 30-day window. Archives survive the soft-delete and
    re-surface automatically when the template is restored.

    The system-managed-role guard and permission check MUST be enforced by
    the calling REST endpoint (crud.py) before reaching this method -- the
    same contract as before BE-6137.

    Args:
        service: The calling TemplateService.
        session: Database session (caller-owned transaction)
        template_id: Template UUID
        tenant_key: Tenant key for isolation

    Returns:
        True if soft-deleted, False if not found

    Raises:
        BaseGiljoError: On unexpected database failure
    """
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
    """Restore a soft-deleted (trashed) template within the 30-day window.

    Clears deleted_at so the template re-enters every live read. Archives
    were never deleted and re-surface automatically. No serial to re-mint
    (AgentTemplate is keyed on name/version; the partial unique index handles
    the re-create case).

    Args:
        service: The calling TemplateService.
        template_id: Template UUID
        tenant_key: Tenant key for isolation

    Returns:
        Refreshed AgentTemplate ORM instance

    Raises:
        ValidationError: No tenant context, or recovery window expired (>30d)
        ResourceNotFoundError: No trashed template matched id for the tenant
        BaseGiljoError: On unexpected database failure
    """
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
    except (BaseGiljoError, ResourceNotFoundError, ValidationError):
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
    """List soft-deleted (trashed) templates for the recover dialog.

    Tenant-isolated; ordered most-recently-trashed first.

    Raises:
        ValidationError: No tenant context
        BaseGiljoError: On unexpected database failure
    """
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
    except (BaseGiljoError, ResourceNotFoundError, ValidationError):
        raise
    except Exception as e:
        service._logger.exception("Failed to list deleted templates")
        raise BaseGiljoError(
            message=str(e),
            context={"operation": "list_deleted_templates"},
        ) from e
