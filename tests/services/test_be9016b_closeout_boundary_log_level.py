# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import sys
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.tools.project_closeout import close_project_and_update_memory


closeout_module = sys.modules["giljo_mcp.tools.project_closeout"]

BOUNDARY_LOGGER = "giljo_mcp.tools.project_closeout"
PROJECT_ID = "44444444-4444-4444-4444-444444444444"
TENANT_KEY = "tk_test"


def _make_db_manager() -> Any:

    @asynccontextmanager
    async def _session_cm():
        yield object()

    db_manager = AsyncMock()
    db_manager.get_session_async = _session_cm
    return db_manager


@pytest.mark.asyncio
async def test_domain_rejection_logged_at_info_not_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(
        closeout_module,
        "_fetch_project_and_product",
        AsyncMock(side_effect=ResourceNotFoundError("Project not found or unauthorized for tenant")),
    )
    caplog.set_level(logging.INFO, logger=BOUNDARY_LOGGER)

    with pytest.raises(ResourceNotFoundError):
        await close_project_and_update_memory(
            project_id=PROJECT_ID,
            summary="x",
            key_outcomes=["o1"],
            decisions_made=["d1"],
            tenant_key=TENANT_KEY,
            db_manager=_make_db_manager(),
            tags=["chore", "backend"],
        )

    boundary_records = [r for r in caplog.records if r.name == BOUNDARY_LOGGER]

    assert any(r.levelno == logging.INFO and "close_project rejected" in r.getMessage() for r in boundary_records), (
        "expected an INFO 'close_project rejected' record, got: "
        f"{[(r.levelname, r.getMessage()) for r in boundary_records]}"
    )
    assert not any(r.levelno >= logging.ERROR for r in boundary_records), (
        "a <500 domain rejection must not log at ERROR (Sentry noise): "
        f"{[(r.levelname, r.getMessage()) for r in boundary_records]}"
    )
