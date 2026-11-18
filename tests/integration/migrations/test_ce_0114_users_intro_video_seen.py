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


_PRE = "ce_0113_sec9837_connected_apps"
_REV = "ce_0114_fe0072e_users_intro_video_seen"


@pytest.fixture
def scratch_at_pre(scratch_engine: sa.Engine):  # noqa: F811
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    yield scratch_engine
    _drop_all_objects(scratch_engine)


def _seed_user(engine: sa.Engine, uid: str, *, with_flag: bool) -> None:
    columns = "id, tenant_key, username, failed_pin_attempts, must_change_password, must_set_pin, is_system_user, role, is_active"
    values = ":id, :tk, :un, 0, FALSE, FALSE, FALSE, 'admin', TRUE"
    if with_flag:
        columns += ", intro_video_seen"
        values += ", DEFAULT"
    with engine.connect() as conn:
        conn.execute(
            text(f"INSERT INTO users ({columns}) VALUES ({values})"),
            {"id": uid, "tk": "tk_" + uid, "un": "user_" + uid},
        )
        conn.commit()


def _flag(engine: sa.Engine, uid: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT intro_video_seen FROM users WHERE id = :id"), {"id": uid}).scalar()


@pytest.mark.integration
class TestCe0114UsersIntroVideoSeen:
    def test_existing_accounts_end_seen_and_new_accounts_end_unseen(self, scratch_at_pre: sa.Engine) -> None:
        _seed_user(scratch_at_pre, "u_before", with_flag=False)

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"
        _seed_user(scratch_at_pre, "u_after", with_flag=True)

        assert _flag(scratch_at_pre, "u_before") is True, "an account that existed before must count as seen"
        assert _flag(scratch_at_pre, "u_after") is False, "an account created after must start unseen"

    def test_a_rerun_is_a_noop_and_does_not_mark_a_new_account_seen(self, scratch_at_pre: sa.Engine) -> None:
        _seed_user(scratch_at_pre, "u_before", with_flag=False)
        assert _run_alembic("upgrade", _REV).returncode == 0
        _seed_user(scratch_at_pre, "u_after", with_flag=True)

        assert _run_alembic("stamp", _PRE).returncode == 0
        rerun = _run_alembic("upgrade", _REV)
        assert rerun.returncode == 0, f"rerun failed:\n{rerun.stdout}\n{rerun.stderr}"

        assert _flag(scratch_at_pre, "u_before") is True
        assert _flag(scratch_at_pre, "u_after") is False, "the rerun must not mark a real new account as seen"

    def test_downgrade_removes_the_column_and_upgrade_restores_it(self, scratch_at_pre: sa.Engine) -> None:
        assert _run_alembic("upgrade", _REV).returncode == 0
        down = _run_alembic("downgrade", _PRE)
        assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"
        columns = {c["name"] for c in sa.inspect(scratch_at_pre).get_columns("users")}
        assert "intro_video_seen" not in columns
        assert _run_alembic("upgrade", _REV).returncode == 0
