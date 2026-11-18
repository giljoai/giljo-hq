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
from giljo_mcp.repositories.project_repository import ProjectRepository
from tests.services.test_fe0072a_start_list_service import _Account


pytestmark = pytest.mark.asyncio


@pytest.fixture
def account(db_session, db_manager) -> _Account:
    return _Account(db_session, db_manager)


async def _created(account: _Account, product_id: str, name: str, minutes_ago: int) -> Project:
    project = await account.make_project(product_id, name)
    project.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    await account.session.flush()
    return project


async def _launched(account: _Account, name: str = "Atlas build") -> Project:
    product = await account.make_product(f"Prod {uuid.uuid4().hex[:6]}")
    project = await account.make_project(product.id, name)
    await account.stage(project)
    await account.launch(project)
    return project




async def test_a_new_account_reads_six_rows_with_nothing_done(account):
    result = await account.read()

    assert result.done_count == 0
    assert result.step_count == 6
    assert result.rows.project_created.model_dump() == {"done": False, "project_id": None, "project_name": None}
    assert result.rows.project_staged.model_dump() == {
        "done": False,
        "has_project": False,
        "mode": None,
        "requested": False,
    }
    assert result.rows.project_built.model_dump() == {"done": False, "in_progress": False, "awaiting_review": False}




async def test_a_project_ticks_step_four_and_names_the_first_live_one(account):
    product = await account.make_product("Atlas")
    first = await _created(account, product.id, "First idea", 10)
    await _created(account, product.id, "Add a search box", 1)

    row = (await account.read()).rows.project_created

    assert row.model_dump() == {"done": True, "project_id": first.id, "project_name": "First idea"}


async def test_a_trashed_project_is_not_a_created_project(account):
    product = await account.make_product("Atlas")
    older = await _created(account, product.id, "Older", 10)
    newer = await _created(account, product.id, "Newer", 1)
    await account.projects.deletion.delete_project(newer.id, broadcast=False)

    row = (await account.read()).rows.project_created

    assert (row.done, row.project_id, row.project_name) == (True, older.id, "Older")

    await account.projects.deletion.delete_project(older.id, broadcast=False)
    assert (await account.read()).rows.project_created.model_dump() == {
        "done": False,
        "project_id": None,
        "project_name": None,
    }




