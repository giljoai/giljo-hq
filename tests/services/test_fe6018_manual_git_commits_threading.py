# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-6018 regression: manual ``git_commits`` threading through Complete-Project.

The Complete-Project closeout path now carries an optional, agent-supplied
``git_commits`` list from the HTTP request all the way to
``close_project_and_update_memory``, which persists each commit as a structured
row in ``product_memory_entries.git_commits`` (JSONB).

The failing layer this guards is the **plumbing**: schema -> endpoint ->
``ProjectService.complete_project`` -> ``ProjectLifecycleService`` ->
``close_project_and_update_memory``. A pure-mock unit test would not catch a
field silently dropped at the Pydantic schema (FastAPI discards undeclared
request fields) nor a hop that fails to forward the keyword. These tests:

1. Drive the real ``ProjectService.complete_project`` facade against a real
   per-worker test DB and read the persisted memory entry back, asserting the
   supplied commits land as structured rows linked to the right
   project_id/product_id.
2. Assert the empty/omitted case still completes cleanly with
   ``git_commits_count == 0`` (omission yields ``[]`` via ``default_factory``).
3. Assert the request schema retains the field (hop-1 silent-drop guard).

Parallel-safe: real DB writes go through the transactional ``db_session``
(rolled back at teardown); no module-level mutable state; no test ordering deps.
"""

import random
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.projects import Project


@pytest.fixture
def manual_git_commits() -> list[dict]:
    """Two commits exercising required + optional GitCommitEntry fields."""
    return [
        {
            "sha": "a1b2c3d4e5f6",
            "message": "feat(fe-6018): thread git_commits through closeout",
            "author": "Test Dev",
            "date": "2026-06-05T10:00:00Z",
            "files_changed": 4,
            "lines_added": 120,
        },
        {
            # author/date/files_changed/lines_added omitted -> optional path
            "sha": "0f9e8d7c6b5a",
            "message": "test(fe-6018): add plumbing regression",
        },
    ]


@pytest.fixture
async def project_linked_to_product(db_session, test_product, test_tenant_key) -> Project:
    """A project linked to ``test_product`` so closeout can resolve the product.

    No agents are attached, so the closeout readiness gate is trivially
    satisfied (the lifecycle calls ``close_project_and_update_memory`` with
    ``force=True`` regardless).
    """
    project = Project(
        id=str(uuid4()),
        name="FE-6018 Threading Test Project",
        description="Project for git_commits threading regression",
        mission="Verify manual git_commits reach the 360 memory entry",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def _fetch_memory_entry(db_session, project_id: str) -> ProductMemoryEntry:
    result = await db_session.execute(select(ProductMemoryEntry).where(ProductMemoryEntry.project_id == project_id))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_supplied_git_commits_persist_as_structured_rows(
    project_service_with_session,
    db_session,
    test_product,
    test_tenant_key,
    project_linked_to_product,
    manual_git_commits,
):
    """Agent-supplied commits reach the persisted 360 memory entry's JSONB."""
    result = await project_service_with_session.complete_project(
        project_id=project_linked_to_product.id,
        summary=(
            "FE-6018 closeout with manually entered git commits to verify the "
            "optional list threads through schema, endpoint, service, lifecycle, "
            "and into the persisted product memory entry."
        ),
        key_outcomes=["git_commits threaded end-to-end"],
        decisions_made=["Reused existing GitCommitEntry validator; no new column"],
        tenant_key=test_tenant_key,
        git_commits=manual_git_commits,
    )

    assert result.memory_updated is True
    assert result.git_commits_count == len(manual_git_commits)

    entry = await _fetch_memory_entry(db_session, project_linked_to_product.id)

    # Linked to the correct project and product.
    assert str(entry.project_id) == str(project_linked_to_product.id)
    assert str(entry.product_id) == str(test_product.id)

    # Structured rows landed in the JSONB column, validated/normalized.
    stored = entry.git_commits
    assert isinstance(stored, list)
    assert len(stored) == 2

    by_sha = {row["sha"]: row for row in stored}
    assert set(by_sha) == {"a1b2c3d4e5f6", "0f9e8d7c6b5a"}

    full = by_sha["a1b2c3d4e5f6"]
    assert full["message"] == "feat(fe-6018): thread git_commits through closeout"
    assert full["author"] == "Test Dev"
    assert full["files_changed"] == 4
    assert full["lines_added"] == 120

    # Optional fields normalized: missing counts -> 0, missing author/date -> None.
    minimal = by_sha["0f9e8d7c6b5a"]
    assert minimal["message"] == "test(fe-6018): add plumbing regression"
    assert minimal["author"] is None
    assert minimal["files_changed"] == 0
    assert minimal["lines_added"] == 0


