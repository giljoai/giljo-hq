# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.services.project_service import ProjectService


EXPECTED_PUBLIC_METHODS = frozenset(
    {
        "get_project_type_by_label",
        "get_project",
        "list_projects",
        "count_projects",
        "board_counts",
        "get_project_type_by_id",
        "create_project",
        "update_project_mission",
        "complete_project",
        "activate_project",
        "deactivate_project",
        "update_project",
        "launch_project",
        "archive_project",
        "create_project_for_mcp",
        "render_ctx_bootstrap_mission",
        "list_projects_for_mcp",
        "update_project_metadata_for_mcp",
    }
)


def _public_async_methods(obj) -> set[str]:
    return {name for name in dir(obj) if not name.startswith("_") and inspect.iscoroutinefunction(getattr(obj, name))}


def test_public_import_resolves():
    from giljo_mcp.services.project_service import ProjectService as Imported

    assert Imported is ProjectService


def test_reexport_surface_resolves():
    from giljo_mcp.services.project_service import (
        ALWAYS_MUTABLE_FIELDS,
        IMMUTABLE_PROJECT_STATUSES,
        LIFECYCLE_FINISHED_STATUSES,
        VALID_PROJECT_STATUSES,
    )

    assert "hidden" in ALWAYS_MUTABLE_FIELDS
    assert IMMUTABLE_PROJECT_STATUSES is not None
    assert LIFECYCLE_FINISHED_STATUSES is not None
    assert VALID_PROJECT_STATUSES is not None


def test_public_method_surface_set_equality():
    assert _public_async_methods(ProjectService) == EXPECTED_PUBLIC_METHODS


def test_all_public_methods_present_callable_async():
    for name in EXPECTED_PUBLIC_METHODS:
        attr = getattr(ProjectService, name, None)
        assert attr is not None, f"missing method: {name}"
        assert inspect.iscoroutinefunction(attr), f"method not async: {name}"


def _make_service() -> ProjectService:
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    return ProjectService(db_manager=db_manager, tenant_manager=tenant_manager)


def test_constructor_composes_sub_services():
    service = _make_service()
    assert service.lifecycle is not None
    assert service.closeout is not None
    assert service.deletion is not None
    assert service.launch is not None
    assert service.summary is not None
    assert service.query is not None


@pytest.mark.asyncio
async def test_complete_project_delegates_to_lifecycle():
    service = _make_service()
    service.lifecycle.complete_project = AsyncMock(return_value={"ok": True})

    result = await service.complete_project(
        project_id="p1",
        summary="s",
        key_outcomes=["k"],
        decisions_made=["d"],
        tenant_key="tk",
    )

    assert result == {"ok": True}
    service.lifecycle.complete_project.assert_awaited_once()
    kwargs = service.lifecycle.complete_project.await_args.kwargs
    args = service.lifecycle.complete_project.await_args.args
    assert "p1" in args
    assert kwargs["tenant_key"] == "tk"


@pytest.mark.asyncio
async def test_launch_project_delegates_to_launch_service():
    service = _make_service()
    service.launch.launch_project = AsyncMock(return_value={"launched": True})

    result = await service.launch_project(project_id="p1")

    assert result == {"launched": True}
    service.launch.launch_project.assert_awaited_once()
    assert service.launch.launch_project.await_args.kwargs["project_service"] is service