async def test_a_staged_project_reports_its_execution_mode(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    project.execution_mode = "subagent"
    await account.stage(project)

    row = (await account.read()).rows.project_staged

    assert row.model_dump() == {"done": True, "has_project": True, "mode": "subagent", "requested": False}


async def test_a_legacy_mode_token_reads_as_one_of_the_two_modes(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    project.execution_mode = "claude_code_cli"
    await account.stage(project)

    assert (await account.read()).rows.project_staged.mode == "subagent"


async def test_a_staged_project_whose_mode_was_never_chosen_reads_mode_null(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    project.execution_mode = None
    await account.stage(project)

    row = (await account.read()).rows.project_staged

    assert (row.done, row.mode) == (True, None)


async def test_an_unstaged_project_reports_no_mode_even_when_one_is_picked(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    project.execution_mode = "multi_terminal"
    await account.session.flush()

    row = (await account.read()).rows.project_staged

    assert (row.done, row.mode) == (False, None)


async def test_the_mode_comes_from_the_newest_staged_project_not_an_unstaged_newer_one(account):
    product = await account.make_product("Atlas")
    staged = await _created(account, product.id, "Staged", 10)
    staged.execution_mode = "multi_terminal"
    await account.stage(staged)
    newer = await _created(account, product.id, "Unstaged but newer", 1)
    newer.execution_mode = "subagent"
    await account.session.flush()

    assert (await account.read()).rows.project_staged.mode == "multi_terminal"




async def test_a_launched_active_project_is_in_progress_and_not_finished(account):
    await _launched(account)

    row = (await account.read()).rows.project_built

    assert row.model_dump() == {"done": False, "in_progress": True, "awaiting_review": False}


async def test_a_staged_but_never_launched_project_is_not_in_progress(account):
    product = await account.make_product("Atlas")
    project = await account.make_project(product.id)
    await account.stage(project)

    assert (await account.read()).rows.project_built.in_progress is False


async def test_a_restaged_project_is_not_in_progress(account):
    project = await _launched(account)
    project.implementation_launched_at = None
    await account.session.flush()

    assert (await account.read()).rows.project_built.in_progress is False


@pytest.mark.parametrize("status", ["cancelled", "parked", "superseded", "terminated", "inactive"])
async def test_a_launched_project_that_stopped_being_active_is_not_in_progress(account, status):
    project = await _launched(account)
    project.status = status
    await account.session.flush()

    row = (await account.read()).rows.project_built

    assert (row.in_progress, row.done) == (False, False)


async def test_a_launched_then_cancelled_project_through_the_real_writer_is_not_in_progress(account):
    project = await _launched(account)
    await account.projects.lifecycle.cancel_project(project.id, account.tenant_key, reason="changed my mind")

    assert (await account.read()).rows.project_built.model_dump() == {
        "done": False,
        "in_progress": False,
        "awaiting_review": False,
    }


async def test_a_launched_then_trashed_project_is_not_in_progress(account):
    project = await _launched(account)
    await account.projects.deletion.delete_project(project.id, broadcast=False)

    assert (await account.read()).rows.project_built.model_dump() == {
        "done": False,
        "in_progress": False,
        "awaiting_review": False,
    }


async def test_another_tenants_launched_project_never_ticks_in_progress(account, db_session, db_manager):
    other = _Account(db_session, db_manager)
    await _launched(other)

    mine = await account.read()

    assert mine.rows.project_built.model_dump() == {"done": False, "in_progress": False, "awaiting_review": False}
    assert mine.rows.project_created.done is False
    assert mine.rows.project_staged.mode is None




async def test_a_closed_project_is_finished_and_no_longer_in_progress(account):
    project = await _launched(account)
    await account.close(project)

    assert (await account.read()).rows.project_built.model_dump() == {
        "done": True,
        "in_progress": False,
        "awaiting_review": False,
    }


async def test_a_finished_project_stays_finished_after_it_is_trashed(account):
    project = await _launched(account)
    await account.close(project)
    await account.projects.deletion.delete_project(project.id, broadcast=False)

    result = await account.read()

    assert result.rows.project_built.done is True
    assert result.rows.project_staged.has_project is False
    assert result.rows.project_created.done is False


async def test_a_trashed_project_that_was_launched_but_cancelled_never_counts_as_finished(account):
    project = await _launched(account)
    await account.projects.lifecycle.cancel_project(project.id, account.tenant_key)
    await account.projects.deletion.delete_project(project.id, broadcast=False)

    assert (await account.read()).rows.project_built.done is False


async def test_a_finished_project_whose_row_is_purged_is_no_longer_finished(account):
    project = await _launched(account)
    await account.close(project)
    await account.session.delete(project)
    await account.session.flush()

    assert (await account.read()).rows.project_built.done is False


async def test_a_finished_project_that_is_reopened_stays_finished(account):
    project = await _launched(account)
    await account.close(project)
    await account.projects.lifecycle.continue_working(project.id, tenant_key=account.tenant_key)

    row = (await account.read()).rows.project_built

    assert row.done is True




async def test_done_count_counts_all_six_rows(account):
    await account.everything_done()

    result = await account.read()

    assert (result.done_count, result.step_count) == (6, 6)


async def test_the_project_facts_carry_their_own_tenant_filter_with_the_session_guard_off(
    account, db_session, db_manager
):
    other = _Account(db_session, db_manager)
    await other.everything_done()

    with tenant_isolation_bypass(db_session, reason="FE-0072c: prove the explicit tenant filter", models=(Project,)):
        mine = await ProjectRepository().get_start_list_project_facts(db_session, account.tenant_key)
        theirs = await ProjectRepository().get_start_list_project_facts(db_session, other.tenant_key)

    assert (mine.project_id, mine.staged, mine.in_progress, mine.built) == (None, False, False, False)
    assert theirs.project_id is not None
    assert (theirs.staged, theirs.built) == (True, True)
