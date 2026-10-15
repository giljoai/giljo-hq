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
    scratch_engine,  # noqa: F401  (fixture)
)


_PRE = "ce_0108_fe9708_project_reviewed_at"
_REV = "ce_0109_be9755_template_proposals"


@pytest.fixture
def scratch_at_rev(scratch_engine: sa.Engine):  # noqa: F811
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _REV)
    assert up.returncode == 0, f"upgrade to {_REV} failed:\n{up.stdout}\n{up.stderr}"
    yield scratch_engine
    _drop_all_objects(scratch_engine)


def _insert(engine: sa.Engine, row_id: str, slot_key: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO template_proposals (id, tenant_key, target_kind, slot_key, proposed_text, reason) "
                "VALUES (:id, 'tk_a', 'orchestrator_additions', :slot, 'text', 'why')"
            ),
            {"id": row_id, "slot": slot_key},
        )


@pytest.mark.integration
class TestCe0109TemplateProposals:
    def test_rerun_over_an_existing_table_is_a_no_op_that_keeps_rows(self, scratch_at_rev: sa.Engine) -> None:
        _insert(scratch_at_rev, "p1", "orchestrator_additions:tenant")

        assert _run_alembic("stamp", _PRE).returncode == 0
        rerun = _run_alembic("upgrade", _REV)
        assert rerun.returncode == 0, f"rerun failed:\n{rerun.stdout}\n{rerun.stderr}"

        with scratch_at_rev.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM template_proposals")).scalar() == 1

    def test_one_waiting_proposal_per_slot_is_enforced(self, scratch_at_rev: sa.Engine) -> None:
        _insert(scratch_at_rev, "p1", "orchestrator_additions:tenant")
        with pytest.raises(sa.exc.IntegrityError):
            _insert(scratch_at_rev, "p2", "orchestrator_additions:tenant")

    def test_downgrade_drops_the_table(self, scratch_at_rev: sa.Engine) -> None:
        down = _run_alembic("downgrade", _PRE)
        assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"
        with scratch_at_rev.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('template_proposals')")).scalar() is None
