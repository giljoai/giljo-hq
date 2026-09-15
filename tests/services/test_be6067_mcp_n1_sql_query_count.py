# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import event

from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.services.project_service import ProjectService


_JOBS_PER_PROJECT = 2
_ENTRIES_PER_PROJECT = 3

_EXPECTED_ENRICHMENT_QUERIES = 3

_N_SMALL = 3
_N_LARGE = 12


class _Item:

    def __init__(self, project: Project):
        self.id = project.id
        self.name = project.name
        self.status = project.status
        self.project_type = None
        self.series_number = project.series_number
        self.taxonomy_alias = getattr(project, "taxonomy_alias", None)
        self.created_at = None
        self.completed_at = None
        self.description = project.description
        self.mission = project.mission


async def _seed_enriched_projects(db_session, tenant_key: str, count: int) -> list[_Item]:
    from giljo_mcp.repositories.project_repository import ProjectRepository

    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE-6067 Product {uuid.uuid4().hex[:6]}",
        description="d",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    base = datetime(2026, 1, 1, tzinfo=UTC)
    seq = 0
    for n in range(count):
        project = Project(
            id=str(uuid.uuid4()),
            name=f"BE-6067 P{n}",
            description="d",
            mission="m",
            status="active" if n == 0 else "inactive",
            tenant_key=tenant_key,
            product_id=product.id,
            series_number=96670 + n,
        )
        db_session.add(project)
        await db_session.flush()
        for j in range(_JOBS_PER_PROJECT):
            jid = str(uuid.uuid4())
            db_session.add(
                AgentJob(job_id=jid, project_id=project.id, tenant_key=tenant_key, job_type="implementer", mission="m")
            )
            await db_session.flush()
            db_session.add(
                AgentExecution(
                    job_id=jid,
                    agent_id=str(uuid.uuid4()),
                    tenant_key=tenant_key,
                    status="working",
                    agent_name=f"impl-{n}-{j}",
                    agent_display_name="implementer",
                )
            )
        for _ in range(_ENTRIES_PER_PROJECT):
            seq += 1
            db_session.add(
                ProductMemoryEntry(
                    id=uuid.uuid4(),
                    tenant_key=tenant_key,
                    product_id=product.id,
                    project_id=project.id,
                    sequence=seq,
                    entry_type="closeout",
                    source="agent",
                    timestamp=base + timedelta(hours=seq),
                    summary=f"entry {n}",
                )
            )
    await db_session.commit()

    repo = ProjectRepository()
    seeded = await repo.list_projects(db_session, tenant_key, status=["active", "inactive"], product_id=product.id)
    return [_Item(p) for p in seeded]


def _service(db_session, tenant_key: str) -> ProjectService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return ProjectService(db_manager=MagicMock(), tenant_manager=tenant_manager, test_session=db_session)


async def _count_enrichment_sql(db_session, db_manager, service: ProjectService, items, tenant_key: str) -> int:
    sync_engine = db_manager.async_engine.sync_engine
    hits: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        if "agent_jobs" in lowered or "product_memory_entries" in lowered:
            hits.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        built = await service._build_mcp_project_list(items, depth=2, tenant_key=tenant_key)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    assert len(built) == len(items)
    for row in built:
        assert row["agent_summary"]["agent_count"] == _JOBS_PER_PROJECT
        assert len(row["agent_details"]) == _JOBS_PER_PROJECT
        assert len(row["memory_entries"]) == _ENTRIES_PER_PROJECT

    return len(hits)


@pytest.mark.asyncio
async def test_be6067_enrichment_sql_is_bounded_and_project_count_independent(db_session, db_manager, test_tenant_key):
    items = await _seed_enriched_projects(db_session, test_tenant_key, _N_LARGE)
    assert len(items) >= _N_LARGE, f"expected >= {_N_LARGE} seeded projects, got {len(items)}"
    small_items = items[:_N_SMALL]
    large_items = items

    small_sql = await _count_enrichment_sql(
        db_session, db_manager, _service(db_session, test_tenant_key), small_items, test_tenant_key
    )
    large_sql = await _count_enrichment_sql(
        db_session, db_manager, _service(db_session, test_tenant_key), large_items, test_tenant_key
    )

    assert small_sql == _EXPECTED_ENRICHMENT_QUERIES, (
        f"depth-2 enrichment over {_N_SMALL} projects issued {small_sql} statements "
        f"against agent_jobs/product_memory_entries (expected {_EXPECTED_ENRICHMENT_QUERIES} grouped-IN queries)"
    )
    assert large_sql == small_sql, (
        f"N+1 REGRESSION: enrichment SQL scaled with project count — {small_sql} for {_N_SMALL} projects "
        f"vs {large_sql} for {_N_LARGE}. The /mcp agent path must issue a project-count-independent "
        f"(grouped) query set, not one query per project."
    )
