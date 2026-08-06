# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9343 — ``completed_at`` is stamped by the SERVICE, never left to the caller.

The defect: a project could reach a terminal status with ``completed_at`` still
NULL, because the timestamp was written by *some* callers rather than guaranteed
by the service layer. ``update_project`` only ever wrote ``completed_at``
``if field in updates`` (``_mutation_mixin._apply_project_updates``), and the MCP
adapter builds its update dict from the caller's fields alone — so
``update_project(status="completed")`` produced ``status=completed,
completed_at=NULL``. Ten of ten completed BE-93xx projects were measured NULL.

Three consequences, all user-visible: the dashboard's COMPLETED column fell back
to ``updated_at`` (so archiving a project changed its "completion" date), sorting
disagreed with the screen, and ``completed_after`` / ``completed_before`` returned
nothing because NULL matches no range.

This is a MECHANISM fix, so these tests exercise the WRITE path — the layer the
bug lives on. A UI test would not have caught it and is deliberately not the proof.

Test layers:
  * ``TestMcpTerminalTransitionStamp`` — the real MCP adapter
    (``update_project_metadata_for_mcp``) against committed Postgres rows. This is
    the exact call an agent makes, and the WHERE-clause-shaped date filter is
    proven against real rows rather than mocks.
  * ``TestServiceLayerStampRules`` — the stamp's rules at the service boundary:
    a caller-supplied value wins, an existing value is never re-stamped, and a
    transition back OUT of a terminal status clears it.
  * ``TestSoloCloseoutStamp`` — ``write_project_closeout`` on a SOLO project
    (the branch that previously stamped chain members only).

Parallel-safe: the MCP-path class commits for real (its adapter opens its own
sessions via ``db_manager``), so it mints a unique tenant_key and purges its rows
at teardown; the other classes use the rollback-isolated ``db_session``. No
module-level mutable state, no ordering dependencies.

Edition Scope: Both.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.project_closeout import close_project_and_update_memory
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


# close_project_and_update_memory hard-requires a non-None db_manager at its input
# gate, but with an injected session it is never dereferenced (mirrors
# tests/services/test_be6198_closeout_chain_sync.py).
_DB_MANAGER_SENTINEL = object()


async def _seed_product_and_project(
    session: AsyncSession,
    tenant_key: str,
    *,
    status: str = "active",
    product_is_active: bool = False,
    completed_at: datetime | None = None,
) -> tuple[str, str]:
    """Seed one product + one project. Returns ``(product_id, project_id)``.

    Each project gets its OWN product so ``series_number=1`` never collides with a
    sibling test row under ``uq_project_taxonomy``.
    """
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE-9343 Product {uuid.uuid4().hex[:6]}",
        description="BE-9343 completed_at stamp.",
        tenant_key=tenant_key,
        is_active=product_is_active,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    await session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9343 {uuid.uuid4().hex[:6]}",
        description="Project under test.",
        mission="Prove the backend stamps completed_at.",
        status=status,
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=1,
        execution_mode="claude_code_cli",
        completed_at=completed_at,
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return product.id, project.id


def _service(db_manager, tenant_key: str, session: AsyncSession | None = None) -> ProjectService:
    tenant_manager = TenantManager()
    tenant_manager.set_current_tenant(tenant_key)
    return ProjectService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=session)


async def _reload(session: AsyncSession, project_id: str, tenant_key: str) -> Project:
    result = await session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    project = result.scalar_one()
    await session.refresh(project)
    return project


# ---------------------------------------------------------------------------
# The MCP write path — real adapter, real committed rows
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def committed_mcp_project(db_manager):
    """Commit an ACTIVE product + one project, then purge the tenant at teardown.

    ``update_project_metadata_for_mcp`` resolves the active product through a
    ProductService that opens its OWN session from ``db_manager`` (it does not
    inherit an injected test session), so a rollback-isolated seed would be
    invisible to it and the call would fail with "No active product set". These
    rows are therefore committed for real and cleaned up explicitly.
    """
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        _, project_id = await _seed_product_and_project(session, tenant_key, product_is_active=True)
        await session.commit()

    try:
        yield tenant_key, project_id
    finally:
        await purge_tenant_rows(db_manager, tenant_key)


