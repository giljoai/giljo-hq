# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from giljo_mcp.tools.project_closeout import close_project_and_update_memory


closeout_module = sys.modules["giljo_mcp.tools.project_closeout"]


PROJECT_ID = "22222222-2222-2222-2222-222222222222"
PRODUCT_ID = "33333333-3333-3333-3333-333333333333"
TENANT_KEY = "tk_test"


class _FakeProject:
    def __init__(self) -> None:
        self.id = PROJECT_ID
        self.name = "Test Project"
        self.created_at = None
        self.completed_at = None


class _FakeProduct:
    def __init__(self) -> None:
        self.id = PRODUCT_ID
        self.product_memory: dict[str, Any] = {}


class _FakeEntry:
    def __init__(self) -> None:
        self.id = "entry-1"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id}


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _FakeProject()
    product = _FakeProduct()

    monkeypatch.setattr(
        closeout_module,
        "_fetch_project_and_product",
        AsyncMock(return_value=(project, product)),
    )
    monkeypatch.setattr(
        closeout_module,
        "_check_agent_readiness",
        AsyncMock(return_value=(True, [])),
    )
    monkeypatch.setattr(
        closeout_module,
        "_handle_force_close",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        closeout_module,
        "emit_websocket_event",
        AsyncMock(return_value=None),
    )

    fake_memory_service = AsyncMock()
    fake_memory_service.get_next_sequence = AsyncMock(return_value=1)
    fake_memory_service.get_closeout_entry_for_project = AsyncMock(return_value=None)
    fake_memory_service.create_entry = AsyncMock(return_value=_FakeEntry())

    monkeypatch.setattr(
        closeout_module,
        "ProductMemoryService",
        lambda *a, **kw: fake_memory_service,
    )

    fake_closeout_service = object()
    monkeypatch.setattr(
        closeout_module,
        "ProjectCloseoutService",
        lambda *a, **kw: fake_closeout_service,
    )
    monkeypatch.setattr(
        "giljo_mcp.tools._closeout_finalize.mark_chain_member_status",
        AsyncMock(return_value=False),
    )


def _make_db_manager() -> Any:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session_cm():
        yield SimpleNamespace(info={})

    db_manager = AsyncMock()
    db_manager.get_session_async = _session_cm
    return db_manager


@pytest.mark.asyncio
async def test_git_unavailable_marker_when_no_commits_supplied(monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)
    monkeypatch.delenv("GILJO_MODE", raising=False)

    db_manager = _make_db_manager()

    response = await close_project_and_update_memory(
        project_id=PROJECT_ID,
        summary="Closed without git",
        key_outcomes=["o1"],
        decisions_made=["d1"],
        tenant_key=TENANT_KEY,
        db_manager=db_manager,
        tags=["chore", "infrastructure"],
        git_commits=None,
    )

    assert response["git_commits_count"] == 0, "no commits supplied → count must be 0"
    assert response.get("git_unavailable") is True, (
        f"expected git_unavailable=True when commits empty and none supplied, got {response}"
    )
    assert isinstance(response.get("git_unavailable_reason"), str)
    assert response["git_unavailable_reason"], "reason must be non-empty when flag is set"


@pytest.mark.asyncio
async def test_no_git_unavailable_when_agent_supplies_commits(monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)
    monkeypatch.delenv("GILJO_MODE", raising=False)

    db_manager = _make_db_manager()

    response = await close_project_and_update_memory(
        project_id=PROJECT_ID,
        summary="Closed with commits",
        key_outcomes=["o1"],
        decisions_made=["d1"],
        tenant_key=TENANT_KEY,
        db_manager=db_manager,
        tags=["feature", "backend"],
        git_commits=[
            {
                "sha": "abc123def456",
                "message": "feat: add thing",
                "author": "Dev",
                "date": "2026-04-27T10:00:00Z",
            },
        ],
    )

    assert response["git_commits_count"] == 1
    assert "git_unavailable" not in response or response["git_unavailable"] is False, (
        "git_unavailable must not be set when agent supplied commits"
    )


@pytest.mark.asyncio
async def test_subprocess_filenotfound_simulated_via_empty_input(monkeypatch: pytest.MonkeyPatch):
    _patch_common(monkeypatch)
    monkeypatch.delenv("GILJO_MODE", raising=False)

    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("git not found")),
    )

    db_manager = _make_db_manager()

    response = await close_project_and_update_memory(
        project_id=PROJECT_ID,
        summary="Demo server closeout",
        key_outcomes=["o1"],
        decisions_made=["d1"],
        tenant_key=TENANT_KEY,
        db_manager=db_manager,
        tags=["chore", "infrastructure"],
        git_commits=None,
    )

    assert response["message"], "closeout must succeed, not raise"
    assert "memory" in response["message"].lower(), "the success message must confirm the memory write"
    assert response["git_commits_count"] == 0
    assert response["git_unavailable"] is True
    assert "git" in response["git_unavailable_reason"].lower()
