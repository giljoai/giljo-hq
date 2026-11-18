# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Project
from giljo_mcp.repositories._project_enrichment_reads_mixin import REVIEW_STEP_RELEASED_AT
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.services.project_helpers import broadcast_deferred_events
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.services.test_fe0072a_start_list_service import _Account


pytestmark = pytest.mark.asyncio

AFTER_RELEASE = REVIEW_STEP_RELEASED_AT + timedelta(days=1)
BEFORE_RELEASE = REVIEW_STEP_RELEASED_AT - timedelta(days=30)


class _Wire:

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    async def broadcast_to_tenant(self, tenant_key: str, event_type: str, data: dict) -> None:
        self.sent.append((tenant_key, event_type, data))

    async def broadcast_event_to_tenant(self, tenant_key: str, event: dict) -> None:
        self.sent.append((tenant_key, event["type"], event["data"]))

    def reviewed(self) -> list[tuple[str, str, dict]]:
        return [e for e in self.sent if e[1] == "project_update" and e[2].get("update_type") == "reviewed"]


@pytest.fixture
def account(db_session, db_manager) -> _Account:
    return _Account(db_session, db_manager)


async def _created(account: _Account, product_id: str, name: str, minutes_ago: int) -> Project:
    project = await account.make_project(product_id, name)
    project.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    await account.session.flush()
    return project


async def _finished(account: _Account, stamp: datetime) -> Project:
    product = await account.make_product(f"Prod {uuid.uuid4().hex[:6]}")
    project = await account.make_project(product.id, f"Build {uuid.uuid4().hex[:4]}")
    await account.stage(project)
    await account.launch(project)
    await account.close(project, review=False)
    project.completed_at = stamp
    project.closeout_executed_at = stamp
    await account.session.flush()
    return project




async def test_row_four_names_the_first_of_two_projects(account):
    product = await account.make_product("Atlas")
    first = await _created(account, product.id, "First idea", 10)
    await _created(account, product.id, "Add a search box", 1)

    row = (await account.read()).rows.project_created

    assert row.model_dump() == {"done": True, "project_id": first.id, "project_name": "First idea"}


async def test_row_four_keeps_naming_the_first_when_the_tool_creates_four_more(account):
    product = await account.make_product("Atlas")
    first = await _created(account, product.id, "Project 1", 50)
    for n in range(2, 6):
        await _created(account, product.id, f"Project {n}", 50 - n * 5)

    row = (await account.read()).rows.project_created

    assert (row.project_id, row.project_name) == (first.id, "Project 1")


async def test_row_four_skips_a_trashed_first_project(account):
    product = await account.make_product("Atlas")
    first = await _created(account, product.id, "Trashed", 10)
    second = await _created(account, product.id, "Kept", 5)
    await account.projects.deletion.delete_project(first.id, broadcast=False)

    assert (await account.read()).rows.project_created.project_id == second.id


async def test_row_four_breaks_a_created_at_tie_by_the_smaller_id(account):
    product = await account.make_product("Atlas")
    a = await account.make_project(product.id, "Twin A")
    b = await account.make_project(product.id, "Twin B")
    same = datetime.now(UTC) - timedelta(minutes=3)
    a.created_at = b.created_at = same
    await account.session.flush()

    assert (await account.read()).rows.project_created.project_id == min(a.id, b.id)




async def test_requested_is_false_with_no_project_and_with_an_unstaged_project(account):
    assert (await account.read()).rows.project_staged.requested is False
    product = await account.make_product("Atlas")
    await account.make_project(product.id, "Plain")

    assert (await account.read()).rows.project_staged.requested is False


async def test_requested_is_true_once_the_stage_prompt_was_handed_out(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id, "Plain")
    project.staging_status = "staged"
    await account.session.flush()

    row = (await account.read()).rows.project_staged

    assert (row.done, row.requested) == (False, True)


async def test_requested_ends_when_staging_completes(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id, "Plain")
    project.staging_status = "staged"
    await account.session.flush()
    await account.stage(project)

    row = (await account.read()).rows.project_staged

    assert (row.done, row.requested) == (True, False)


async def test_requested_ends_when_the_project_is_launched(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id, "Plain")
    project.staging_status = "staged"
    await account.session.flush()
    await account.launch(project)

    row = (await account.read()).rows.project_staged

    assert (row.done, row.requested) == (True, False)


async def test_a_trashed_project_is_not_requested(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id, "Plain")
    project.staging_status = "staged"
    await account.session.flush()
    await account.projects.deletion.delete_project(project.id, broadcast=False)

    assert (await account.read()).rows.project_staged.requested is False




