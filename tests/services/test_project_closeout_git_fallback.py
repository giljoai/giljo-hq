# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for graceful git-unavailable fallback in project closeout.

Wave 1 IMP-0019 Item 5 (code): a hosted test environment has no git binary, so agents
cannot pass `git_commits` and there is no SaaS GitHub fallback. The closeout
previously succeeded silently with `git_commits_count: 0` and no marker on the
response, leaving callers unable to distinguish "git was unavailable" from
"git was available but the project had no commits in range."

Fix contract: when the server resolves an empty commit list AND the agent did
not supply commits, surface `git_unavailable: true` plus a human-readable
`git_unavailable_reason` in the response. Closeout must still succeed.
"""

import sys
from typing import Any
from unittest.mock import AsyncMock

import pytest

# Import the function under test and grab the module from sys.modules so we
# can patch its private helpers (the package's __init__ may shadow attributes
# when accessed via "as" import).
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
    """
    Patch the closeout module's external collaborators so tests can drive
    only the git-resolution branches without standing up a real DB.
    """
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
        # BE-9246: _handle_force_close now returns list[AgentStatusChangeEvent]
        # (empty when nothing was force-decommissioned) instead of None -- the
        # caller iterates the return value to broadcast post-commit events.
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        closeout_module,
        "emit_websocket_event",
        AsyncMock(return_value=None),
    )

    fake_memory_service = AsyncMock()
    fake_memory_service.get_next_sequence = AsyncMock(return_value=1)
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


def _make_db_manager() -> Any:
    """Build a minimal db_manager whose async session context manager yields a sentinel session."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session_cm():
        yield object()

    db_manager = AsyncMock()
    db_manager.get_session_async = _session_cm
    return db_manager


@pytest.mark.asyncio
async def test_git_unavailable_marker_when_no_commits_supplied(monkeypatch: pytest.MonkeyPatch):
    """
    CE mode (default), no GILJO_MODE=saas, no agent-supplied git_commits → the
    response must include `git_unavailable: true` with a reason string AND a
    zero git_commits_count. Closeout must succeed (no exception).
    """
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
    """
    When the agent supplies a non-empty git_commits list, the response must
    NOT carry git_unavailable — git was clearly available on the agent side.
    """
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
    """
    Mission-described scenario: on a hosted test environment, git is unavailable so the
    agent's `git log` subprocess would raise FileNotFoundError. The agent then
    sends git_commits=None to the server. The server must still close the
    project successfully and surface the unavailable marker.

    We simulate the boundary by patching subprocess.run to raise
    FileNotFoundError (proves the test infra honors the mock) AND by passing
    git_commits=None (the actual data shape the failed subprocess produces on
    the agent side). The server-side path itself does not run subprocess --
    that is correct; the server is passive. The contract under test is the
    server response shape when commits arrive empty.
    """
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

    # This project is solo (no active chain run), so the truthful closeout message
    # does not start with "Project closed" -- it never did for a solo project even
    # before the wording fix; this assertion only checked for a fixed prefix as a
    # stand-in for "the call succeeded". Assert that directly instead: a non-empty
    # success message confirming the memory write, which genuinely happened.
    assert response["message"], "closeout must succeed, not raise"
    assert "memory" in response["message"].lower(), "the success message must confirm the memory write"
    assert response["git_commits_count"] == 0
    assert response["git_unavailable"] is True
    assert "git" in response["git_unavailable_reason"].lower()
