# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for StatisticsService (BE-5022b).

Verifies that the service layer correctly wraps the statistics repositories
and enforces tenant isolation on all analytics queries.

These tests seed a known mix of rows into the real test database and assert the
exact non-zero counts the service returns. The previous version asserted only
key-shape and zero-counts on an empty tenant, so a broken aggregation/WHERE
clause (e.g. a dropped tenant_key filter or a miscounted status) would have
passed silently. A second tenant is seeded to prove cross-tenant isolation.
"""

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
    """Create StatisticsService instance with test session."""
    return StatisticsService(
        db_manager=db_manager,
        test_session=db_session,
    )


def _project(tenant_key, status, *, series, product_id, **extra):
    # product_id intentionally left NULL: an "only one active project per product"
    # partial unique index (idx_project_single_active_per_product) would otherwise
    # reject multiple active projects sharing a product. NULLs are distinct there, so
    # the seeded mix of active projects is allowed without coupling each to its own
    # product.
    #
    # ``series`` is REQUIRED and must come from a per-fixture counter, never a
    # random draw: uq_project_taxonomy_active is NULLS NOT DISTINCT, so the NULL
    # product_id/project_type_id/subseries columns compare EQUAL and two live rows
    # that drew the same number collide with an IntegrityError.
    #
    # BE-9429 corrects the second half of what this comment used to say. It read
    # "the plain Index() in models/projects.py does not carry the flag, so the
    # model file alone reads as safe and is not the authority" -- and concluded the
    # MIGRATION governs. For this suite it does not: the pytest schema is built by
    # Base.metadata.create_all(), so the MODEL is the authority here, and while it
    # omitted the flag this index could not reject anything in CI (measured: all
    # seven giljo_mcp_test* databases carried indnullsnotdistinct = false). The
    # model now declares it and the two layers agree, which is what makes the
    # constraint described above real in the test schema as well as in production.
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
    """Seed tenant A with a known row mix; tenant B with 2 projects (isolation).

    Tenant A totals: 7 projects (4 active incl. 1 staged, 2 completed, 1 cancelled),
    5 messages (2 pending / 1 ack / 1 completed / 1 failed), 3 agent executions
    (working / waiting / complete), 2 tasks (1 completed / 1 pending).
    """
    tenant_a = test_tenant_key
    tenant_b = f"tk_b_{uuid4().hex[:12]}"  # distinct tenant; tenant_key is VARCHAR(36)
    series = count(1)

    with tenant_session_context(db_session, tenant_a):
        product_a = Product(tenant_key=tenant_a, name="Product A", description="d", is_active=True)
        db_session.add(product_a)
        await db_session.flush()

        # BE-9437: product_id is NOT NULL, so every row names a product. The four
        # ACTIVE ones get one EACH -- idx_project_single_active_per_product allows a
        # single active project per product, which is what the old "product_id
        # intentionally left NULL" note was dodging. completed/cancelled rows fall
        # outside that index's predicate and can share product_a.
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
    """System stats should return all expected metric keys."""
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
    """System stats must report the exact seeded counts (catches broken aggregation)."""
    result = await stats_service.get_system_stats(seeded_stats["tenant_a"])

    assert result["total_projects"] == 7
    assert result["active_projects"] == 4  # 3 plain + 1 staged-but-active
    assert result["completed_projects"] == 2
    assert result["projects_cancelled"] == 1
    assert result["projects_staged"] == 1
    assert result["total_messages"] == 5
    assert result["pending_messages"] == 2
    assert result["total_agents"] == 3
    assert result["active_agents"] == 2  # working + waiting
    assert result["total_jobs_completed"] == 1  # complete
    assert result["total_tasks"] == 2
    assert result["completed_tasks"] == 1


@pytest.mark.asyncio
async def test_get_system_stats_isolates_tenants(stats_service, seeded_stats):
    """A second tenant sees only its own rows — proves the tenant_key filter."""
    tenant_a = await stats_service.get_system_stats(seeded_stats["tenant_a"])
    tenant_b = await stats_service.get_system_stats(seeded_stats["tenant_b"])

    assert tenant_a["total_projects"] == 7
    assert tenant_b["total_projects"] == 2  # only tenant B's own projects
    assert tenant_b["total_messages"] == 0
    assert tenant_b["total_agents"] == 0


@pytest.mark.asyncio
async def test_get_system_stats_unknown_tenant_returns_zeros(stats_service):
    """An unseeded tenant returns zeros (empty-path smoke)."""
    result = await stats_service.get_system_stats("nonexistent_tenant_key")
    assert result["total_projects"] == 0
    assert result["total_agents"] == 0
    assert result["total_messages"] == 0


@pytest.mark.asyncio
async def test_get_dashboard_stats_returns_expected_keys(stats_service, test_tenant_key):
    """Dashboard stats should return all expected top-level keys."""
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
        "total_commits",  # BE-6078
    }
    assert set(result.keys()) == expected_keys


@pytest.mark.asyncio
async def test_get_total_commits_counts_all_git_commits(stats_service, db_session, test_tenant_key):
    """BE-6078: total_commits sums jsonb_array_length(git_commits) across ALL
    product_memory_entries — not the capped 10-item preview. Tenant-scoped and
    honors the per-product dashboard filter; a foreign tenant's commits and
    other-product commits must not leak into a product-filtered count."""
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
                _entry(tenant_a, product_a1.id, 1, 3),  # 3 commits
                _entry(tenant_a, product_a1.id, 2, 4),  # 4 commits
                _entry(tenant_a, product_a1.id, 3, 0),  # empty array contributes 0
                _entry(tenant_a, product_a2.id, 1, 5),  # other product: 5 commits
            ]
        )
        await db_session.flush()

    with tenant_session_context(db_session, tenant_b):
        product_b = Product(tenant_key=tenant_b, name="PB", description="d", is_active=True)
        db_session.add(product_b)
        await db_session.flush()
        db_session.add(_entry(tenant_b, product_b.id, 1, 99))  # foreign tenant: must not leak
        await db_session.flush()

    # Tenant-wide (all products for tenant A): 3 + 4 + 0 + 5 = 12.
    all_products = await stats_service.get_dashboard_stats(tenant_a)
    assert all_products["total_commits"] == 12

    # Product-filtered to product_a1: 3 + 4 + 0 = 7 (excludes product_a2 and tenant B).
    filtered = await stats_service.get_dashboard_stats(tenant_a, product_id=str(product_a1.id))
    assert filtered["total_commits"] == 7

    # Foreign tenant sees only its own commits (99), proving isolation.
    foreign = await stats_service.get_dashboard_stats(tenant_b)
    assert foreign["total_commits"] == 99


@pytest.mark.asyncio
async def test_agent_role_distribution_ticker_and_folding(db_session, test_tenant_key):
    """Agent Roles pill: the ticker counts every agent an orchestrator spawned,
    the bar categorizes them by base role.

    Regression for the Dashboard reading "0 spawned": the prior query counted
    ONLY executions whose agent_name exactly matched a configured template, so
    specialized subagent names (implementer-backend / implementer-frontend) and
    template-less jobs were silently dropped. This asserts:
      - implementer-backend + implementer-frontend fold into "implementer";
      - a template-linked (FK) execution counts under its template;
      - the orchestrator/conductor itself is excluded (it is not spawned BY an
        orchestrator);
      - a spawned name that maps to no template still counts (its own segment);
      - the ticker (sum of segment counts) equals the total workers spawned.
    """
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

        # Orchestrator — excluded from the ticker (it is the assigner).
        _exec(_job("orchestrator"), "orchestrator", "orchestrator")
        # Two implementer variants (name-path, no template_id) — fold to implementer.
        _exec(_job("Backend-Templates-Removal"), "Backend-Templates-Removal", "implementer-backend")
        _exec(_job("Frontend-Templates-Removal"), "Frontend-Templates-Removal", "implementer-frontend")
        # One more backend implementer → implementer total = 3.
        _exec(_job("Backend-2"), "Backend-2", "implementer-backend")
        # Exact template-name match.
        _exec(_job("tester"), "tester", "tester")
        # FK path: job carries a template_id (reviewer) regardless of agent_name.
        _exec(_job("Code Checker", template_id=reviewer.id), "Code Checker", "code-checker")
        # A spawned agent that maps to no template — still counts under its own label.
        _exec(_job("data-wrangler"), "data-wrangler", "data-wrangler")
        await db_session.flush()

    repo = JobStatisticsRepository(None)
    with tenant_session_context(db_session, tenant):
        dist = await repo.get_agent_role_distribution(db_session, tenant)
    by_label = {seg["label"]: seg["count"] for seg in dist}

    assert by_label["Implementer"] == 3  # backend + backend + frontend, folded
    assert by_label["Tester"] == 1
    assert by_label["Reviewer"] == 1  # via FK template_id, not agent_name
    assert by_label["Data Wrangler"] == 1  # unmatched name still counts
    assert "Orchestrator" not in by_label  # the assigner is not a spawned agent

    ticker = sum(seg["count"] for seg in dist)
    assert ticker == 6  # 3 impl + 1 tester + 1 reviewer + 1 wrangler; orchestrator excluded


@pytest.mark.asyncio
async def test_get_system_stats_uses_single_session(stats_service, monkeypatch):
    """BE-6063a A1: all 13 counts must share ONE session, not open one each.

    Pins the round-trip collapse (landed in f023044ce) so the BE-6063 off-loop /
    tenant-guard follow-ups (links b/c) cannot regress ``get_system_stats`` back
    to a session-per-count fan-out on the single sync worker. Spies on
    ``_get_session`` and asserts exactly one ``async with`` is entered for the
    full set of counts.
    """
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


# ============================================================================
# Trashed-product liveness on the dashboard
#
# ``ProductLifecycleService.delete_product`` stamps ``deleted_at`` on the
# product row ALONE -- nothing cascades. The dashboard readers therefore have to
# revalidate the product each row points at, or a trashed product keeps feeding
# the dashboard for the whole recovery window.
#
# These scenarios seed REAL rows because the defect is predicate-shaped: a mock
# cannot see a missing WHERE clause.
# ============================================================================


def _memory_entry(tenant_key, product_id, sequence, commit_count, **extra):
    """Build one 360 memory entry carrying ``commit_count`` git commits."""
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
    """Four products across the three states a tenant can actually hold.

    * **Live** -- ``is_active=True``, not deleted. 1 memory entry (3 commits),
      1 user-deleted entry (7 commits), 1 live project, 1 soft-deleted project,
      1 live COMPLETED project (BE-9354's live-row control).
    * **Dormant** -- ``is_active=False``, NOT deleted. The discriminator between
      the two candidate predicates on the MEMORY/commits surface:
      ``deactivate_product`` clears ``is_active`` without trashing, so a fix keyed
      on ``is_active`` instead of ``deleted_at`` would wrongly hide this product's
      data. 1 entry (2 commits). Its only project is soft-deleted, ON PURPOSE --
      that is what makes it report a zero project count instead of vanishing.
    * **Deactivated** -- ``is_active=False``, NOT deleted, same state as Dormant
      but carrying a VISIBLE completed project. Dormant cannot serve this role:
      giving it a live project would flip its zero-count guard. This is the
      discriminator on the RECENT-PROJECTS surface, and it is the only row where
      ``is_active`` and ``deleted_at`` disagree about a name the dashboard renders.
      1 live COMPLETED project, no memory entries (the commits totals stay as they
      were).
    * **Trashed** -- ``is_active=False`` AND ``deleted_at`` set, which is exactly
      what ``delete_product`` writes. 1 entry (5 commits), 1 live project,
      1 live COMPLETED project.

    BE-9354 also seeds one live COMPLETED project with NO product at all.
    ``get_recent_projects`` selects only ``status == COMPLETED`` with a non-NULL
    ``completed_at``, so the four completed rows above are the ONLY ones that
    surface there -- the active/soft-deleted rows are invisible to it by design.

    Only one product per tenant may be active (idx_product_single_active_per_tenant)
    -- three of the four are ``is_active=False``, so they do not collide -- and only
    one project per product may be active (idx_project_single_active_per_product);
    the seed honours both rather than working around them.
    """
    tenant = test_tenant_key
    now = datetime.now(UTC)
    series = count(1)

    with tenant_session_context(db_session, tenant):
        live = Product(tenant_key=tenant, name="Live Product", description="d", is_active=True)
        dormant = Product(tenant_key=tenant, name="Dormant Product", description="d", is_active=False)
        # BE-9354: a SECOND deactivated-but-not-trashed product. Deliberately not
        # Dormant -- see the docstring; Dormant's zero project count is its own guard.
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

        # status='active' is unique per product, so the soft-deleted project
        # carries a non-active status.
        db_session.add_all(
            [
                _project(tenant, "active", series=next(series), product_id=live.id),
                _project(tenant, "completed", series=next(series), product_id=live.id, deleted_at=now),
                # Dormant's ONLY project is soft-deleted. This pins the project
                # predicate to the join's ON clause: moved to the WHERE, the
                # outer-join row is filtered out and the product itself vanishes
                # from the rollup instead of reporting zero.
                _project(tenant, "completed", series=next(series), product_id=dormant.id, deleted_at=now),
                _project(tenant, "active", series=next(series), product_id=trashed.id),
                # BE-9354: the three rows get_recent_projects can actually see.
                # completed_at is REQUIRED -- the query filters on it, so a
                # completed project without one never reaches the dashboard.
                _project(tenant, "completed", series=next(series), product_id=trashed.id, completed_at=now),
                _project(tenant, "completed", series=next(series), product_id=live.id, completed_at=now),
                # The is_active-vs-deleted_at discriminator for this surface: a
                # deactivated product is NOT a trashed one, and its name must keep
                # rendering. Without this row both predicates pass every test here.
                _project(tenant, "completed", series=next(series), product_id=deactivated.id, completed_at=now),
                # BE-9437 removed the "no product at all" row that sat here.
                # projects.product_id is NOT NULL now, so a product-less project is
                # not a real row any more and seeding one would pin a state the
                # database cannot hold. Its test was deleted with it.
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
    """The 360 Memories panel must not serve a trashed product's entries."""
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    product_names = {m["product_name"] for m in stats["recent_memories"]}
    assert "Trashed Product" not in product_names, (
        f"a trashed product's 360 memory entries are still on the dashboard, got={sorted(product_names)}"
    )


@pytest.mark.asyncio
async def test_recent_memories_exclude_user_deleted_entries(stats_service, trashed_product_dashboard):
    """A user-deleted entry must not be served, matching every sibling reader."""
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    sequences = {m["summary"] for m in stats["recent_memories"]}
    assert "summary for sequence 2" not in sequences, (
        f"a user-deleted 360 memory entry is still on the dashboard, got={sorted(sequences)}"
    )


@pytest.mark.asyncio
async def test_total_commits_excludes_trashed_and_deleted_entries(stats_service, trashed_product_dashboard):
    """The Commits tile counts live entries of non-trashed products: 3 + 2 = 5, not 17."""
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    assert stats["total_commits"] == 5, (
        "the Commits tile is counting a trashed product's (5) and/or a user-deleted "
        f"entry's (7) commits, got={stats['total_commits']}"
    )


@pytest.mark.asyncio
async def test_product_counts_exclude_a_trashed_product(stats_service, trashed_product_dashboard):
    """The per-product rollup must not list a trashed product."""
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    names = {p["product_name"] for p in stats["products"]}
    assert "Trashed Product" not in names, f"a trashed product is still listed, got={sorted(names)}"


@pytest.mark.asyncio
async def test_product_project_count_excludes_soft_deleted_projects(stats_service, trashed_product_dashboard):
    """The per-product project count must agree with the status distribution.

    The live product owns two live projects (one active, one completed) and one
    soft-deleted project; the badge counted all three, while
    ``get_project_status_distribution`` counted two. Asserting the exact live
    total still catches a dropped ``deleted_at`` predicate -- that would read 3.
    """
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    counts = {p["product_name"]: p["project_count"] for p in stats["products"]}
    assert counts.get("Live Product") == 2, f"the project count badge is counting soft-deleted projects, got={counts}"
    # A product whose only project is trashed still exists — it reports zero,
    # it does not disappear.
    assert counts.get("Dormant Product") == 0, (
        f"a product whose only project is soft-deleted must report 0, not vanish, got={counts}"
    )


@pytest.mark.asyncio
async def test_live_product_dashboard_data_is_still_served(stats_service, trashed_product_dashboard):
    """Over-exclusion guard: hiding a LIVE product's data is worse than the bug.

    Every predicate added for the trashed-product fix is inverted by this
    scenario -- a fix that empties the dashboard cannot pass.
    """
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    served = {(m["product_name"], m["summary"]) for m in stats["recent_memories"]}
    assert ("Live Product", "summary for sequence 1") in served, (
        f"a live product's 360 memory entry must still be served, got={sorted(served)}"
    )
    # The is_active-vs-deleted_at discriminator: a DEACTIVATED product is not a
    # trashed one, and its data stays on the dashboard.
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


# ----------------------------------------------------------------------------
# BE-9354 -- the Recent Projects list
#
# ``get_recent_projects`` outer-joined ``Product`` on id + tenant_key with no
# liveness predicate, so a trashed product's NAME kept rendering next to its
# completed projects (RecentProjectsList.vue:18) for the whole recovery window.
#
# The fix nulls the NAME; it does not hide the projects. Project visibility is
# deliberately not keyed on parent-product liveness anywhere in this codebase --
# see the note at the head of ``ProjectRepository._build_list_conditions``.
# ----------------------------------------------------------------------------


def _recent_by_product(stats, product_id):
    """The recent-projects rows owned by ``product_id`` (None == no product)."""
    wanted = str(product_id) if product_id is not None else None
    return [p for p in stats["recent_projects"] if p["product_id"] == wanted]


@pytest.mark.asyncio
async def test_recent_projects_null_the_name_of_a_trashed_parent_product(stats_service, trashed_product_dashboard):
    """A trashed product's completed project stays listed, but loses its name.

    Both halves are load-bearing. Dropping the project instead would be the
    rejected fix: it would hide the project here while its tasks, chain runs,
    roadmap items and jobs all stayed visible.
    """
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
    """Over-exclusion guard: a fix that nulled EVERY name would pass without this."""
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    owned = _recent_by_product(stats, trashed_product_dashboard["live_id"])
    assert len(owned) == 1, f"a live product's completed project vanished, got={stats['recent_projects']}"
    assert owned[0]["product_name"] == "Live Product", (
        f"a live product must still be named beside its project, got={owned[0]['product_name']!r}"
    )


@pytest.mark.asyncio
async def test_recent_projects_still_name_a_deactivated_parent_product(stats_service, trashed_product_dashboard):
    """Predicate discriminator: deactivating a product is NOT trashing it.

    ``deactivate_product`` (POST /products/{id}/deactivate,
    api/endpoints/products/lifecycle.py) clears ``is_active`` and leaves
    ``deleted_at`` NULL. It is a live, reachable path today.

    Without this case the join predicate could be ``Product.is_active.is_(True)``
    and every other test in this file still passes -- they only exercise the two
    states where the two candidate predicates agree (live+active, trashed+inactive).
    That mutant would strip the name from every deactivated product's projects with
    no trash entry to explain it. This is the only row where the two disagree about
    a name the dashboard actually renders.
    """
    stats = await stats_service.get_dashboard_stats(trashed_product_dashboard["tenant"])

    owned = _recent_by_product(stats, trashed_product_dashboard["deactivated_id"])
    assert len(owned) == 1, (
        f"a deactivated (not trashed) product's completed project vanished, got={stats['recent_projects']}"
    )
    assert owned[0]["product_name"] == "Deactivated Product", (
        "a deactivated product is not a trashed one -- its name must still render. "
        f"A join keyed on is_active instead of deleted_at gets here, got={owned[0]['product_name']!r}"
    )


# BE-9437 DELETED test_recent_projects_still_include_a_project_with_no_product.
# It seeded a completed project with product_id NULL and asserted the dashboard
# still returned it -- an outer-join guard resting on "projects.product_id is
# nullable". That premise is gone: the column is NOT NULL and the FK cascades, so
# there is no way to reach a projects row whose product row is absent, and the
# test could only ever have failed by seeding a state the database now rejects.
# The LEFT JOIN it protected is still covered, by the two tests above it: a
# TRASHED parent product must null the name rather than drop the row, and a
# DEACTIVATED one must keep rendering it. Those exercise the same ON-clause
# mistake through a state that still exists.


# ============================================================================
# BE-9355 -- trashed PROJECTS on the statistics surfaces
#
# ``ProjectDeletionService.delete_project`` stamps ``status='deleted'`` AND
# ``deleted_at`` together (project_deletion_service.py:99-100); ``restore_project``
# clears both (:558-561). It is the only writer of ``Project.deleted_at``, and it
# has written the pair since the feature shipped -- so a trashed row's ``status``
# is always ``'deleted'``.
#
# That equivalence is why ``count_projects_by_status`` is NOT inflated (nothing
# asks for the 'deleted' bucket) while its siblings, which key off ``status``-
# independent columns, ARE: ``staging_status`` and ``execution_mode`` both survive
# a soft delete untouched, and ``count_total_projects`` counts everything.
#
# Real rows, because the defect is a missing WHERE clause and a mock cannot see one.
# ============================================================================


@pytest_asyncio.fixture
async def trashed_projects_stats(db_session, test_tenant_key):
    """3 live projects and 5 trashed ones, deliberately asymmetric on every axis.

    Asymmetry is the point: for each count under test the correct answer, the
    unfiltered answer, and the INVERTED answer are three different numbers, so no
    assertion can pass by landing on the wrong side of the boundary. A balanced
    seed would have been blind to inversion.

    The two ``cancelled`` rows exist for ``count_projects_by_status``. Without a
    trashed row carrying a status a caller actually asks for, removing that
    predicate reddens nothing and the site would ship unpinned.

    ``product_id`` is left NULL so ``idx_project_single_active_per_product`` does
    not reject the seeded mix.
    """
    tenant = test_tenant_key
    now = datetime.now(UTC)
    series = count(1)

    with tenant_session_context(db_session, tenant):
        # BE-9437: one product suffices -- exactly one row here is active, and
        # idx_project_single_active_per_product constrains nothing else.
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
                # Trashed rows carry status='deleted' because that is what the
                # single writer stamps alongside deleted_at...
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
                # ...except these two. A trashed project whose status is something
                # a caller DOES query is the only shape that can catch a missing
                # predicate in count_projects_by_status. Reachable in practice from
                # any future writer that stamps deleted_at without rewriting status.
                _project(tenant, "cancelled", series=next(series), deleted_at=now, product_id=mix_product.id),
                _project(tenant, "cancelled", series=next(series), deleted_at=now, product_id=mix_product.id),
            ]
        )
        await db_session.flush()

    return tenant


