# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for ProjectQueryService (Sprint 002e extraction).

These tests verify the read-only dashboard query methods after extraction from
ProjectService. Every method swallows exceptions and returns an empty result on
error, so the previous not-found/empty-only tests would pass even if the
underlying join/query were broken. These seed real rows into the test database
and assert the returned data, so a broken query fails the suite.
"""

import random
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentExecution, AgentJob, Message, Product, ProductMemoryEntry, Project
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.project_query_service import ProjectQueryService


@pytest.fixture
def query_service(db_session, test_tenant_key):
    """Create a ProjectQueryService with a test session."""
    db_manager = MagicMock()
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return ProjectQueryService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_project(session, tenant_key, status="active", **extra):
    """Seed a project (product_id left NULL to avoid the single-active-per-product index)."""
    project = Project(
        tenant_key=tenant_key,
        name="Query Project",
        description="seeded",
        mission="seeded mission",
        status=status,
        series_number=random.randint(1, 9000),
        **extra,
    )
    session.add(project)
    await session.flush()
    return project


def _job(tenant_key, project_id, job_type="implementer"):
    return AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        mission="do X",
        job_type=job_type,
        status="active",
        created_at=datetime.now(UTC),
    )


# ---- Not-found / empty paths (cheap smoke, retained) ----


@pytest.mark.asyncio
async def test_get_active_project_returns_none_when_no_active(query_service):
    """get_active_project returns None when no project is active."""
    result = await query_service.get_active_project()
    assert result is None


@pytest.mark.asyncio
async def test_get_project_agent_summary_returns_empty_for_missing_project(query_service, test_tenant_key):
    """get_project_agent_summary returns zero counts for non-existent project."""
    result = await query_service.get_project_agent_summary("00000000-0000-0000-0000-000000000000", test_tenant_key)
    assert result == {"agent_count": 0, "job_types": []}


@pytest.mark.asyncio
async def test_get_project_agent_details_returns_empty_for_missing_project(query_service, test_tenant_key):
    """get_project_agent_details returns empty list for non-existent project."""
    result = await query_service.get_project_agent_details("00000000-0000-0000-0000-000000000000", test_tenant_key)
    assert result == []


@pytest.mark.asyncio
async def test_get_project_memory_entries_returns_empty_for_missing_project(query_service, test_tenant_key):
    """get_project_memory_entries returns empty list for non-existent project."""
    result = await query_service.get_project_memory_entries("00000000-0000-0000-0000-000000000000", test_tenant_key)
    assert result == []


@pytest.mark.asyncio
async def test_get_project_messages_returns_empty_for_missing_project(query_service, test_tenant_key):
    """get_project_messages returns empty list for non-existent project."""
    result = await query_service.get_project_messages("00000000-0000-0000-0000-000000000000", test_tenant_key)
    assert result == []


# ---- Seeded positive paths (verify real returned data) ----


@pytest.mark.asyncio
async def test_get_active_project_returns_seeded_project(query_service, db_session, test_tenant_key):
    """A seeded active project is returned with correct agent/message counts."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, status="active")
        db_session.add_all([_job(test_tenant_key, project.id), _job(test_tenant_key, project.id)])
        db_session.add(Message(tenant_key=test_tenant_key, project_id=project.id, content="hi", status="pending"))
        await db_session.flush()

    result = await query_service.get_active_project()

    assert result is not None
    assert result.id == str(project.id)
    assert result.name == "Query Project"
    assert result.status == "active"
    assert result.mission == "seeded mission"
    assert result.agent_count == 2
    assert result.message_count == 1


@pytest.mark.asyncio
async def test_get_active_project_populates_nested_project_type(query_service, db_session, test_tenant_key):
    """BE-9326: the ActiveProjectDetail builder must carry the nested project_type.

    The builder listed project_type_id but not project_type, and the field defaults
    to None on the schema — so nothing raised and GET /api/v1/projects/active
    reported ``project_type: null`` for every project, including typed ones
    (api/endpoints/projects/crud.py::_to_project_response reads proj.project_type).
    """
    with tenant_session_context(db_session, test_tenant_key):
        taxonomy_type = TaxonomyType(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            abbreviation="BE",
            label="Backend",
            color="#1976D2",
        )
        db_session.add(taxonomy_type)
        await db_session.flush()
        project = await _seed_project(db_session, test_tenant_key, status="active", project_type_id=taxonomy_type.id)
        await db_session.flush()

    result = await query_service.get_active_project()

    assert result is not None
    assert result.project_type_id == taxonomy_type.id
    assert result.project_type is not None, (
        "get_active_project dropped the nested project_type — GET /api/v1/projects/active "
        "reports null for a typed project. See project_query_service.py "
        "ActiveProjectDetail construction."
    )
    assert result.project_type.abbreviation == "BE"
    assert result.project_type.label == "Backend"
    assert result.project_type.color == "#1976D2"
    assert str(project.id) == result.id


