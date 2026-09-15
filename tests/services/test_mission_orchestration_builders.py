# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def test_free_functions_importable_from_mission_orchestration_builders() -> None:
    from giljo_mcp.services.mission_orchestration_builders import (
        attach_protocol_and_identity,
        build_category_metadata,
        build_execution_mode_fields,
        check_staging_redirect,
        is_chain_member,
        maybe_build_ctx_self_close_directive,
    )

    assert callable(attach_protocol_and_identity)
    assert callable(build_category_metadata)
    assert callable(build_execution_mode_fields)
    assert callable(check_staging_redirect)
    assert callable(is_chain_member)
    assert callable(maybe_build_ctx_self_close_directive)


def test_back_compat_shims_still_present_on_mission_orchestration_service() -> None:
    from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService

    assert hasattr(MissionOrchestrationService, "_build_execution_mode_fields")
    assert hasattr(MissionOrchestrationService, "_build_category_metadata")
    assert hasattr(MissionOrchestrationService, "_maybe_build_ctx_self_close_directive")
    assert hasattr(MissionOrchestrationService, "_is_chain_member")
    assert hasattr(MissionOrchestrationService, "_check_staging_redirect")
    assert hasattr(MissionOrchestrationService, "_attach_protocol_and_identity")


def test_check_staging_redirect_shim_delegates_to_free_function() -> None:
    from giljo_mcp.services.mission_orchestration_builders import check_staging_redirect
    from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService

    project = SimpleNamespace(
        staging_status="staging_complete",
        implementation_launched_at=None,
        id="proj-1",
        name="Proj",
    )

    shim_result = MissionOrchestrationService._check_staging_redirect(project, "job-1", is_chain_member=False)
    direct_result = check_staging_redirect(project, "job-1", is_chain_member=False)
    assert shim_result == direct_result


def test_maybe_build_ctx_self_close_directive_shim_delegates() -> None:
    from giljo_mcp.services.mission_orchestration_builders import maybe_build_ctx_self_close_directive
    from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService

    ctx = {"project_type_abbreviation": "NOT_CTX", "product": None}

    assert MissionOrchestrationService._maybe_build_ctx_self_close_directive(
        ctx
    ) == maybe_build_ctx_self_close_directive(ctx)


def test_build_execution_mode_fields_shim_delegates() -> None:
    from giljo_mcp.services.mission_orchestration_builders import build_execution_mode_fields
    from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService

    service = MissionOrchestrationService.__new__(MissionOrchestrationService)
    templates = [SimpleNamespace(name="implementer")]

    shim_result = service._build_execution_mode_fields("multi_terminal", templates, "job-1")
    direct_result = build_execution_mode_fields("multi_terminal", templates, "job-1")
    assert shim_result == direct_result
    assert "phase_assignment_instructions" in shim_result


async def test_is_chain_member_shim_delegates_with_service_handles() -> None:
    from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService

    service = MissionOrchestrationService.__new__(MissionOrchestrationService)
    service.db_manager = object()
    service.tenant_manager = object()
    session = object()

    with patch(
        "giljo_mcp.services.mission_orchestration_service.is_chain_member", new=AsyncMock(return_value=True)
    ) as mocked:
        result = await service._is_chain_member(session, "proj-1", "tk")

    assert result is True
    mocked.assert_awaited_once_with(
        session, "proj-1", "tk", db_manager=service.db_manager, tenant_manager=service.tenant_manager
    )
