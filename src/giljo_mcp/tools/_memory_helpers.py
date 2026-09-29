# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    yield existing_session


def refuse_if_superseded(project: Any) -> dict[str, Any] | None:
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


NO_CODE_CHANGES_MAX = 500


def normalize_no_code_changes(
    no_code_changes: str | None,
    git_commits: list[Any] | None,
) -> str | None:
    reason = (no_code_changes or "").strip()
    if not reason:
        return None
    if len(reason) > NO_CODE_CHANGES_MAX:
        raise ValidationError(f"no_code_changes must be at most {NO_CODE_CHANGES_MAX} characters.")
    if git_commits:
        raise ValidationError("Pass git_commits or no_code_changes, not both.")
    return reason


def git_commits_required_rejection(project_id: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": "GIT_COMMITS_REQUIRED",
        "project_id": project_id,
        "message": (
            "Git integration is enabled, so this closeout needs one of: git_commits (the "
            "commits this project made), or no_code_changes='<why>' when it changed no code. "
            "Do not create an empty commit to satisfy this."
        ),
    }


MAX_SUMMARY_LENGTH = 10000
MAX_KEY_OUTCOMES = 100
MAX_DECISIONS_MADE = 100


def build_git_commit_title_required_rejection(
    exc: GitCommitTitleRequiredError,
    project_id: str,
) -> dict[str, Any]:
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