@pytest.mark.asyncio
async def test_get_active_project_keeps_project_type_null_when_untyped(query_service, db_session, test_tenant_key):
    """A project with no taxonomy type still returns project_type=None, not an error."""
    with tenant_session_context(db_session, test_tenant_key):
        await _seed_project(db_session, test_tenant_key, status="active")
        await db_session.flush()

    result = await query_service.get_active_project()

    assert result is not None
    assert result.project_type_id is None
    assert result.project_type is None


@pytest.mark.asyncio
async def test_get_project_agent_summary_groups_by_job_type(query_service, db_session, test_tenant_key):
    """Agent summary counts jobs grouped by job_type."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key)
        db_session.add_all(
            [
                _job(test_tenant_key, project.id, "implementer"),
                _job(test_tenant_key, project.id, "implementer"),
                _job(test_tenant_key, project.id, "tester"),
            ]
        )
        await db_session.flush()

    result = await query_service.get_project_agent_summary(str(project.id), test_tenant_key)

    assert result["agent_count"] == 3
    assert {jt["type"]: jt["count"] for jt in result["job_types"]} == {"implementer": 2, "tester": 1}


@pytest.mark.asyncio
async def test_get_project_agent_details_returns_joined_rows(query_service, db_session, test_tenant_key):
    """Agent details join job + execution and project the expected fields."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key)
        job = _job(test_tenant_key, project.id, "implementer")
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            AgentExecution(
                job_id=job.job_id,
                agent_id=str(uuid4()),
                tenant_key=test_tenant_key,
                agent_display_name="implementer",
                agent_name="impl-1",
                status="working",
                result={"summary": "ok"},
            )
        )
        await db_session.flush()

    details = await query_service.get_project_agent_details(str(project.id), test_tenant_key)

    assert len(details) == 1
    row = details[0]
    assert row["job_id"] == job.job_id
    assert row["job_type"] == "implementer"
    assert row["display_name"] == "implementer"
    assert row["agent_status"] == "working"
    assert row["mission"] == "do X"
    assert row["result"] == {"summary": "ok"}

    headlines = await query_service.get_project_agent_details(str(project.id), test_tenant_key, headlines=True)
    assert set(headlines[0].keys()) == {"job_id", "display_name", "status", "completed_at"}


@pytest.mark.asyncio
async def test_get_project_memory_entries_returns_seeded_entries(query_service, db_session, test_tenant_key):
    """Memory entries are returned, respect limit, and support the headlines projection."""
    with tenant_session_context(db_session, test_tenant_key):
        product = Product(tenant_key=test_tenant_key, name="P", description="d", is_active=True)
        db_session.add(product)
        await db_session.flush()
        project = await _seed_project(db_session, test_tenant_key)
        for seq in (1, 2, 3):
            db_session.add(
                ProductMemoryEntry(
                    tenant_key=test_tenant_key,
                    product_id=product.id,
                    project_id=project.id,
                    sequence=seq,
                    entry_type="project_completion",
                    source="write_360_memory_v1",
                    timestamp=datetime.now(UTC),
                    summary=f"summary {seq}",
                )
            )
        await db_session.flush()

    entries = await query_service.get_project_memory_entries(str(project.id), test_tenant_key)
    assert len(entries) == 3

    limited = await query_service.get_project_memory_entries(str(project.id), test_tenant_key, limit=2)
    assert len(limited) == 2

    headlines = await query_service.get_project_memory_entries(str(project.id), test_tenant_key, headlines=True)
    assert set(headlines[0].keys()) == {"id", "sequence", "entry_type", "summary", "timestamp"}


@pytest.mark.asyncio
async def test_get_project_messages_returns_seeded_messages(query_service, db_session, test_tenant_key):
    """Messages for a project are returned with their content and type."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key)
        for i in range(2):
            db_session.add(
                Message(
                    tenant_key=test_tenant_key,
                    project_id=project.id,
                    content=f"msg {i}",
                    message_type="direct",
                    status="pending",
                    from_agent_id=f"agent-{i}",
                )
            )
        await db_session.flush()

    messages = await query_service.get_project_messages(str(project.id), test_tenant_key)

    assert len(messages) == 2
    assert {m["content"] for m in messages} == {"msg 0", "msg 1"}
    assert all(m["message_type"] == "direct" for m in messages)