@pytest.mark.asyncio
async def test_omitted_git_commits_still_completes_cleanly(
    project_service_with_session,
    db_session,
    test_tenant_key,
    project_linked_to_product,
):
    """Omitting git_commits (default empty list) still writes the entry with count 0."""
    result = await project_service_with_session.complete_project(
        project_id=project_linked_to_product.id,
        summary=(
            "FE-6018 closeout with no git commits supplied; the project must "
            "still complete cleanly and persist a 360 memory entry with an "
            "empty git_commits list and a zero count."
        ),
        key_outcomes=["empty case completes"],
        decisions_made=["Omission equals empty list (back-compat)"],
        tenant_key=test_tenant_key,
    )

    assert result.memory_updated is True
    assert result.git_commits_count == 0

    entry = await _fetch_memory_entry(db_session, project_linked_to_product.id)
    assert entry.git_commits in ([], None)


@pytest.mark.parametrize(
    ("supplied", "expected_kwarg"),
    [
        pytest.param([], None, id="empty-list-becomes-None"),
        pytest.param(None, None, id="None-stays-None"),
    ],
)
@pytest.mark.asyncio
async def test_empty_or_none_commits_pass_none_to_closeout(
    monkeypatch,
    project_service_with_session,
    db_session,
    test_tenant_key,
    project_linked_to_product,
    supplied,
    expected_kwarg,
):
    """Regression (reviewer Finding #1): an empty/None manual closeout must forward
    ``git_commits=None`` to ``close_project_and_update_memory``, NOT ``[]``.

    Passing ``[]`` sets ``agent_supplied_commits=True`` downstream, which suppresses
    the ``git_unavailable_reason`` marker (BE-9256: the server is passive -- it never
    fetches commits from a git host itself; ``None`` vs ``[]`` now only distinguishes
    "commits not collected" from "explicitly none in range"). FE-6018's scope promised
    not to touch that distinction, so the empty manual case must preserve the
    pre-FE-6018 ``None`` signal. Asserting the call-arg contract proves that
    distinction is intact.
    """
    spy = AsyncMock(return_value={"sequence_number": 1, "git_commits_count": 0, "memory_updated": True})
    monkeypatch.setattr("giljo_mcp.tools.project_closeout.close_project_and_update_memory", spy)

    kwargs = {} if supplied is None else {"git_commits": supplied}
    await project_service_with_session.complete_project(
        project_id=project_linked_to_product.id,
        summary=(
            "FE-6018 regression: empty or omitted git_commits must reach the closeout "
            "tool as None so the SaaS auto-fetch path stays reachable."
        ),
        key_outcomes=["call-arg contract: None, not []"],
        decisions_made=["git_commits or None at the lifecycle call site"],
        tenant_key=test_tenant_key,
        **kwargs,
    )

    spy.assert_awaited_once()
    assert spy.await_args.kwargs["git_commits"] is expected_kwarg


@pytest.mark.asyncio
async def test_nonempty_commits_pass_exact_list_to_closeout(
    monkeypatch,
    project_service_with_session,
    test_tenant_key,
    project_linked_to_product,
    manual_git_commits,
):
    """A non-empty manual list is forwarded verbatim (truthy -> unchanged)."""
    spy = AsyncMock(return_value={"sequence_number": 1, "git_commits_count": 2, "memory_updated": True})
    monkeypatch.setattr("giljo_mcp.tools.project_closeout.close_project_and_update_memory", spy)

    await project_service_with_session.complete_project(
        project_id=project_linked_to_product.id,
        summary=(
            "FE-6018 regression: a non-empty manual git_commits list must reach the "
            "closeout tool unchanged so manually entered commits are still persisted."
        ),
        key_outcomes=["manual commits forwarded verbatim"],
        decisions_made=["truthy git_commits passes through the call site unchanged"],
        tenant_key=test_tenant_key,
        git_commits=manual_git_commits,
    )

    spy.assert_awaited_once()
    assert spy.await_args.kwargs["git_commits"] == manual_git_commits


def test_request_schema_retains_git_commits_field():
    """Hop-1 guard: the request model must declare git_commits or FastAPI drops it."""
    from api.schemas.prompt import ProjectCompleteRequest

    payload = {
        "summary": "x" * 60,
        "key_outcomes": ["o1"],
        "confirm_closeout": True,
        "git_commits": [{"sha": "deadbeef", "message": "chore: probe"}],
    }
    model = ProjectCompleteRequest(**payload)
    assert model.git_commits == [{"sha": "deadbeef", "message": "chore: probe"}]

    # Omission yields an empty list (not None), preserving back-compat.
    omitted = ProjectCompleteRequest(summary="y" * 60, key_outcomes=["o1"], confirm_closeout=True)
    assert omitted.git_commits == []
