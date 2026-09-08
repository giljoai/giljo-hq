# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9540 — headless chain completion must satisfy the per-card review gate.

A ``per_card`` run driven entirely headlessly (staged, launched, closed out,
completed) could have its conductor's finale purge the run with
``reviewed_project_ids`` still EMPTY — the dashboard's per-card review flow was
never consulted, because the headless path never wrote to it at all, so a
client still viewing that run lost the row underneath it.

Decided behaviour: headless completion COUNTS as the per-card review. This file
pins that ``complete_chain_run_if_finished``
auto-marks every not-yet-reviewed member reviewed, through the SAME writer the
UI review flow uses (``SequenceRunService.mark_member_reviewed``), stamped
``reviewed_via="harness"`` in the new per-member provenance map -- and that an
EXISTING "ui" review (a card the user reviewed manually before the rest
finished headlessly) is never silently overwritten.

Failing-layer discipline (CLAUDE.md): the defect lives in the service layer
(``project_helpers.complete_chain_run_if_finished``), so these are service
tests exercising the real function against a real DB row -- not a mock of the
writer. ``test_headless_completion_writes_review_before_purge`` reproduces the
exact live sequence and is the regression core; it must be shown FAILING before
this project's fix (asserted in the PR body, not here).

DB-touching: db_session fixture (TransactionalTestContext). No module-level
mutable state. No ordering dependencies. Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.services.project_helpers import (
    complete_chain_run_if_finished,
    mark_chain_member_status,
)
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_be6189_conductor_closeout.py)
# ---------------------------------------------------------------------------


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    owning_product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(owning_product)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9540 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=owning_product.id,
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


async def _seed_run_with_conductor(session: AsyncSession, tenant_key: str, *, review_policy: str = "per_card") -> dict:
    p1 = await _seed_project(session, tenant_key)
    p2 = await _seed_project(session, tenant_key)
    run = await _run_svc(session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        review_policy=review_policy,
        tenant_key=tenant_key,
    )
    run["_project_ids"] = [p1, p2]
    return run


async def _complete_both_members(session: AsyncSession, tenant_key: str, p1: str, p2: str) -> None:
    for pid in (p1, p2):
        flipped = await mark_chain_member_status(
            db_manager=None,
            tenant_manager=TenantManager(),
            project_id=pid,
            tenant_key=tenant_key,
            status="completed",
            test_session=session,
        )
        assert flipped is True


# ---------------------------------------------------------------------------
# 1. THE REGRESSION CORE: headless completion writes the review before purge.
# ---------------------------------------------------------------------------


async def test_headless_completion_writes_review_before_purge(db_session: AsyncSession, monkeypatch) -> None:
    """Reproduce the exact live sequence: a per_card run driven fully headlessly.

    Captures the run's ``reviewed_project_ids``/``reviewed_via`` the instant
    before ``purge_run`` deletes the row (by wrapping the real purge_run rather
    than replacing it -- the purge itself still happens, proving this test does
    not merely avoid the defect by skipping the delete).
    """
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1, p2 = run["_project_ids"]
    conductor_agent_id = run["conductor_agent_id"]

    await _complete_both_members(db_session, tenant, p1, p2)

    captured: dict = {}
    original_purge = SequenceRunService.purge_run

    async def _capturing_purge(self, *, run_id, tenant_key=None):
        # Read the row through THIS SAME session, right before it is deleted.
        current = await self.get(run_id=run_id, tenant_key=tenant_key)
        captured["reviewed_project_ids"] = current["reviewed_project_ids"]
        captured["reviewed_via"] = current["reviewed_via"]
        return await original_purge(self, run_id=run_id, tenant_key=tenant_key)

    monkeypatch.setattr(SequenceRunService, "purge_run", _capturing_purge)

    purged = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=conductor_agent_id,
        tenant_key=tenant,
        test_session=db_session,
    )
    assert purged is True

    # The exact defect: BEFORE the fix, both of these are empty at purge time —
    # the headless path never wrote the review at all.
    assert set(captured["reviewed_project_ids"]) == {p1, p2}, (
        "operator ruling B: headless completion must count as the per-card review"
    )
    assert captured["reviewed_via"] == {p1: "harness", p2: "harness"}, (
        "provenance must show the review was satisfied BY THE HARNESS, never silently skipped"
    )

    # The run is genuinely gone afterward (this is not a purge-skip in disguise).
    with pytest.raises(ResourceNotFoundError):
        await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)