class TestMcpTerminalTransitionStamp:
    """The agent-facing call. This is the layer the defect lives on."""

    @pytest.mark.parametrize("terminal_status", ["completed", "cancelled"])
    async def test_mcp_update_to_terminal_status_stamps_completed_at(
        self, db_manager, committed_mcp_project, terminal_status: str
    ) -> None:
        """THE regression: ``update_project(status="completed")`` must stamp the date.

        A caller doing everything right supplies only the status — exactly what an
        agent closing a solo project does. Before the fix this landed
        ``status=completed, completed_at=NULL``.
        """
        tenant_key, project_id = committed_mcp_project
        service = _service(db_manager, tenant_key)

        before = datetime.now(UTC)
        result = await service.update_project_metadata_for_mcp(
            project_id=project_id,
            status=terminal_status,
            tenant_key=tenant_key,
        )
        after = datetime.now(UTC)

        assert result["success"] is True

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            project = await _reload(session, project_id, tenant_key)
            assert project.status == terminal_status
            assert project.completed_at is not None, (
                f"a project moved to '{terminal_status}' through the MCP write path must carry "
                "completed_at — the backend stamps it, the caller is never asked to"
            )
            stamped = project.completed_at
            if stamped.tzinfo is None:
                stamped = stamped.replace(tzinfo=UTC)
            assert before <= stamped <= after, "the stamp must be the moment of transition"

    async def test_completed_after_filter_finds_a_project_closed_through_mcp(
        self, db_manager, committed_mcp_project
    ) -> None:
        """The user-visible acceptance check, against REAL rows.

        "What shipped this week?" returned zero results because the filter reads the
        real column and NULL matches no range. This is the query that found the bug.
        """
        tenant_key, project_id = committed_mcp_project
        service = _service(db_manager, tenant_key)

        await service.update_project_metadata_for_mcp(
            project_id=project_id,
            status="completed",
            tenant_key=tenant_key,
        )

        window_start = datetime.now(UTC) - timedelta(hours=1)
        window_end = datetime.now(UTC) + timedelta(hours=1)

        listing = await service.list_projects_for_mcp(
            tenant_key=tenant_key,
            include_completed=True,
            completed_after=window_start,
            completed_before=window_end,
        )
        returned_ids = {p["project_id"] for p in listing["projects"]}
        assert project_id in returned_ids, (
            "completed_after/completed_before must return a project closed through the MCP "
            "path — with completed_at NULL it silently matched nothing"
        )

        # The other side of the filter: a window that ends before the project closed
        # must NOT return it, so the assertion above cannot pass by the filter simply
        # being inert.
        stale = await service.list_projects_for_mcp(
            tenant_key=tenant_key,
            include_completed=True,
            completed_before=datetime.now(UTC) - timedelta(days=7),
        )
        assert project_id not in {p["project_id"] for p in stale["projects"]}

    async def test_bare_completion_date_filter_returns_the_completed_project(
        self, db_manager, committed_mcp_project
    ) -> None:
        """AUDIT F2: a completion-date filter alone must not exclude completed projects.

        Without ``include_completed=True`` the status filter resolved to the
        lifecycle-ACTIVE complement and dropped every completed project at the SQL
        boundary — so the query returned the projects NOT marked completed and hid the
        ones that were. Before the backfill that returned nothing, which reads as
        "nothing found"; afterwards it would have returned an INVERTED set, which reads
        as an answer. That is the worse failure, and it is the one this pins.

        Reachable by design: ``template_seeder.py`` seeds the orchestrator's
        duplicate/continuation check with ``completed_after`` and marks
        ``include_completed`` optional, so omitting it is documented-normal.
        """
        tenant_key, project_id = committed_mcp_project
        service = _service(db_manager, tenant_key)

        await service.update_project_metadata_for_mcp(
            project_id=project_id,
            status="completed",
            tenant_key=tenant_key,
        )

        # Note the ABSENCE of include_completed — this is the bare call shape.
        listing = await service.list_projects_for_mcp(
            tenant_key=tenant_key,
            completed_after=datetime.now(UTC) - timedelta(hours=1),
        )

        assert project_id in {p["project_id"] for p in listing["projects"]}, (
            "a bare completed_after query must return the completed project — a "
            "completion-date filter is an unambiguous request for finished work"
        )

        # The OTHER operand of the fix's own predicate. ``has_completion_filter`` is
        # an OR over completed_after and completed_before, and only the first half
        # was pinned: every other bare-shaped completed_before in the tree passes
        # include_completed=True, so nothing exercised this branch. A refactor that
        # dropped ``or completed_before is not None`` would pass the entire suite
        # while silently restoring the inverted set this test exists to prevent.
        before_listing = await service.list_projects_for_mcp(
            tenant_key=tenant_key,
            completed_before=datetime.now(UTC) + timedelta(hours=1),
        )

        assert project_id in {p["project_id"] for p in before_listing["projects"]}, (
            "a bare completed_before query must return the completed project too — the "
            "implication is an OR over both date bounds, not completed_after alone"
        )

    async def test_an_explicit_status_still_wins_over_the_implied_include(
        self, db_manager, committed_mcp_project
    ) -> None:
        """The implication must not override a caller who asked a narrower question.

        ``list_projects(status="active", completed_after=X)`` is coherent, and it must
        keep excluding completed projects — otherwise the F2 fix would have replaced one
        wrong answer with another.
        """
        tenant_key, project_id = committed_mcp_project
        service = _service(db_manager, tenant_key)

        await service.update_project_metadata_for_mcp(
            project_id=project_id,
            status="completed",
            tenant_key=tenant_key,
        )

        listing = await service.list_projects_for_mcp(
            tenant_key=tenant_key,
            status="active",
            completed_after=datetime.now(UTC) - timedelta(hours=1),
        )

        assert project_id not in {p["project_id"] for p in listing["projects"]}, (
            "an explicit status filter must still win over the implied include_completed"
        )


