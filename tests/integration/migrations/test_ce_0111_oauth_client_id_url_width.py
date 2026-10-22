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


_PRE = "ce_0110_fe9789b_retire_tenant_prompt_rung"
_REV = "ce_0111_be9815_oauth_client_id_url_width"
_TABLES = ("oauth_authorization_codes", "oauth_refresh_tokens")


def _client_id_length(engine: sa.Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = 'client_id'"
            ),
            {"t": table},
        ).scalar_one()


@pytest.fixture
def scratch_at_pre(scratch_engine: sa.Engine):  # noqa: F811
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    yield scratch_engine
    _drop_all_objects(scratch_engine)


@pytest.mark.integration
class TestCe0111OauthClientIdWidth:
    def test_old_shape_is_widened(self, scratch_at_pre: sa.Engine) -> None:
        for table in _TABLES:
            assert _client_id_length(scratch_at_pre, table) == 64

        up = _run_alembic("upgrade", _REV)
        assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

        for table in _TABLES:
            assert _client_id_length(scratch_at_pre, table) == 256

    def test_rerun_over_wide_columns_is_a_no_op(self, scratch_at_pre: sa.Engine) -> None:
        assert _run_alembic("upgrade", _REV).returncode == 0
        assert _run_alembic("stamp", _PRE).returncode == 0

        rerun = _run_alembic("upgrade", _REV)

        assert rerun.returncode == 0, f"rerun failed:\n{rerun.stdout}\n{rerun.stderr}"
        for table in _TABLES:
            assert _client_id_length(scratch_at_pre, table) == 256

    def test_downgrade_narrows_the_columns(self, scratch_at_pre: sa.Engine) -> None:
        assert _run_alembic("upgrade", _REV).returncode == 0

        down = _run_alembic("downgrade", _PRE)

        assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"
        for table in _TABLES:
            assert _client_id_length(scratch_at_pre, table) == 64
