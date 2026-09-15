# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from giljo_mcp.services.statistics_service import StatisticsService


pytestmark = pytest.mark.asyncio

_PRODUCT_METHODS = (
    "count_total_projects",
    "count_projects_by_status",
    "count_total_messages",
    "count_messages_by_status",
    "count_total_tasks",
    "count_completed_tasks",
    "count_projects_staged",
)


def _service_with_stubbed_repos(total_agents: int) -> StatisticsService:
    session = MagicMock()
    session.info = {}
    svc = StatisticsService(db_manager=Mock(), test_session=session)

    svc._product_repo = Mock()
    for name in _PRODUCT_METHODS:
        setattr(svc._product_repo, name, AsyncMock(return_value=0))

    svc._job_repo = Mock()
    svc._job_repo.count_total_agents = AsyncMock(return_value=total_agents)
    svc._job_repo.count_active_agents = AsyncMock(return_value=0)
    svc._job_repo.count_completed_agents = AsyncMock(return_value=0)
    return svc


async def test_get_system_stats_counts_total_agents_once():
    svc = _service_with_stubbed_repos(total_agents=7)

    await svc.get_system_stats("tenant-x")

    assert svc._job_repo.count_total_agents.await_count == 1


async def test_get_system_stats_both_agent_keys_share_the_count():
    svc = _service_with_stubbed_repos(total_agents=7)

    stats = await svc.get_system_stats("tenant-x")

    assert stats["total_agents"] == 7
    assert stats["total_agents_spawned"] == 7
    assert set(stats) == {
        "total_projects",
        "active_projects",
        "completed_projects",
        "total_agents",
        "active_agents",
        "total_messages",
        "pending_messages",
        "total_tasks",
        "completed_tasks",
        "total_agents_spawned",
        "total_jobs_completed",
        "projects_staged",
        "projects_cancelled",
    }