@pytest.mark.asyncio
async def test_system_stats_total_projects_excludes_trashed(stats_service, trashed_projects_stats):
    """The Projects total must not count what the user put in the trash."""
    result = await stats_service.get_system_stats(trashed_projects_stats)

    assert result["total_projects"] == 3, (
        f"total_projects is counting soft-deleted projects (3 live, 5 trashed), got={result['total_projects']}"
    )


@pytest.mark.asyncio
async def test_system_stats_projects_staged_excludes_trashed(stats_service, trashed_projects_stats):
    """``staging_status`` survives a soft delete, so this count inflated too."""
    result = await stats_service.get_system_stats(trashed_projects_stats)

    assert result["projects_staged"] == 1, (
        "projects_staged is counting soft-deleted projects; a trashed project keeps its "
        f"staging_status, got={result['projects_staged']}"
    )


@pytest.mark.asyncio
async def test_execution_mode_distribution_excludes_trashed(stats_service, trashed_projects_stats):
    """``execution_mode_dist`` must agree with ``project_status_dist`` beside it.

    Both fields are served in the same ``get_dashboard_stats`` payload and
    ``get_project_status_distribution`` already excluded trashed rows, so the one
    response carried two disagreeing project totals. (An API-level disagreement:
    ``execution_mode_dist`` is not read by the bundled frontend.)
    """
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
    """Over-exclusion guard: every predicate added here is inverted by this scenario.

    A fix that swapped ``is_(None)`` for ``is_not(None)`` -- or that dropped live
    rows some other way -- reports 3 totals, 2 staged, and an ``unset`` bucket,
    and fails here rather than passing on an empty result.
    """
    result = await stats_service.get_system_stats(trashed_projects_stats)

    assert result["active_projects"] == 1, f"the live active project must still be counted, got={result}"
    assert result["completed_projects"] == 1, f"the live completed project must still be counted, got={result}"


