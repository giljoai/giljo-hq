# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, ProgrammingError

from api.app_state import APIState


class _DriverError(Exception):
    def __init__(self, message: str, sqlstate: str):
        super().__init__(message)
        self.sqlstate = sqlstate


async def _boot_with_create_all_raising(monkeypatch, exc: Exception) -> None:
    from api.startup.database import init_database

    monkeypatch.setenv("GILJO_MODE", "")
    with (
        patch("api.startup.database.get_config") as get_config,
        patch("api.startup.database.DatabaseManager") as manager,
        patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/test"}),
    ):
        get_config.return_value = MagicMock()
        instance = MagicMock()
        instance.create_tables_async = AsyncMock(side_effect=exc)
        manager.return_value = instance
        await init_database(APIState())


@pytest.mark.asyncio
async def test_duplicate_table_by_sqlstate_is_tolerated(monkeypatch):
    exc = ProgrammingError("CREATE INDEX", {}, _DriverError('relation "ix_x" exists', "42P07"))
    await _boot_with_create_all_raising(monkeypatch, exc)


@pytest.mark.asyncio
async def test_an_unrelated_error_mentioning_already_exists_is_not_hidden(monkeypatch):
    exc = IntegrityError("INSERT", {}, _DriverError("Key (name)=(x) already exists.", "23505"))
    with pytest.raises(IntegrityError):
        await _boot_with_create_all_raising(monkeypatch, exc)
