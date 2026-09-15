# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock, patch

import pytest


def _build_fake_conn(*, has_columns: bool, has_table: bool):
    fake_conn = MagicMock()

    def execute(stmt, params=None):
        text = str(stmt).lower()
        result = MagicMock()
        if "information_schema.columns" in text:
            result.first.return_value = (1,) if has_columns else None
        elif "information_schema.tables" in text:
            result.first.return_value = (1,) if has_table else None
        else:
            result.first.return_value = None
        return result

    fake_conn.execute.side_effect = execute
    return fake_conn


@pytest.mark.unit
def test_upgrade_is_noop_when_columns_absent_and_table_present():
    from migrations.versions import (
        ce_0009_drop_per_user_skills_tracking_add_system_announce as mig,
    )

    fake_conn = _build_fake_conn(has_columns=False, has_table=True)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "drop_column") as drop_column,
        patch.object(mig.op, "create_table") as create_table,
    ):
        mig.upgrade()

    assert drop_column.call_count == 0
    assert create_table.call_count == 0
    insert_calls = [
        call for call in fake_conn.execute.call_args_list if "INSERT INTO system_settings" in str(call.args[0])
    ]
    assert len(insert_calls) == 1


@pytest.mark.unit
def test_upgrade_drops_columns_and_creates_table_on_fresh_run():
    from migrations.versions import (
        ce_0009_drop_per_user_skills_tracking_add_system_announce as mig,
    )

    fake_conn = _build_fake_conn(has_columns=True, has_table=False)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "drop_column") as drop_column,
        patch.object(mig.op, "create_table") as create_table,
    ):
        mig.upgrade()

    assert drop_column.call_count == 2
    dropped_cols = [call.args[1] for call in drop_column.call_args_list]
    assert "last_installed_skills_version" in dropped_cols
    assert "last_update_reminder_at" in dropped_cols

    assert create_table.call_count == 1
    assert create_table.call_args.args[0] == "system_settings"


@pytest.mark.unit
def test_upgrade_seeds_announce_row_with_bundled_version():
    from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION
    from migrations.versions import (
        ce_0009_drop_per_user_skills_tracking_add_system_announce as mig,
    )

    fake_conn = _build_fake_conn(has_columns=False, has_table=True)

    with patch.object(mig.op, "get_bind", return_value=fake_conn):
        mig.upgrade()

    insert_calls = [
        call for call in fake_conn.execute.call_args_list if "INSERT INTO system_settings" in str(call.args[0])
    ]
    assert len(insert_calls) == 1
    stmt_text = str(insert_calls[0].args[0])
    assert "ON CONFLICT" in stmt_text
    params = insert_calls[0].args[1]
    assert params == {"key": "skills_version_announced", "value": SKILLS_VERSION}


@pytest.mark.unit
def test_downgrade_is_noop_on_already_downgraded_db():
    from migrations.versions import (
        ce_0009_drop_per_user_skills_tracking_add_system_announce as mig,
    )

    fake_conn = _build_fake_conn(has_columns=True, has_table=False)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "add_column") as add_column,
        patch.object(mig.op, "drop_table") as drop_table,
    ):
        mig.downgrade()

    assert add_column.call_count == 0
    assert drop_table.call_count == 0