# ---------------------------------------------------------------------------
# 2. An existing UI review is never overwritten by the auto-harness pass.
# ---------------------------------------------------------------------------


async def test_existing_ui_review_is_not_overwritten_by_harness_pass(db_session: AsyncSession, monkeypatch) -> None:
    """A user reviews one card manually (via='ui') before the OTHER member
    finishes headlessly. The finale must record 'harness' only for the member
    that was never reviewed, and must leave the 'ui' entry untouched."""
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1, p2 = run["_project_ids"]
    conductor_agent_id = run["conductor_agent_id"]

    # Simulate the dashboard's per-card review POST for p1, BEFORE either member
    # is terminal -- exactly what a user reviewing-as-they-go looks like.
    reviewed = await _run_svc(db_session).mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant)
    assert reviewed["reviewed_via"] == {p1: "ui"}

    await _complete_both_members(db_session, tenant, p1, p2)

    captured: dict = {}
    original_purge = SequenceRunService.purge_run

    async def _capturing_purge(self, *, run_id, tenant_key=None):
        current = await self.get(run_id=run_id, tenant_key=tenant_key)
        captured["reviewed_via"] = current["reviewed_via"]
        return await original_purge(self, run_id=run_id, tenant_key=tenant_key)

    monkeypatch.setattr(SequenceRunService, "purge_run", _capturing_purge)

    await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=conductor_agent_id,
        tenant_key=tenant,
        test_session=db_session,
    )

    assert captured["reviewed_via"] == {p1: "ui", p2: "harness"}, (
        "the pre-existing UI review must survive; only the never-reviewed member gets 'harness'"
    )


# ---------------------------------------------------------------------------
# 3. auto_close runs have no per-card policy to satisfy -- no auto-review write.
# ---------------------------------------------------------------------------


async def test_auto_close_run_gets_no_auto_review_write(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant, review_policy="auto_close")
    p1, p2 = run["_project_ids"]
    conductor_agent_id = run["conductor_agent_id"]

    await _complete_both_members(db_session, tenant, p1, p2)

    purged = await complete_chain_run_if_finished(
        db_manager=None,
        tenant_manager=TenantManager(),
        conductor_agent_id=conductor_agent_id,
        tenant_key=tenant,
        test_session=db_session,
    )
    assert purged is True
    with pytest.raises(ResourceNotFoundError):
        await _run_svc(db_session).get(run_id=run["id"], tenant_key=tenant)


# ---------------------------------------------------------------------------
# 4. mark_member_reviewed: `via` writes the provenance map, one writer, both
#    the UI shape (default) and the new harness shape.
# ---------------------------------------------------------------------------


async def test_mark_member_reviewed_default_via_is_ui(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1 = run["_project_ids"][0]

    result = await _run_svc(db_session).mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant)
    assert result["reviewed_project_ids"] == [p1]
    assert result["reviewed_via"] == {p1: "ui"}


async def test_mark_member_reviewed_accepts_harness_via(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1 = run["_project_ids"][0]

    result = await _run_svc(db_session).mark_member_reviewed(
        run_id=run["id"], project_id=p1, tenant_key=tenant, via="harness"
    )
    assert result["reviewed_via"] == {p1: "harness"}


async def test_mark_member_reviewed_rejects_unknown_via(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1 = run["_project_ids"][0]

    with pytest.raises(ValidationError):
        await _run_svc(db_session).mark_member_reviewed(
            run_id=run["id"], project_id=p1, tenant_key=tenant, via="carrier-pigeon"
        )


async def test_mark_member_reviewed_idempotent_keeps_original_via(db_session: AsyncSession) -> None:
    """Re-marking an already-reviewed project is a clean no-op -- the ORIGINAL
    provenance is kept, a later call with a different via does not overwrite it."""
    tenant = TenantManager.generate_tenant_key()
    run = await _seed_run_with_conductor(db_session, tenant)
    p1 = run["_project_ids"][0]

    await _run_svc(db_session).mark_member_reviewed(run_id=run["id"], project_id=p1, tenant_key=tenant, via="ui")
    second = await _run_svc(db_session).mark_member_reviewed(
        run_id=run["id"], project_id=p1, tenant_key=tenant, via="harness"
    )
    assert second["reviewed_via"] == {p1: "ui"}, "idempotent no-op must not overwrite the original provenance"
