# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from itertools import count
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentExecution, AgentJob, Message, Product, Project, Task
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.platform_registry import MODE_MULTI_TERMINAL, MODE_SUBAGENT
from giljo_mcp.repositories.product_statistics_repository import ProductStatisticsRepository
from giljo_mcp.services.statistics_service import StatisticsService


@pytest_asyncio.fixture
async def stats_service(db_manager, db_session):
    return StatisticsService(
        db_manager=db_manager,
        test_session=db_session,
    )


def _project(tenant_key, status, *, series, product_id, **extra):
    return Project(
        tenant_key=tenant_key,
        product_id=product_id,
        name="Stats Project",
        description="seeded for statistics tests",
        mission="seeded mission",
        status=status,
        series_number=series,
        **extra,
    )


@pytest_asyncio.fixture
async def seeded_stats(db_session, test_tenant_key):
    tenant_a = test_tenant_key
    tenant_b = f"tk_b_{uuid4().hex[:12]}"
    series = count(1)

    with tenant_session_context(db_session, tenant_a):
        product_a = Product(tenant_key=tenant_a, name="Product A", description="d", is_active=True)
        db_session.add(product_a)
        await db_session.flush()

        active_products = [
            Product(tenant_key=tenant_a, name=f"Product A{i}", description="d", is_active=False) for i in range(3)
        ]
        db_session.add_all(active_products)
        await db_session.flush()

        projects = [
            *[_project(tenant_a, "active", series=next(series), product_id=ap.id) for ap in active_products],
            _project(
                tenant_a,
                "active",
                series=next(series),
                staging_status="staging_complete",
                product_id=product_a.id,
            ),
            *[_project(tenant_a, "completed", series=next(series), product_id=product_a.id) for _ in range(2)],
            _project(tenant_a, "cancelled", series=next(series), product_id=product_a.id),
        ]
        db_session.add_all(projects)
        await db_session.flush()

        msg_project = projects[0]
        for status in ("pending", "pending", "acknowledged", "completed", "failed"):
            db_session.add(Message(tenant_key=tenant_a, project_id=msg_project.id, content="hi", status=status))

        job = AgentJob(
            job_id=str(uuid4()),
            tenant_key=tenant_a,
            project_id=msg_project.id,
            mission="seeded",
            job_type="implementer",
            status="active",
            created_at=datetime.now(UTC),
        )
        db_session.add(job)
        await db_session.flush()
        for status in ("working", "waiting", "complete"):
            db_session.add(
                AgentExecution(
                    job_id=job.job_id,
                    agent_id=str(uuid4()),
                    tenant_key=tenant_a,
                    agent_display_name="implementer",
                    agent_name=f"implementer-{status}",
                    status=status,
                    completed_at=datetime.now(UTC) if status == "complete" else None,
                )
            )

        db_session.add_all(
            [
                Task(tenant_key=tenant_a, product_id=product_a.id, title="t1", status="completed"),
                Task(tenant_key=tenant_a, product_id=product_a.id, title="t2", status="pending"),
            ]
        )
        await db_session.flush()

    with tenant_session_context(db_session, tenant_b):
        product_b = Product(tenant_key=tenant_b, name="Product B", description="d", is_active=True)
        db_session.add(product_b)
        await db_session.flush()
        product_b2 = Product(tenant_key=tenant_b, name="Product B2", description="d", is_active=False)
        db_session.add(product_b2)
        await db_session.flush()
        db_session.add_all(
            [_project(tenant_b, "active", series=next(series), product_id=pid) for pid in (product_b.id, product_b2.id)]
        )
        await db_session.flush()

    return {"tenant_a": tenant_a, "tenant_b": tenant_b}