@pytest.mark.asyncio
async def test_status_counts_exclude_trashed_projects(stats_service, trashed_projects_stats):
    """Regression pin for ``count_projects_by_status``.

    That site is hygiene rather than a live defect: the sole writer of
    ``Project.deleted_at`` stamps ``status='deleted'`` with it, so in the shipped
    product a trashed row lands in a bucket no caller queries. The predicate is
    what stops those two liveness facts depending on each other -- and this test
    is what proves the predicate is load-bearing, by seeding the shape the
    invariant currently rules out: trashed rows still carrying 'cancelled'.

    1 live cancelled against 2 trashed cancelled: unfiltered reports 3, inverted
    reports 2, correct reports 1.
    """
    result = await stats_service.get_system_stats(trashed_projects_stats)

    assert result["projects_cancelled"] == 1, (
        "count_projects_by_status is counting soft-deleted projects; only the 1 live "
        f"cancelled project should count, got={result['projects_cancelled']}"
    )


@pytest.mark.asyncio
async def test_aggregated_project_stats_exclude_trashed(db_manager, db_session, trashed_projects_stats):
    """``get_project_stats_aggregated`` has no production caller today.

    Its only other caller is ``tests/stress/test_be6063b_stats_eventloop_lag_spike.py``.
    The predicate is added for consistency inside the file -- so that whichever
    paginated project surface picks this method up later does not inherit the
    defect -- and this test is what keeps that claim honest.
    """
    repo = ProductStatisticsRepository(db_manager)

    with tenant_session_context(db_session, trashed_projects_stats):
        rows = await repo.get_project_stats_aggregated(db_session, trashed_projects_stats, limit=100)

    assert len(rows) == 3, f"the aggregated project page is returning soft-deleted projects, got={len(rows)}"
    assert {row[0].status for row in rows} == {"active", "completed", "cancelled"}, (
        f"a trashed project leaked into the aggregated page, got={sorted(row[0].status for row in rows)}"
    )
