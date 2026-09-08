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


async def _seed_project(session, tenant_key, status="active", product=None, **extra):
    """Seed a project, under its own fresh product unless one is passed in.

    BE-9437 made ``product_id`` NOT NULL, so the old note here -- "product_id
    left NULL to avoid the single-active-per-product index" -- describes a state
    that no longer exists. BE-9525b (ruling 5 amended) dropped
    ``idx_project_single_active_per_product`` entirely, so two ACTIVE projects
    under the SAME product is now a legal state too (see the genuinely-plural
    test below); a fresh product per project remains the default here only to
    keep the existing per-product-scoping tests exercising one project each.
    """
    if product is None:
        product = Product(
            id=str(uuid4()),
            tenant_key=tenant_key,
            name=f"Query Product {uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        session.add(product)
        await session.flush()

    project = Project(
        tenant_key=tenant_key,
        product_id=product.id,
        name=extra.pop("name", "Query Project"),
        description="seeded",
        mission="seeded mission",
        status=status,
        series_number=extra.pop("series_number", random.randint(1, 9000)),
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
async def test_get_active_projects_returns_empty_when_no_active(query_service):
    """get_active_projects returns an empty list when no project is active."""
    result = await query_service.get_active_projects()
    assert result == []


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
async def test_get_active_projects_returns_seeded_project(query_service, db_session, test_tenant_key):
    """A seeded active project is returned with correct agent/message counts."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, status="active")
        db_session.add_all([_job(test_tenant_key, project.id), _job(test_tenant_key, project.id)])
        db_session.add(Message(tenant_key=test_tenant_key, project_id=project.id, content="hi", status="pending"))
        await db_session.flush()

    result = await query_service.get_active_projects()

    assert len(result) == 1
    active = result[0]
    assert active.id == str(project.id)
    assert active.name == "Query Project"
    assert active.status == "active"
    assert active.mission == "seeded mission"
    assert active.agent_count == 2
    assert active.message_count == 1


@pytest.mark.asyncio
async def test_get_active_projects_is_genuinely_plural_within_one_product(query_service, db_session, test_tenant_key):
    """BE-9525b: two ACTIVE projects under the SAME product must BOTH come back.

    Before BE-9525b, the repository read used ``.limit(1)`` +
    ``scalar_one_or_none()`` -- safe only because
    ``idx_project_single_active_per_product`` made a second ACTIVE row in the
    same product impossible. With that index dropped, an arbitrary single row
    would be a confidently wrong answer (the BE-9521 failure class); this pins
    that both rows are returned instead of one being silently dropped.
    """
    with tenant_session_context(db_session, test_tenant_key):
        product = Product(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            name=f"Plural Query Product {uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(product)
        await db_session.flush()
        # Explicit, distinct series_number: two untyped (project_type_id=None)
        # projects in the same product would otherwise risk colliding on
        # uq_project_taxonomy_active (NULLS NOT DISTINCT) under _seed_project's
        # default random series_number.
        project_1 = await _seed_project(
            db_session, test_tenant_key, status="active", product=product, name="P1", series_number=101
        )
        project_2 = await _seed_project(
            db_session, test_tenant_key, status="active", product=product, name="P2", series_number=102
        )
        await db_session.flush()

    result = await query_service.get_active_projects(product_id=product.id)

    assert {p.id for p in result} == {str(project_1.id), str(project_2.id)}


@pytest.mark.asyncio
async def test_get_active_projects_populates_nested_project_type(query_service, db_session, test_tenant_key):
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

    result = await query_service.get_active_projects()

    assert len(result) == 1
    active = result[0]
    assert active.project_type_id == taxonomy_type.id
    assert active.project_type is not None, (
        "get_active_projects dropped the nested project_type — GET /api/v1/projects/active "
        "reports null for a typed project. See project_query_service.py "
        "ActiveProjectDetail construction."
    )
    assert active.project_type.abbreviation == "BE"
    assert active.project_type.label == "Backend"
    assert active.project_type.color == "#1976D2"
    assert str(project.id) == active.id


@pytest.mark.asyncio
async def test_get_active_projects_keeps_project_type_null_when_untyped(query_service, db_session, test_tenant_key):
    """A project with no taxonomy type still returns project_type=None, not an error."""
    with tenant_session_context(db_session, test_tenant_key):
        await _seed_project(db_session, test_tenant_key, status="active")
        await db_session.flush()

    result = await query_service.get_active_projects()

    assert len(result) == 1
    assert result[0].project_type_id is None
    assert result[0].project_type is None


@pytest.mark.asyncio
async def test_get_active_projects_scopes_to_product_not_tenant(query_service, db_session, test_tenant_key):
    """BE-9525a: an active project in product A must not surface as active for product B.

    Reproduces the live bug: GET /api/v1/projects/active filtered on tenant_key
    only, so a project active in product A greyed out product B's Activate
    button. Two products, one active project in each; querying by product B's
    id must return product B's own active project, never product A's.
    """
    with tenant_session_context(db_session, test_tenant_key):
        project_a = await _seed_project(db_session, test_tenant_key, status="active")
        project_b = await _seed_project(db_session, test_tenant_key, status="active")
        await db_session.flush()

    result_a = await query_service.get_active_projects(product_id=project_a.product_id)
    result_b = await query_service.get_active_projects(product_id=project_b.product_id)

    assert len(result_a) == 1
    assert result_a[0].id == str(project_a.id)
    assert result_a[0].product_id == project_a.product_id

    assert len(result_b) == 1
    assert result_b[0].id == str(project_b.id)
    assert result_b[0].product_id == project_b.product_id


@pytest.mark.asyncio
async def test_get_active_projects_scoped_to_product_with_none_active_there(query_service, db_session, test_tenant_key):
    """Product B has no active project of its own, even though product A does."""
    with tenant_session_context(db_session, test_tenant_key):
        await _seed_project(db_session, test_tenant_key, status="active")
        project_b = await _seed_project(db_session, test_tenant_key, status="inactive")
        await db_session.flush()

    result_b = await query_service.get_active_projects(product_id=project_b.product_id)

    assert result_b == []


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