# ---------------------------------------------------------------------------
# The stamp's rules at the service boundary
# ---------------------------------------------------------------------------


class TestServiceLayerStampRules:
    """Additive, never an override — and symmetric on the way back out."""

    async def test_caller_supplied_completed_at_still_wins(self, db_manager, db_session) -> None:
        """The Archive button passes completed_at explicitly and must keep winning."""
        tenant_key = TenantManager.generate_tenant_key()
        _, project_id = await _seed_product_and_project(db_session, tenant_key)
        service = _service(db_manager, tenant_key, db_session)

        explicit = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
        await service.update_project(project_id=project_id, updates={"status": "completed", "completed_at": explicit})

        project = await _reload(db_session, project_id, tenant_key)
        stamped = project.completed_at
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=UTC)
        assert stamped == explicit, "an explicitly supplied completed_at must not be overwritten by the auto-stamp"

    async def test_existing_completed_at_is_not_re_stamped(self, db_manager, db_session) -> None:
        """Already set means already answered — a later terminal write must not re-date it.

        This is what keeps a completed project's real date intact when it is later
        marked superseded (BE-9157 allows exactly that transition).
        """
        tenant_key = TenantManager.generate_tenant_key()
        original = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        _, project_id = await _seed_product_and_project(
            db_session, tenant_key, status="terminated", completed_at=original
        )
        service = _service(db_manager, tenant_key, db_session)

        await service.update_project(project_id=project_id, updates={"status": "completed"})

        project = await _reload(db_session, project_id, tenant_key)
        stamped = project.completed_at
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=UTC)
        assert stamped == original, "an existing completed_at must survive a later terminal transition"

    async def test_transition_to_terminated_stamps(self, db_manager, db_session) -> None:
        """``terminated`` is lifecycle-finished too — the set drives this, not a literal list."""
        tenant_key = TenantManager.generate_tenant_key()
        _, project_id = await _seed_product_and_project(db_session, tenant_key)
        service = _service(db_manager, tenant_key, db_session)

        await service.update_project(project_id=project_id, updates={"status": "terminated"})

        project = await _reload(db_session, project_id, tenant_key)
        assert project.completed_at is not None, "every LIFECYCLE_FINISHED status must stamp, not just 'completed'"

    async def test_transition_out_of_terminal_clears_completed_at(self, db_manager, db_session) -> None:
        """A reopened project must not keep a stale completion date.

        Mirrors ``continue_working``, which already clears it on the dashboard path.
        ``terminated`` is lifecycle-finished but NOT immutable, so this transition is
        genuinely reachable through the generic write path.
        """
        tenant_key = TenantManager.generate_tenant_key()
        _, project_id = await _seed_product_and_project(
            db_session, tenant_key, status="terminated", completed_at=datetime(2026, 2, 2, tzinfo=UTC)
        )
        service = _service(db_manager, tenant_key, db_session)

        await service.update_project(project_id=project_id, updates={"status": "inactive"})

        project = await _reload(db_session, project_id, tenant_key)
        assert project.completed_at is None, "leaving a terminal status must clear the completion date"

    async def test_a_non_status_update_never_touches_completed_at(self, db_manager, db_session) -> None:
        """The stamp keys on a TRANSITION. Renaming a project must not date it.

        Without this, any PATCH would become a lifecycle event.
        """
        tenant_key = TenantManager.generate_tenant_key()
        _, project_id = await _seed_product_and_project(db_session, tenant_key)
        service = _service(db_manager, tenant_key, db_session)

        await service.update_project(project_id=project_id, updates={"name": "Renamed, still running"})

        project = await _reload(db_session, project_id, tenant_key)
        assert project.completed_at is None, "a metadata-only update must not stamp a completion date"


