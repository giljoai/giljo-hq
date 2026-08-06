# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Shared helpers for project_closeout and write_memory_entry tools."""

import logging
from contextlib import asynccontextmanager
from inspect import iscoroutine
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.schemas.jsonb_validators import GitCommitTitleRequiredError


logger = logging.getLogger(__name__)


@asynccontextmanager
async def provided_session(existing_session: AsyncSession):
    """No-op async context manager yielding an existing session unchanged.

    Lets the write tools `async with` either a fresh ``db_manager`` session or a
    caller-supplied one through a single code path. Extracted from the identical
    inline definitions in project_closeout / write_memory_entry (BE-9157).
    """
    yield existing_session


def refuse_if_superseded(project: Any) -> dict[str, Any] | None:
    """Return a structured rejection when writing 360 memory to a superseded project.

    BE-9157: a ``superseded`` project is an audit-trail row whose work moved to a
    successor. Writing a closeout / 360 memory entry against it would attach
    history to the wrong (retired) project, so both write paths
    (``write_360_memory`` and ``close_project_and_update_memory``) refuse it.

    This is a DELIBERATE, agent-actionable domain rejection (the BE-6081 Tier-2
    carve-out shape), not an internal error: the caller returns this dict rather
    than raising, so it reaches the agent as normal tool content (not isError)
    and points them at the successor. Returns ``None`` when the project is not
    superseded (the write proceeds unchanged).
    """
    if project is None or getattr(project, "status", None) != ProjectStatus.SUPERSEDED:
        return None
    return {
        "success": False,
        "error": "PROJECT_SUPERSEDED",
        "project_id": str(project.id),
        "successor_project_id": getattr(project, "successor_project_id", None),
        "message": (
            "This project was superseded — its work moved to a successor project. "
            "360 memory / closeout writes against a superseded project are refused so "
            "history is not attached to retired work. Write to the successor project instead."
        ),
        "hint": (
            "Use the successor_project_id above (if set) as the project_id for this write, "
            "or list_projects(include_superseded=false) to find the live project."
        ),
    }


# Field length constraints
MAX_SUMMARY_LENGTH = 10000  # ~2,500 tokens
MAX_KEY_OUTCOMES = 100
MAX_DECISIONS_MADE = 100


def build_git_commit_title_required_rejection(
    exc: GitCommitTitleRequiredError,
    project_id: str,
) -> dict[str, Any]:
    """Build the BE-6081 Tier-2 structured rejection for a titleless git_commits entry.

    Shared by ``write_project_closeout`` and ``write_memory_entry`` -- both call sites
    catch ``GitCommitTitleRequiredError`` (raised by ``validate_git_commits``, BE-9256)
    around the same JSONB validator call and return this dict instead of letting the
    exception propagate, so the rejection reaches the agent as normal tool content
    (not isError) with the exact git command it needs to self-correct.
    """
    return {
        "success": False,
        "error": "GIT_COMMIT_TITLE_REQUIRED",
        "project_id": project_id,
        "message": str(exc),
        "hint": exc.hint,
    }


async def _fetch_project_and_product(
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
) -> tuple[Any, Any]:
    """
    Fetch the Project and its associated Product from the database.

    Both queries are filtered by tenant_key for tenant isolation. Raises
    ResourceNotFoundError if either record is missing or belongs to a
    different tenant. Raises ValidationError when the project has no
    linked product.

    Returns:
        Tuple of (project, product) ORM instances.
    """
    project_stmt = select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key)
    project_result = await session.execute(project_stmt)
    project = project_result.scalar_one_or_none()
    if iscoroutine(project):
        project = await project

    if not project:
        raise ResourceNotFoundError("Project not found or unauthorized for tenant")

    if getattr(project, "tenant_key", None) != tenant_key:
        raise ResourceNotFoundError("Project not found or unauthorized for tenant")

    if not project.product_id:
        raise ValidationError("Project not associated with product")

    product_stmt = select(Product).where(
        Product.id == project.product_id,
        Product.tenant_key == tenant_key,
    )
    product_result = await session.execute(product_stmt)
    product = product_result.scalar_one_or_none()
    if iscoroutine(product):
        product = await product

    if not product:
        raise ResourceNotFoundError("Product not found for project")

    return project, product


async def emit_websocket_event(
    event_type: str,
    tenant_key: str,
    product_id: str,
    data: dict[str, Any],
) -> None:
    """
    Emit WebSocket event; graceful no-op if manager unavailable.

    Args:
        event_type: Event type (e.g., "product:memory:updated")
        tenant_key: Tenant isolation key
        product_id: Product UUID
        data: Event payload data

    Side Effects:
        - Broadcasts event to tenant WebSocket clients
        - Logs warning if WebSocket fails (doesn't crash operation)
    """
    try:
        from giljo_mcp.app_registry.service_registry import get_websocket_manager

        websocket_manager = get_websocket_manager()

        if websocket_manager:
            await websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type=event_type,
                data={"product_id": product_id, **data},
            )
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:  # pragma: no cover - best-effort emit
        logger.warning("WebSocket emit failed", extra={"error": str(exc), "event_type": event_type})
