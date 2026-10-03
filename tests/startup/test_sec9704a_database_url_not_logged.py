# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.app_state import APIState


_SECRET = "Unrelated-Passphrase-77"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "db_url",
    [
        f"postgresql://dbhost:5432/giljo?user=giljo&password={_SECRET}",
        f"postgresql:///giljo?host=/run/pg&password={_SECRET}",
        "postgresql://giljo:" + _SECRET + "@dbhost:5432/giljo",
    ],
)
async def test_the_connection_log_has_no_password(db_url):
    from api.startup.database import init_database

    manager = MagicMock()
    manager.create_tables_async = AsyncMock()
    with (
        patch("api.startup.database.get_config", return_value=MagicMock()),
        patch("api.startup.database.DatabaseManager", return_value=manager),
        patch("api.startup.database.logger") as log,
        patch.dict(os.environ, {"DATABASE_URL": db_url}),
    ):
        await init_database(APIState())

    logged = " ".join(str(arg) for call in log.method_calls for arg in call.args)
    assert "Connecting to database" in logged
    assert _SECRET not in logged