# ---------------------------------------------------------------------------
# The solo closeout branch
# ---------------------------------------------------------------------------


class TestSoloCloseoutStamp:
    """``write_project_closeout`` stamped chain members only; solo was skipped."""

    async def test_solo_closeout_stamps_completed_at(self, db_session) -> None:
        """A standalone project closed by an agent is the majority case in this repo.

        It previously depended on someone later pressing Archive to get a date at
        all — and if nobody did, the row stayed NULL forever.
        """
        tenant_key = TenantManager.generate_tenant_key()
        _, project_id = await _seed_product_and_project(db_session, tenant_key)

        await close_project_and_update_memory(
            project_id=project_id,
            summary="solo done",
            key_outcomes=["shipped"],
            decisions_made=["stamped by the backend"],
            tenant_key=tenant_key,
            db_manager=_DB_MANAGER_SENTINEL,
            session=db_session,
            force=True,
        )

        project = await _reload(db_session, project_id, tenant_key)
        assert project.closeout_executed_at is not None
        assert project.completed_at is not None, (
            "a SOLO closeout must stamp completed_at — previously only chain members were stamped"
        )

    async def test_solo_closeout_does_not_overwrite_an_existing_date(self, db_session) -> None:
        """Closeout fills a gap; it does not re-date a project that already has one."""
        tenant_key = TenantManager.generate_tenant_key()
        original = datetime(2026, 1, 9, 10, 11, 12, tzinfo=UTC)
        _, project_id = await _seed_product_and_project(db_session, tenant_key, completed_at=original)

        await close_project_and_update_memory(
            project_id=project_id,
            summary="solo done again",
            key_outcomes=["shipped"],
            decisions_made=["kept the original date"],
            tenant_key=tenant_key,
            db_manager=_DB_MANAGER_SENTINEL,
            session=db_session,
            force=True,
        )

        project = await _reload(db_session, project_id, tenant_key)
        stamped = project.completed_at
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=UTC)
        assert stamped == original

    async def test_solo_closeout_message_does_not_claim_the_project_was_closed(self, db_session) -> None:
        """The message this branch returns must not claim what this exact branch refuses to do.

        ``_finalize_chain_member_closeout`` deliberately leaves a solo project's row
        untouched -- status flip is chain-member-only, by design (BUG #7) -- yet the
        response text used to read "Project closed and 360 Memory updated successfully"
        unconditionally. An agent (or a script) trusting that sentence has no reason to
        ever press Archive, and INF-9252's prod-seeding incident traced a bad
        assumption to exactly this: the caller believed the project was closed because
        the tool said so.

        The remedy named must be the one that actually completes a solo project --
        the dashboard's Archive button, i.e. ``POST /api/v1/projects/{id}/archive``
        (``api/endpoints/projects/lifecycle.py::archive_project``) -- NOT
        ``update_project(status="completed")``, which is not the supported path.
        """
        tenant_key = TenantManager.generate_tenant_key()
        _, project_id = await _seed_product_and_project(db_session, tenant_key)

        result = await close_project_and_update_memory(
            project_id=project_id,
            summary="solo done",
            key_outcomes=["shipped"],
            decisions_made=["stamped by the backend"],
            tenant_key=tenant_key,
            db_manager=_DB_MANAGER_SENTINEL,
            session=db_session,
            force=True,
        )

        message = result["message"]
        assert "project closed" not in message.lower(), (
            f"a solo closeout must not claim the PROJECT itself was closed -- its status "
            f"is deliberately left for the Archive press, unchanged by this call: {message!r}"
        )
        assert f"/api/v1/projects/{project_id}/archive" in message, (
            f"the message must name the remedy that genuinely completes a solo project: {message!r}"
        )
        assert "update_project" not in message, (
            f"must not point at update_project(status=...) -- that is not the supported completion path: {message!r}"
        )
        assert "memory" in message.lower(), (
            f"the message must still confirm the 360 memory entry, which genuinely was written: {message!r}"
        )

        # Sanity: the status really was left alone by this exact call (the museum-rule
        # invariant this wording change must not disturb).
        project = await _reload(db_session, project_id, tenant_key)
        assert project.status == "active", "sanity: the solo status must truly be unchanged by this closeout"
