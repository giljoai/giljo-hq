# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch


def test_free_functions_importable_from_mission_implementation_gate() -> None:
    from giljo_mcp.services.mission_implementation_gate import (
        check_implementation_gate,
        is_chain_member,
    )

    assert callable(check_implementation_gate)
    assert callable(is_chain_member)


def test_back_compat_shims_still_present_on_mission_service() -> None:
    from giljo_mcp.services.mission_service import MissionService

    assert hasattr(MissionService, "_check_implementation_gate")
    assert hasattr(MissionService, "_is_chain_member")


async def test_check_implementation_gate_shim_delegates_with_service_handles() -> None:
    from giljo_mcp.services.mission_service import MissionService

    service = MissionService.__new__(MissionService)
    service._logger = logging.getLogger("test.mission_implementation_gate")
    service._repo = object()
    service.db_manager = object()
    service.tenant_manager = object()
    session = object()
    job = object()

    with patch(
        "giljo_mcp.services.mission_service.check_implementation_gate",
        new=AsyncMock(return_value=("PROJECT", None)),
    ) as mocked:
        result = await service._check_implementation_gate(session, job, "job-1", "tk")

    assert result == ("PROJECT", None)
    mocked.assert_awaited_once_with(
        service._logger,
        session,
        job,
        "job-1",
        "tk",
        repo=service._repo,
        db_manager=service.db_manager,
        tenant_manager=service.tenant_manager,
    )


async def test_is_chain_member_shim_delegates_with_service_handles() -> None:
    from giljo_mcp.services.mission_service import MissionService

    service = MissionService.__new__(MissionService)
    service._logger = logging.getLogger("test.mission_implementation_gate")
    service.db_manager = object()
    service.tenant_manager = object()
    session = object()

    with patch("giljo_mcp.services.mission_service.is_chain_member", new=AsyncMock(return_value=True)) as mocked:
        result = await service._is_chain_member(session, "proj-1", "tk")

    assert result is True
    mocked.assert_awaited_once_with(
        service._logger, session, "proj-1", "tk", db_manager=service.db_manager, tenant_manager=service.tenant_manager
    )


def test_chain_worker_staging_block_message_still_importable_from_mission_service() -> None:
    from giljo_mcp.services.mission_service import _CHAIN_WORKER_STAGING_BLOCK_MESSAGE

    assert "STAGING" in _CHAIN_WORKER_STAGING_BLOCK_MESSAGE
