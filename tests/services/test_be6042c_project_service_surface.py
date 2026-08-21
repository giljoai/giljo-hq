# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-6042c characterization test — locks the public surface of ProjectService.

This suite is the behavior lock for the mechanical mixin split of
``project_service.py`` into a ``project_service/`` subpackage. It runs GREEN
against the unmodified single-file class FIRST, then unchanged against the
split package. It asserts:

- The load-bearing import path ``from giljo_mcp.services.project_service import
  ProjectService`` resolves (~30 importers: api/endpoints/projects/*,
  api/startup/background_tasks.py, ~25 test files).
- The re-export surface (status constants previously importable from the
  module) keeps resolving — tests/contract/test_project_status_single_source.py
  imports IMMUTABLE_PROJECT_STATUSES / LIFECYCLE_FINISHED_STATUSES /
  VALID_PROJECT_STATUSES straight from this module.
- STRICT set-equality of the public method surface — catches the one real
  mixin failure mode: a dropped, duplicated, or shadowed method.
- Two thin-delegator behavior locks: the facade methods dispatch verbatim to
  the composed sub-service with the same arguments (no signature / service-call
  drift across the split).
"""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.services.project_service import ProjectService


# The public methods of ProjectService (all coroutines; everything
# non-underscore). Locks dropped/duplicated/shadowed methods after the split.
EXPECTED_PUBLIC_METHODS = frozenset(
    {
        # Query concern
        "get_project_type_by_label",
        "get_project",
        "list_projects",
        # BE-6076: filtered COUNT backing the dashboard list X-Total-Count header.
        "count_projects",
        # BE-9468: board-wide grouped counts backing the agent list's `counts` block.
        # Peer of list_projects rather than a repository call from the adapter, so the
        # MCP read path keeps ONE service seam and stays testable without a database.
        "board_counts",
        "get_project_type_by_id",
        # Mutation / lifecycle concern
        "create_project",
        "update_project_mission",
        "set_early_termination",
        "complete_project",
        "activate_project",
        "deactivate_project",
        "update_project",
        "launch_project",
        # BE-9384: the archive lifecycle, shared by the REST endpoint and the MCP
        # terminal transition (previously inlined in the endpoint, reachable by neither).
        "archive_project",
        # MCP adapter concern
        "create_project_for_mcp",
        "render_ctx_bootstrap_mission",
        "list_projects_for_mcp",
        "update_project_metadata_for_mcp",
    }
)


def _public_async_methods(obj) -> set[str]:
    return {name for name in dir(obj) if not name.startswith("_") and inspect.iscoroutinefunction(getattr(obj, name))}


def test_public_import_resolves():
    """Load-bearing import used by ~30 importers across api/ and tests/."""
    from giljo_mcp.services.project_service import ProjectService as Imported

    assert Imported is ProjectService


def test_reexport_surface_resolves():
    """Status constants must stay importable straight from this module path."""
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
    """Class-level surface check — zero fixture coupling, catches drop/dup/shadow."""
    assert _public_async_methods(ProjectService) == EXPECTED_PUBLIC_METHODS


def test_all_public_methods_present_callable_async():
    for name in EXPECTED_PUBLIC_METHODS:
        attr = getattr(ProjectService, name, None)
        assert attr is not None, f"missing method: {name}"
        assert inspect.iscoroutinefunction(attr), f"method not async: {name}"


def _make_service() -> ProjectService:
    """Construct a ProjectService with mocked dependencies (no DB needed).

    The composed sub-services are instantiated in __init__ from MagicMock
    db_manager / tenant_manager — fine for surface + delegator inspection.
    """
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    return ProjectService(db_manager=db_manager, tenant_manager=tenant_manager)


def test_constructor_composes_sub_services():
    service = _make_service()
    # Sub-services composed in __init__ stay wired across the split.
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
    # Facade passes project_service=self through to the launch service.
    assert service.launch.launch_project.await_args.kwargs["project_service"] is service
