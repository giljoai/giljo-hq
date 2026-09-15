# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock, patch

import pytest


def _build_fake_conn(*, has_column: bool):
    fake_conn = MagicMock()

    def execute(stmt, params=None):
        result = MagicMock()
        text = str(stmt).lower()
        if "information_schema.columns" in text:
            result.first.return_value = (1,) if has_column else None
        else:
            result.first.return_value = None
        return result

    fake_conn.execute.side_effect = execute
    return fake_conn


@pytest.mark.unit
def test_upgrade_adds_hidden_column_when_missing():
    from migrations.versions import ce_0024_tasks_add_hidden as mig

    fake_conn = _build_fake_conn(has_column=False)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "add_column") as add_column,
    ):
        mig.upgrade()

    assert add_column.call_count == 1
    args = add_column.call_args.args
    assert args[0] == "tasks"
    column = args[1]
    assert column.name == "hidden"
    assert column.nullable is False
    assert "false" in str(column.server_default.arg).lower()


@pytest.mark.unit
def test_upgrade_is_noop_when_column_present():
    from migrations.versions import ce_0024_tasks_add_hidden as mig

    fake_conn = _build_fake_conn(has_column=True)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "add_column") as add_column,
    ):
        mig.upgrade()

    assert add_column.call_count == 0


@pytest.mark.unit
def test_downgrade_drops_column_when_present():
    from migrations.versions import ce_0024_tasks_add_hidden as mig

    fake_conn = _build_fake_conn(has_column=True)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "drop_column") as drop_column,
    ):
        mig.downgrade()

    assert drop_column.call_count == 1
    assert drop_column.call_args.args == ("tasks", "hidden")


@pytest.mark.unit
def test_downgrade_is_noop_when_column_missing():
    from migrations.versions import ce_0024_tasks_add_hidden as mig

    fake_conn = _build_fake_conn(has_column=False)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "drop_column") as drop_column,
    ):
        mig.downgrade()

    assert drop_column.call_count == 0


@pytest.mark.unit
def test_revision_chains_after_ce_0023():
    from migrations.versions import ce_0024_tasks_add_hidden as mig

    assert mig.revision == "ce_0024_tasks_add_hidden"
    assert mig.down_revision == "ce_0023_tasks_shared_taxonomy_serial"
