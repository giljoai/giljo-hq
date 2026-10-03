# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from tests.integration.migrations.test_ce_0088_completed_at_backfill import (
    _drop_all_objects,
    _run_alembic,
    _seed_product,
    _seed_project,
    scratch_engine,  # noqa: F401  (fixture)
)


_PRE = "ce_0107_db9639_drop_tasks_due_date"
_REV = "ce_0108_fe9708_project_reviewed_at"
COMPLETED_TS = "2026-07-01 10:00:00+00"


@pytest.fixture
def scratch_at_pre(scratch_engine: sa.Engine):  # noqa: F811
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    _seed_product(scratch_engine)
    yield scratch_engine
    _drop_all_objects(scratch_engine)


def _reviewed_at(engine: sa.Engine, project_id: str):
    with engine.connect() as conn:
        return conn.execute(text("SELECT reviewed_at FROM projects WHERE id = :id"), {"id": project_id}).scalar()


@pytest.mark.integration
class TestCe0108ProjectReviewedAt:
    def test_finished_projects_are_backfilled_as_reviewed_and_live_ones_are_not(
        self, scratch_at_pre: sa.Engine
    ) -> None:
        stamp = "2026-07-02 00:00:00+00"
        _seed_project(
            scratch_at_pre, "p_done_dated", status="completed", series=1, updated_at=stamp, completed_at=COMPLETED_TS
        )
        _seed_project(scratch_at_pre, "p_done_undated", status="completed", series=2, updated_at=stamp)
        _seed_project(scratch_at_pre, "p_cancelled", status="cancelled", series=3, updated_at=stamp)
        _seed_project(scratch_at_pre, "p_terminated", status="terminated", series=4, updated_at=stamp)
        _seed_project(scratch_at_pre, "p_inactive", status="inactive", series=5, updated_at=stamp)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"

        with scratch_at_pre.connect() as conn:
            same = conn.execute(
                text("SELECT reviewed_at = completed_at FROM projects WHERE id = 'p_done_dated'")
            ).scalar()
        assert same is True, "a dated completed project is reviewed at its completion time"
        for pid in ("p_done_undated", "p_cancelled", "p_terminated"):
            assert _reviewed_at(scratch_at_pre, pid) is not None, f"{pid} must count as reviewed"
        assert _reviewed_at(scratch_at_pre, "p_inactive") is None

    def test_a_rerun_does_not_stamp_a_project_that_finished_after_the_first_run(
        self, scratch_at_pre: sa.Engine
    ) -> None:
        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, up.stderr
        _seed_project(
            scratch_at_pre,
            "p_late",
            status="completed",
            series=9,
            updated_at=COMPLETED_TS,
            completed_at=COMPLETED_TS,
        )
        assert _reviewed_at(scratch_at_pre, "p_late") is None

        assert _run_alembic("stamp", _PRE).returncode == 0
        rerun = _run_alembic("upgrade", _REV)
        assert rerun.returncode == 0, f"rerun failed:\n{rerun.stdout}\n{rerun.stderr}"

        assert _reviewed_at(scratch_at_pre, "p_late") is None, "the rerun must not mark a real unreviewed project"