async def test_row_six_todo_state_json(account):
    result = await account.read()

    assert result.model_dump()["rows"]["project_built"] == {
        "done": False,
        "in_progress": False,
        "awaiting_review": False,
    }


async def test_row_six_in_progress_state_json(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id, "Plain")
    await account.stage(project)
    await account.launch(project)

    assert (await account.read()).model_dump()["rows"]["project_built"] == {
        "done": False,
        "in_progress": True,
        "awaiting_review": False,
    }


async def test_row_six_awaiting_review_state_json(account):
    await _finished(account, AFTER_RELEASE)

    result = await account.read()

    assert result.model_dump()["rows"]["project_built"] == {
        "done": False,
        "in_progress": False,
        "awaiting_review": True,
    }
    assert result.done_count == 3


async def test_row_six_done_state_json_after_the_review_press(account):
    project = await _finished(account, AFTER_RELEASE)
    await account.projects.mark_project_reviewed(project.id, account.tenant_key)

    result = await account.read()

    assert result.model_dump()["rows"]["project_built"] == {
        "done": True,
        "in_progress": False,
        "awaiting_review": False,
    }
    assert result.done_count == 4


async def test_an_account_that_finished_before_the_release_never_falls_back(account):
    project = await _finished(account, BEFORE_RELEASE)
    assert project.reviewed_at is None

    result = await account.read()

    assert result.model_dump()["rows"]["project_built"] == {
        "done": True,
        "in_progress": False,
        "awaiting_review": False,
    }
    assert result.done_count == 4


async def test_a_trashed_unreviewed_built_project_counts_as_reviewed(account):
    project = await _finished(account, AFTER_RELEASE)
    await account.projects.deletion.delete_project(project.id, broadcast=False)

    result = await account.read()

    assert result.model_dump()["rows"]["project_built"] == {
        "done": True,
        "in_progress": False,
        "awaiting_review": False,
    }
    assert result.done_count == 2


async def test_a_restored_unreviewed_built_project_waits_for_review_again(account):
    project = await _finished(account, AFTER_RELEASE)
    await account.projects.deletion.delete_project(project.id, broadcast=False)
    await account.projects.deletion.restore_project(project.id, tenant_key=account.tenant_key)

    row = (await account.read()).rows.project_built

    assert (row.done, row.awaiting_review) == (False, True)


async def test_a_trashed_unreviewed_project_beside_a_live_unreviewed_one_reads_done(account):
    trashed = await _finished(account, AFTER_RELEASE)
    await _finished(account, AFTER_RELEASE)
    await account.projects.deletion.delete_project(trashed.id, broadcast=False)

    row = (await account.read()).rows.project_built

    assert (row.done, row.awaiting_review) == (True, False)


async def test_another_tenants_trashed_built_project_never_changes_this_account(account, db_session, db_manager):
    await _finished(account, AFTER_RELEASE)
    other = _Account(db_session, db_manager)
    theirs = await _finished(other, AFTER_RELEASE)
    await other.projects.deletion.delete_project(theirs.id, broadcast=False)

    mine = (await account.read()).rows.project_built

    assert (mine.done, mine.awaiting_review) == (False, True)


async def test_a_trashed_old_finished_project_stays_done(account):
    project = await _finished(account, BEFORE_RELEASE)
    await account.projects.deletion.delete_project(project.id, broadcast=False)

    assert (await account.read()).rows.project_built.done is True


async def test_one_reviewed_project_among_unreviewed_ones_makes_row_six_done(account):
    await _finished(account, AFTER_RELEASE)
    second = await _finished(account, AFTER_RELEASE)
    await account.projects.mark_project_reviewed(second.id, account.tenant_key)

    row = (await account.read()).rows.project_built

    assert (row.done, row.awaiting_review) == (True, False)


async def test_a_revived_old_project_keeps_row_six_done(account):
    project = await _finished(account, BEFORE_RELEASE)
    await account.projects.lifecycle.continue_working(project.id, tenant_key=account.tenant_key)

    row = (await account.read()).rows.project_built

    assert (row.done, row.awaiting_review) == (True, False)


async def test_another_tenants_review_never_makes_this_account_done(account, db_session, db_manager):
    await _finished(account, AFTER_RELEASE)
    other = _Account(db_session, db_manager)
    theirs = await _finished(other, AFTER_RELEASE)
    await other.projects.mark_project_reviewed(theirs.id, other.tenant_key)

    mine = (await account.read()).rows.project_built

    assert (mine.done, mine.awaiting_review) == (False, True)


