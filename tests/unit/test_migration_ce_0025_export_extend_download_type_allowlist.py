# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock, patch

import pytest


def _build_fake_conn(*, has_constraint: bool):
    fake_conn = MagicMock()

    def execute(stmt, params=None):
        result = MagicMock()
        rendered = str(stmt).lower()
        if "information_schema.table_constraints" in rendered:
            result.first.return_value = (1,) if has_constraint else None
        else:
            result.first.return_value = None
        return result

    fake_conn.execute.side_effect = execute
    return fake_conn


@pytest.mark.unit
def test_upgrade_replaces_constraint_when_present():
    from migrations.versions import ce_0025_export_extend_download_type_allowlist as mig

    fake_conn = _build_fake_conn(has_constraint=True)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "drop_constraint") as drop_c,
        patch.object(mig.op, "create_check_constraint") as create_c,
    ):
        mig.upgrade()

    assert drop_c.call_count == 1
    assert drop_c.call_args.args == ("ck_download_token_type", "download_tokens")
    assert drop_c.call_args.kwargs == {"type_": "check"}

    assert create_c.call_count == 1
    name, table, condition = create_c.call_args.args
    assert name == "ck_download_token_type"
    assert table == "download_tokens"
    assert "'tenant_export'" in condition
    assert "'slash_commands'" in condition
    assert "'agent_templates'" in condition


@pytest.mark.unit
def test_upgrade_creates_constraint_when_missing():
    from migrations.versions import ce_0025_export_extend_download_type_allowlist as mig

    fake_conn = _build_fake_conn(has_constraint=False)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "drop_constraint") as drop_c,
        patch.object(mig.op, "create_check_constraint") as create_c,
    ):
        mig.upgrade()

    assert drop_c.call_count == 0
    assert create_c.call_count == 1


@pytest.mark.unit
def test_downgrade_restores_two_value_allowlist():
    from migrations.versions import ce_0025_export_extend_download_type_allowlist as mig

    fake_conn = _build_fake_conn(has_constraint=True)

    with (
        patch.object(mig.op, "get_bind", return_value=fake_conn),
        patch.object(mig.op, "drop_constraint") as drop_c,
        patch.object(mig.op, "create_check_constraint") as create_c,
    ):
        mig.downgrade()

    assert drop_c.call_count == 1
    assert create_c.call_count == 1
    _, _, condition = create_c.call_args.args
    assert "'tenant_export'" not in condition
    assert "'slash_commands'" in condition
    assert "'agent_templates'" in condition


@pytest.mark.unit
def test_revision_chains_after_ce_0024():
    from migrations.versions import ce_0025_export_extend_download_type_allowlist as mig

    assert mig.revision == "ce_0025_export_extend_download_type_allowlist"
    assert mig.down_revision == "ce_0024_tasks_add_hidden"
