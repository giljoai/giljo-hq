# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock, patch

import pytest


def _build_fake_conn(*, has_table: bool, has_index: bool, has_check: bool = False):
    fake_conn = MagicMock()

    def execute(stmt, params=None):
        text = str(stmt).lower()
        result = MagicMock()
        if "information_schema.table_constraints" in text:
            result.first.return_value = (1,) if has_check else None
        elif "information_schema.tables" in text:
            result.first.return_value = (1,) if has_table else None
        elif "pg_indexes" in text:
            result.first.return_value = (1,) if has_index else None
        else:
            result.first.return_value = None
        return result

    fake_conn.execute.side_effect = execute
    return fake_conn


def _patch_op(mig):
    return [
        patch.object(mig.op, "create_table"),
        patch.object(mig.op, "create_index"),
        patch.object(mig.op, "drop_index"),
        patch.object(mig.op, "drop_table"),
        patch.object(mig.op, "drop_constraint"),
        patch.object(mig.op, "create_check_constraint"),
    ]


@pytest.mark.unit
def test_upgrade_creates_table_and_indexes_on_fresh_db():
    from migrations.versions import ce_0018_user_approvals as mig

    fake_conn = _build_fake_conn(has_table=False, has_index=False)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "create_table") as create_table,
        patch.object(mig.op, "create_index") as create_index,
        patch.object(mig.op, "drop_constraint"),
        patch.object(mig.op, "create_check_constraint") as create_check,
    ):
        mig.upgrade()

    assert create_table.call_count == 1
    assert create_table.call_args.args[0] == "user_approvals"
    assert create_index.call_count == 3
    assert create_check.call_count == 1
    assert create_check.call_args.args[0] == "ck_agent_execution_status"
    assert "awaiting_user" in create_check.call_args.args[2]


@pytest.mark.unit
def test_upgrade_is_noop_when_table_and_indexes_present():
    from migrations.versions import ce_0018_user_approvals as mig

    fake_conn = _build_fake_conn(has_table=True, has_index=True)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "create_table") as create_table,
        patch.object(mig.op, "create_index") as create_index,
        patch.object(mig.op, "drop_constraint"),
        patch.object(mig.op, "create_check_constraint"),
    ):
        mig.upgrade()

    assert create_table.call_count == 0
    assert create_index.call_count == 0


@pytest.mark.unit
def test_downgrade_drops_indexes_and_table_when_present():
    from migrations.versions import ce_0018_user_approvals as mig

    fake_conn = _build_fake_conn(has_table=True, has_index=True, has_check=True)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "drop_index") as drop_index,
        patch.object(mig.op, "drop_table") as drop_table,
        patch.object(mig.op, "drop_constraint") as drop_constraint,
        patch.object(mig.op, "create_check_constraint") as create_check,
    ):
        mig.downgrade()

    assert drop_index.call_count == 3
    assert drop_table.call_count == 1
    assert drop_table.call_args.args[0] == "user_approvals"
    assert drop_constraint.call_count == 1
    assert drop_constraint.call_args.args[0] == "ck_agent_execution_status"
    assert create_check.call_count == 1
    assert create_check.call_args.args[0] == "ck_agent_execution_status"
    assert create_check.call_args.args[2] == mig._AGENT_STATUS_CHECK_OLD
    assert "awaiting_user" not in create_check.call_args.args[2]


@pytest.mark.unit
def test_downgrade_is_noop_when_table_absent():
    from migrations.versions import ce_0018_user_approvals as mig

    fake_conn = _build_fake_conn(has_table=False, has_index=False)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "drop_index") as drop_index,
        patch.object(mig.op, "drop_table") as drop_table,
        patch.object(mig.op, "drop_constraint"),
        patch.object(mig.op, "create_check_constraint"),
    ):
        mig.downgrade()

    assert drop_index.call_count == 0
    assert drop_table.call_count == 0


@pytest.mark.unit
def test_revision_chain_extends_ce_0017():
    from migrations.versions import ce_0018_user_approvals as mig

    assert mig.revision == "ce_0018_user_approvals"
    assert mig.down_revision == "ce_0017_tasks_add_series_number_subseries"
