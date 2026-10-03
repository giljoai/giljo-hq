# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from giljo_mcp.models import Project
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.tools.write_memory_entry import write_360_memory


@pytest_asyncio.fixture
async def linked_project(db_session, test_tenant_key, test_product):
    project = Project(
        id=str(uuid.uuid4()),
        name="Author job required",
        description="fixture",
        mission="fixture",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return project


def _db_manager(db_session):
    mgr = MagicMock()
    mgr.get_session_async = MagicMock()
    mgr.get_session_async.return_value.__aenter__ = AsyncMock(return_value=db_session)
    mgr.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)
    return mgr


async def _write(db_session, tenant_key, project_id, entry_type):
    with (
        patch("giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness", new_callable=AsyncMock),
        patch("giljo_mcp.tools.write_memory_entry.emit_websocket_event", new_callable=AsyncMock),
    ):
        return await write_360_memory(
            project_id=project_id,
            tenant_key=tenant_key,
            summary="Headline.",
            key_outcomes=["k"],
            decisions_made=["d"],
            entry_type=entry_type,
            git_commits=[{"sha": "abc1234", "message": "fixture commit"}],
            tags=[],
            db_manager=_db_manager(db_session),
            session=db_session,
        )


async def _entry_count(db_session, project_id: str) -> int:
    return await db_session.scalar(
        select(func.count()).select_from(ProductMemoryEntry).where(ProductMemoryEntry.project_id == project_id)
    )


@pytest.mark.asyncio
async def test_project_completion_without_author_job_id_is_refused(db_session, test_tenant_key, linked_project):
    result = await _write(db_session, test_tenant_key, str(linked_project.id), "project_completion")

    assert result.get("success") is False, result
    assert result.get("error") == "ORCHESTRATOR_ONLY_ENTRY_TYPE"
    assert await _entry_count(db_session, str(linked_project.id)) == 0


@pytest.mark.asyncio
async def test_a_worker_entry_type_without_author_job_id_still_writes(db_session, test_tenant_key, linked_project):
    result = await _write(db_session, test_tenant_key, str(linked_project.id), "decision")

    assert result.get("success") is not False, result
    assert await _entry_count(db_session, str(linked_project.id)) == 1