async def test_another_tenants_old_project_never_makes_this_account_done(account, db_session, db_manager):
    other = _Account(db_session, db_manager)
    await _finished(other, BEFORE_RELEASE)

    assert (await account.read()).rows.project_built.model_dump() == {
        "done": False,
        "in_progress": False,
        "awaiting_review": False,
    }


async def test_the_new_facts_carry_their_own_tenant_filter_with_the_session_guard_off(account, db_session, db_manager):
    other = _Account(db_session, db_manager)
    project = await _finished(other, AFTER_RELEASE)
    project.staging_status = "staged"
    await other.session.flush()

    with tenant_isolation_bypass(db_session, reason="BA1: prove the explicit tenant filter", models=(Project,)):
        mine = await ProjectRepository().get_start_list_project_facts(db_session, account.tenant_key)
        theirs = await ProjectRepository().get_start_list_project_facts(db_session, other.tenant_key)

    assert (mine.requested, mine.built, mine.reviewed) == (False, False, False)
    assert (theirs.built, theirs.reviewed) == (True, False)




async def test_the_review_press_sends_one_project_update_to_the_tenant(account, db_session, db_manager):
    wire = _Wire()
    project = await _finished(account, AFTER_RELEASE)
    service = ProjectService(
        db_manager=db_manager, tenant_manager=account.tm, test_session=db_session, websocket_manager=wire
    )

    await service.mark_project_reviewed(project.id, account.tenant_key)

    [(tenant_key, event_type, data)] = wire.reviewed()
    assert (tenant_key, event_type) == (account.tenant_key, "project_update")
    assert data["project_id"] == project.id
    assert data["update_type"] == "reviewed"


async def test_a_repeated_review_press_sends_nothing_more(account, db_session, db_manager):
    wire = _Wire()
    project = await _finished(account, AFTER_RELEASE)
    service = ProjectService(
        db_manager=db_manager, tenant_manager=account.tm, test_session=db_session, websocket_manager=wire
    )

    await service.mark_project_reviewed(project.id, account.tenant_key)
    await service.mark_project_reviewed(project.id, account.tenant_key)

    assert len(wire.reviewed()) == 1


async def test_mark_all_reviewed_sends_one_event_per_project_newly_reviewed(account, db_session, db_manager):
    wire = _Wire()
    first = await _finished(account, AFTER_RELEASE)
    second = await _finished(account, AFTER_RELEASE)
    service = ProjectService(
        db_manager=db_manager, tenant_manager=account.tm, test_session=db_session, websocket_manager=wire
    )
    await service.mark_project_reviewed(first.id, account.tenant_key)
    wire.sent.clear()

    result = await service.mark_projects_reviewed([first.id, second.id], account.tenant_key)

    assert result["marked"] == 2
    assert [e[2]["project_id"] for e in wire.reviewed()] == [second.id]
    assert {e[0] for e in wire.reviewed()} == {account.tenant_key}


async def test_a_refused_review_sends_nothing(account, db_session, db_manager):
    wire = _Wire()
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id, "Unfinished")
    service = ProjectService(
        db_manager=db_manager, tenant_manager=account.tm, test_session=db_session, websocket_manager=wire
    )

    with pytest.raises(Exception, match="finished"):
        await service.mark_project_reviewed(project.id, account.tenant_key)

    assert wire.sent == []


async def test_the_chain_member_review_sends_a_project_update_to_the_tenant(account, db_session):
    wire = _Wire()
    first = await _finished(account, AFTER_RELEASE)
    second = await _finished(account, AFTER_RELEASE)
    runs = SequenceRunService(
        db_manager=None, tenant_manager=TenantManager(), session=db_session, websocket_manager=wire
    )
    run = await runs.create(
        project_ids=[first.id, second.id],
        resolved_order=[first.id, second.id],
        execution_mode="claude_code_cli",
        tenant_key=account.tenant_key,
        project_statuses={first.id: "completed", second.id: "completed"},
    )

    await runs.mark_member_reviewed(run_id=run["id"], project_id=first.id, tenant_key=account.tenant_key)
    await broadcast_deferred_events(db_session)
    await runs.mark_member_reviewed(run_id=run["id"], project_id=first.id, tenant_key=account.tenant_key)
    await broadcast_deferred_events(db_session)

    [(tenant_key, _, data)] = wire.reviewed()
    assert (tenant_key, data["project_id"]) == (account.tenant_key, first.id)
    assert (await account.read()).rows.project_built.done is True
