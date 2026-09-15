# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import update


@contextmanager
def _patched_alembic(heads: list[str], script_head: str = "ce_head"):
    from alembic.util import CommandError

    ctx = MagicMock()
    ctx.get_current_heads.return_value = heads
    if len(heads) > 1:
        ctx.get_current_revision.side_effect = CommandError("Version table has more than one head present")
    else:
        ctx.get_current_revision.return_value = heads[0] if heads else None

    conn = MagicMock()
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn

    script = MagicMock()
    script.get_current_head.return_value = script_head

    with (
        patch.object(update, "ROOT") as root,
        patch("alembic.config.Config"),
        patch("alembic.script.ScriptDirectory.from_config", return_value=script),
        patch("alembic.runtime.migration.MigrationContext.configure", return_value=ctx),
        patch("sqlalchemy.create_engine", return_value=engine),
    ):
        root.__truediv__.return_value.exists.return_value = True
        yield


def test_multihead_db_does_not_crash_and_returns_first_head():
    with _patched_alembic(heads=["saas_020_x", "ce_0042_y"], script_head="ce_0042_y"):
        current, head = update._get_revisions("postgresql://fake/db")

    assert current == "saas_020_x"
    assert head == "ce_0042_y"


def test_single_head_unchanged():
    with _patched_alembic(heads=["ce_0042_y"], script_head="ce_0042_y"):
        current, head = update._get_revisions("postgresql://fake/db")

    assert current == "ce_0042_y"
    assert head == "ce_0042_y"


def test_empty_head_returns_none():
    with _patched_alembic(heads=[], script_head="ce_0042_y"):
        current, head = update._get_revisions("postgresql://fake/db")

    assert current is None
    assert head == "ce_0042_y"