@pytest.mark.asyncio
async def test_get_system_stats_returns_expected_keys(stats_service, test_tenant_key):
    result = await stats_service.get_system_stats(test_tenant_key)
    expected_keys = {
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
    assert set(result.keys()) == expected_keys


@pytest.mark.asyncio
async def test_get_system_stats_counts_seeded_data(stats_service, seeded_stats):
    result = await stats_service.get_system_stats(seeded_stats["tenant_a"])

    assert result["total_projects"] == 7
    assert result["active_projects"] == 4
    assert result["completed_projects"] == 2
    assert result["projects_cancelled"] == 1
    assert result["projects_staged"] == 1
    assert result["total_messages"] == 5
    assert result["pending_messages"] == 2
    assert result["total_agents"] == 3
    assert result["active_agents"] == 2
    assert result["total_jobs_completed"] == 1
    assert result["total_tasks"] == 2
    assert result["completed_tasks"] == 1


@pytest.mark.asyncio
async def test_get_system_stats_isolates_tenants(stats_service, seeded_stats):
    tenant_a = await stats_service.get_system_stats(seeded_stats["tenant_a"])
    tenant_b = await stats_service.get_system_stats(seeded_stats["tenant_b"])

    assert tenant_a["total_projects"] == 7
    assert tenant_b["total_projects"] == 2
    assert tenant_b["total_messages"] == 0
    assert tenant_b["total_agents"] == 0


@pytest.mark.asyncio
async def test_get_system_stats_unknown_tenant_returns_zeros(stats_service):
    result = await stats_service.get_system_stats("nonexistent_tenant_key")
    assert result["total_projects"] == 0
    assert result["total_agents"] == 0
    assert result["total_messages"] == 0


@pytest.mark.asyncio
async def test_get_dashboard_stats_returns_expected_keys(stats_service, test_tenant_key):
    result = await stats_service.get_dashboard_stats(test_tenant_key)
    expected_keys = {
        "project_status_dist",
        "taxonomy_dist",
        "agent_role_dist",
        "recent_projects",
        "recent_memories",
        "task_status_dist",
        "execution_mode_dist",
        "products",
        "total_commits",
    }
    assert set(result.keys()) == expected_keys


@pytest.mark.asyncio
async def test_get_total_commits_counts_all_git_commits(stats_service, db_session, test_tenant_key):
    from giljo_mcp.models.product_memory_entry import ProductMemoryEntry

    tenant_a = test_tenant_key
    tenant_b = f"tk_b_{uuid4().hex[:12]}"

    def _commit(n: int) -> dict:
        return {"sha": f"{n:040x}", "message": f"commit {n}"}

    def _entry(tenant_key, product_id, seq, commit_count):
        return ProductMemoryEntry(
            tenant_key=tenant_key,
            product_id=product_id,
            sequence=seq,
            entry_type="project_completion",
            source="write_360_memory_v1",
            timestamp=datetime.now(UTC),
            git_commits=[_commit(i) for i in range(commit_count)],
        )

    with tenant_session_context(db_session, tenant_a):
        product_a1 = Product(tenant_key=tenant_a, name="PA1", description="d", is_active=True)
        product_a2 = Product(tenant_key=tenant_a, name="PA2", description="d", is_active=False)
        db_session.add_all([product_a1, product_a2])
        await db_session.flush()
        db_session.add_all(
            [
                _entry(tenant_a, product_a1.id, 1, 3),
                _entry(tenant_a, product_a1.id, 2, 4),
                _entry(tenant_a, product_a1.id, 3, 0),
                _entry(tenant_a, product_a2.id, 1, 5),
            ]
        )
        await db_session.flush()

    with tenant_session_context(db_session, tenant_b):
        product_b = Product(tenant_key=tenant_b, name="PB", description="d", is_active=True)
        db_session.add(product_b)
        await db_session.flush()
        db_session.add(_entry(tenant_b, product_b.id, 1, 99))
        await db_session.flush()

    all_products = await stats_service.get_dashboard_stats(tenant_a)
    assert all_products["total_commits"] == 12

    filtered = await stats_service.get_dashboard_stats(tenant_a, product_id=str(product_a1.id))
    assert filtered["total_commits"] == 7

    foreign = await stats_service.get_dashboard_stats(tenant_b)
    assert foreign["total_commits"] == 99


@pytest.mark.asyncio
async def test_agent_role_distribution_ticker_and_folding(db_session, test_tenant_key):
    from giljo_mcp.models.templates import AgentTemplate
    from giljo_mcp.repositories.job_statistics_repository import JobStatisticsRepository

    tenant = test_tenant_key
    with tenant_session_context(db_session, tenant):
        impl = AgentTemplate(tenant_key=tenant, name="implementer", background_color="#aabbcc")
        tester = AgentTemplate(tenant_key=tenant, name="tester", background_color="#ddeeff")
        reviewer = AgentTemplate(tenant_key=tenant, name="reviewer", background_color="#123456")
        db_session.add_all([impl, tester, reviewer])
        await db_session.flush()

        role_product = Product(tenant_key=tenant, name="Role Dist Product", description="d", is_active=False)
        db_session.add(role_product)
        await db_session.flush()
        project = _project(tenant, "active", series=1, product_id=role_product.id)
        db_session.add(project)
        await db_session.flush()

        def _job(job_type, template_id=None):
            job = AgentJob(
                job_id=str(uuid4()),
                tenant_key=tenant,
                project_id=project.id,
                mission="m",
                job_type=job_type,
                status="active",
                template_id=template_id,
                created_at=datetime.now(UTC),
            )
            db_session.add(job)
            return job

        def _exec(job, display_name, agent_name):
            db_session.add(
                AgentExecution(
                    job_id=job.job_id,
                    agent_id=str(uuid4()),
                    tenant_key=tenant,
                    agent_display_name=display_name,
                    agent_name=agent_name,
                    status="working",
                    started_at=datetime.now(UTC),
                )
            )

        _exec(_job("orchestrator"), "orchestrator", "orchestrator")
        _exec(_job("Backend-Templates-Removal"), "Backend-Templates-Removal", "implementer-backend")
        _exec(_job("Frontend-Templates-Removal"), "Frontend-Templates-Removal", "implementer-frontend")
        _exec(_job("Backend-2"), "Backend-2", "implementer-backend")
        _exec(_job("tester"), "tester", "tester")
        _exec(_job("Code Checker", template_id=reviewer.id), "Code Checker", "code-checker")
        _exec(_job("data-wrangler"), "data-wrangler", "data-wrangler")
        await db_session.flush()

    repo = JobStatisticsRepository(None)
    with tenant_session_context(db_session, tenant):
        dist = await repo.get_agent_role_distribution(db_session, tenant)
    by_label = {seg["label"]: seg["count"] for seg in dist}

    assert by_label["Implementer"] == 3
    assert by_label["Tester"] == 1
    assert by_label["Reviewer"] == 1
    assert by_label["Data Wrangler"] == 1
    assert "Orchestrator" not in by_label

    ticker = sum(seg["count"] for seg in dist)
    assert ticker == 6


@pytest.mark.asyncio
async def test_get_system_stats_uses_single_session(stats_service, monkeypatch):
    real_get_session = stats_service._get_session
    calls = 0

    def _counting_get_session(tenant_key=None):
        nonlocal calls
        calls += 1
        return real_get_session(tenant_key)

    monkeypatch.setattr(stats_service, "_get_session", _counting_get_session)

    result = await stats_service.get_system_stats("any_tenant_key")

    assert calls == 1, f"expected one shared session for all counts, got {calls}"
    assert "total_projects" in result




def _memory_entry(tenant_key, product_id, sequence, commit_count, **extra):
    return ProductMemoryEntry(
        tenant_key=tenant_key,
        product_id=product_id,
        sequence=sequence,
        entry_type="project_completion",
        source="write_360_memory_v1",
        timestamp=datetime.now(UTC),
        summary=f"summary for sequence {sequence}",
        project_name=f"project for sequence {sequence}",
        git_commits=[{"sha": f"{n:040x}", "message": f"commit {n}"} for n in range(commit_count)],
        **extra,
    )


@pytest_asyncio.fixture
async def trashed_product_dashboard(db_session, test_tenant_key):
    tenant = test_tenant_key
    now = datetime.now(UTC)
    series = count(1)

    with tenant_session_context(db_session, tenant):
        live = Product(tenant_key=tenant, name="Live Product", description="d", is_active=True)
        dormant = Product(tenant_key=tenant, name="Dormant Product", description="d", is_active=False)
        deactivated = Product(tenant_key=tenant, name="Deactivated Product", description="d", is_active=False)
        trashed = Product(tenant_key=tenant, name="Trashed Product", description="d", is_active=False)
        db_session.add_all([live, dormant, deactivated, trashed])
        await db_session.flush()

        trashed.deleted_at = now

        db_session.add_all(
            [
                _memory_entry(tenant, live.id, 1, 3),
                _memory_entry(tenant, live.id, 2, 7, deleted_by_user=True),
                _memory_entry(tenant, dormant.id, 1, 2),
                _memory_entry(tenant, trashed.id, 1, 5),
            ]
        )

        db_session.add_all(
            [
                _project(tenant, "active", series=next(series), product_id=live.id),
                _project(tenant, "deleted", series=next(series), product_id=live.id, deleted_at=now),
                _project(tenant, "deleted", series=next(series), product_id=dormant.id, deleted_at=now),
                _project(tenant, "active", series=next(series), product_id=trashed.id),
                _project(tenant, "completed", series=next(series), product_id=trashed.id, completed_at=now),
                _project(tenant, "completed", series=next(series), product_id=live.id, completed_at=now),
                _project(tenant, "completed", series=next(series), product_id=deactivated.id, completed_at=now),
            ]
        )
        await db_session.flush()

    return {
        "tenant": tenant,
        "live_id": live.id,
        "deactivated_id": deactivated.id,
        "trashed_id": trashed.id,
    }


@pytest.mark.asyncio
async def test_recent_memories_exclude_a_trashed_products_entries(stats_service, trashed_product_dashboard):
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    product_names = {m["product_name"] for m in stats["recent_memories"]}
    assert "Trashed Product" not in product_names, (
        f"a trashed product's 360 memory entries are still on the dashboard, got={sorted(product_names)}"
    )


@pytest.mark.asyncio
async def test_recent_memories_exclude_user_deleted_entries(stats_service, trashed_product_dashboard):
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    sequences = {m["summary"] for m in stats["recent_memories"]}
    assert "summary for sequence 2" not in sequences, (
        f"a user-deleted 360 memory entry is still on the dashboard, got={sorted(sequences)}"
    )


@pytest.mark.asyncio
async def test_total_commits_excludes_trashed_and_deleted_entries(stats_service, trashed_product_dashboard):
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    assert stats["total_commits"] == 5, (
        "the Commits tile is counting a trashed product's (5) and/or a user-deleted "
        f"entry's (7) commits, got={stats['total_commits']}"
    )


@pytest.mark.asyncio
async def test_product_counts_exclude_a_trashed_product(stats_service, trashed_product_dashboard):
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    names = {p["product_name"] for p in stats["products"]}
    assert "Trashed Product" not in names, f"a trashed product is still listed, got={sorted(names)}"


@pytest.mark.asyncio
async def test_product_project_count_excludes_soft_deleted_projects(stats_service, trashed_product_dashboard):
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    counts = {p["product_name"]: p["project_count"] for p in stats["products"]}
    assert counts.get("Live Product") == 2, f"the project count badge is counting soft-deleted projects, got={counts}"
    assert counts.get("Dormant Product") == 0, (
        f"a product whose only project is soft-deleted must report 0, not vanish, got={counts}"
    )


@pytest.mark.asyncio
async def test_live_product_dashboard_data_is_still_served(stats_service, trashed_product_dashboard):
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    served = {(m["product_name"], m["summary"]) for m in stats["recent_memories"]}
    assert ("Live Product", "summary for sequence 1") in served, (
        f"a live product's 360 memory entry must still be served, got={sorted(served)}"
    )
    assert ("Dormant Product", "summary for sequence 1") in served, (
        f"a deactivated (not trashed) product's 360 memory entry must still be served, got={sorted(served)}"
    )
    assert stats["total_commits"] == 5, (
        f"live and deactivated products' commits must still be counted, got={stats['total_commits']}"
    )
    names = {p["product_name"] for p in stats["products"]}
    assert {"Live Product", "Dormant Product"} <= names, (
        f"live and deactivated products must still be listed, got={sorted(names)}"
    )




def _recent_by_product(stats, product_id):
    wanted = str(product_id) if product_id is not None else None
    return [p for p in stats["recent_projects"] if p["product_id"] == wanted]


@pytest.mark.asyncio
async def test_recent_projects_null_the_name_of_a_trashed_parent_product(stats_service, trashed_product_dashboard):
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    owned = _recent_by_product(stats, trashed_product_dashboard["trashed_id"])
    assert len(owned) == 1, (
        "a trashed product's completed project must still be listed -- this fix nulls "
        f"the name, it does not hide the project, got={stats['recent_projects']}"
    )
    assert owned[0]["product_name"] is None, (
        f"a trashed product's name is still rendering on the dashboard, got={owned[0]['product_name']!r}"
    )


@pytest.mark.asyncio
async def test_recent_projects_still_name_a_live_parent_product(stats_service, trashed_product_dashboard):
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    owned = _recent_by_product(stats, trashed_product_dashboard["live_id"])
    assert len(owned) == 1, f"a live product's completed project vanished, got={stats['recent_projects']}"
    assert owned[0]["product_name"] == "Live Product", (
        f"a live product must still be named beside its project, got={owned[0]['product_name']!r}"
    )


@pytest.mark.asyncio
async def test_recent_projects_still_name_a_deactivated_parent_product(stats_service, trashed_product_dashboard):
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    owned = _recent_by_product(stats, trashed_product_dashboard["deactivated_id"])
    assert len(owned) == 1, (
        f"a deactivated (not trashed) product's completed project vanished, got={stats['recent_projects']}"
    )
    assert owned[0]["product_name"] == "Deactivated Product", (
        "a deactivated product is not a trashed one -- its name must still render. "
        f"A join keyed on is_active instead of deleted_at gets here, got={owned[0]['product_name']!r}"
    )






@pytest_asyncio.fixture
async def trashed_projects_stats(db_session, test_tenant_key):
    tenant = test_tenant_key
    now = datetime.now(UTC)
    series = count(1)

    with tenant_session_context(db_session, tenant):
        mix_product = Product(tenant_key=tenant, name="Status Mix Product", description="d", is_active=False)
        db_session.add(mix_product)
        await db_session.flush()

        db_session.add_all(
            [
                _project(
                    tenant,
                    "active",
                    series=next(series),
                    staging_status="staged",
                    execution_mode=MODE_MULTI_TERMINAL,
                    product_id=mix_product.id,
                ),
                _project(
                    tenant, "completed", series=next(series), execution_mode=MODE_SUBAGENT, product_id=mix_product.id
                ),
                _project(
                    tenant, "cancelled", series=next(series), execution_mode=MODE_SUBAGENT, product_id=mix_product.id
                ),
                _project(
                    tenant,
                    "deleted",
                    series=next(series),
                    deleted_at=now,
                    staging_status="staging_complete",
                    execution_mode=MODE_MULTI_TERMINAL,
                    product_id=mix_product.id,
                ),
                _project(
                    tenant,
                    "deleted",
                    series=next(series),
                    deleted_at=now,
                    staging_status="staged",
                    product_id=mix_product.id,
                ),
                _project(
                    tenant,
                    "deleted",
                    series=next(series),
                    deleted_at=now,
                    execution_mode=MODE_SUBAGENT,
                    product_id=mix_product.id,
                ),
                _project(tenant, "deleted", series=next(series), deleted_at=now, product_id=mix_product.id),
                _project(tenant, "deleted", series=next(series), deleted_at=now, product_id=mix_product.id),
            ]
        )
        await db_session.flush()

    return tenant


@pytest.mark.asyncio
async def test_system_stats_total_projects_excludes_trashed(stats_service, trashed_projects_stats):
    result = await stats_service.get_system_stats(trashed_projects_stats)

    assert result["total_projects"] == 3, (
        f"total_projects is counting soft-deleted projects (3 live, 5 trashed), got={result['total_projects']}"
    )


@pytest.mark.asyncio
async def test_system_stats_projects_staged_excludes_trashed(stats_service, trashed_projects_stats):
    result = await stats_service.get_system_stats(trashed_projects_stats)

    assert result["projects_staged"] == 1, (
        "projects_staged is counting soft-deleted projects; a trashed project keeps its "
        f"staging_status, got={result['projects_staged']}"
    )


@pytest.mark.asyncio
async def test_execution_mode_distribution_excludes_trashed(stats_service, trashed_projects_stats):
    stats = await stats_service.get_dashboard_stats(trashed_projects_stats)

    assert stats["execution_mode_dist"] == {MODE_MULTI_TERMINAL: 1, MODE_SUBAGENT: 2}, (
        f"execution_mode_dist is counting soft-deleted projects, got={stats['execution_mode_dist']}"
    )
    assert sum(stats["project_status_dist"].values()) == 3, (
        "guard on the comparison itself: the status distribution must still see exactly the 3 live "
        f"projects, got={stats['project_status_dist']}"
    )


@pytest.mark.asyncio
async def test_live_projects_are_still_counted(stats_service, trashed_projects_stats):
    result = await stats_service.get_system_stats(trashed_projects_stats)

    assert result["active_projects"] == 1, f"the live active project must still be counted, got={result}"
    assert result["completed_projects"] == 1, f"the live completed project must still be counted, got={result}"


@pytest.mark.asyncio
async def test_status_counts_exclude_trashed_projects(stats_service, trashed_projects_stats):
    result = await stats_service.get_system_stats(trashed_projects_stats)

    assert result["projects_cancelled"] == 1, (
        "count_projects_by_status is counting soft-deleted projects; only the 1 live "
        f"cancelled project should count, got={result['projects_cancelled']}"
    )


@pytest.mark.asyncio
async def test_aggregated_project_stats_exclude_trashed(db_manager, db_session, trashed_projects_stats):
    repo = ProductStatisticsRepository(db_manager)

    with tenant_session_context(db_session, trashed_projects_stats):
        rows = await repo.get_project_stats_aggregated(db_session, trashed_projects_stats, limit=100)

    assert len(rows) == 3, f"the aggregated project page is returning soft-deleted projects, got={len(rows)}"
    assert {row[0].status for row in rows} == {"active", "completed", "cancelled"}, (
        f"a trashed project leaked into the aggregated page, got={sorted(row[0].status for row in rows)}"
    )
