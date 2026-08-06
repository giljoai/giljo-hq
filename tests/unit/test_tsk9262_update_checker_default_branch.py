# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9262: git-mode update checker must follow the remote's DEFAULT branch.

Bug: ``_update_check_loop`` hardcoded ``branch = f"{remote}/master"``. A CE fork
whose remote default branch is ``main`` got a clean ``rev-list`` failure every
cycle (count=None -> "leave state unchanged"), so update notices silently never
appeared. The failing layer is the update-checker loop itself, so the regression
test drives the loop against a mocked git whose remote HEAD points at ``main``.

Fix under test: ``_resolve_default_branch()`` reads
``git symbolic-ref refs/remotes/<remote>/HEAD`` (with a ``git remote set-head
<remote> --auto`` retry when the symbolic ref is unset) and falls back to
``<remote>/master`` on any git error, preserving graceful-None behavior.
"""

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from api.startup import update_checker


def _make_fake_git(
    *,
    default_branch: str = "main",
    symbolic_ref_set: bool = True,
    set_head_works: bool = True,
    behind: int = 3,
):
    """Fake ``_run_git`` for a repo whose remote default branch is *default_branch*.

    ``rev-list HEAD..origin/<default_branch>`` succeeds with *behind*; rev-list
    against any other ref fails like real git ("bad revision"). Returns the fake
    and a mutable call-state dict for assertions.
    """
    call_state = {"set_head_called": False, "symref_set": symbolic_ref_set}

    async def fake_run_git(*args: str) -> tuple[int, str, str]:
        if args[0] == "symbolic-ref":
            if call_state["symref_set"]:
                return 0, f"origin/{default_branch}", ""
            return 128, "", "fatal: ref refs/remotes/origin/HEAD is not a symbolic ref"
        if args[:2] == ("remote", "set-head"):
            call_state["set_head_called"] = True
            if set_head_works:
                call_state["symref_set"] = True
                return 0, f"origin/HEAD set to {default_branch}", ""
            return 1, "", "error: Could not determine remote HEAD"
        if args[0] == "fetch":
            return 0, "", ""
        if args[0] == "rev-list":
            target = args[1]
            if target == f"HEAD..origin/{default_branch}":
                return 0, str(behind), ""
            return 128, "", f"fatal: bad revision '{target}'"
        return 0, "", ""

    return fake_run_git, call_state


async def _run_one_check_cycle(state) -> None:
    """Drive ``_update_check_loop`` through its first check, then cancel it."""
    task = asyncio.create_task(update_checker._update_check_loop(state))
    try:
        # The fake git calls resolve in a handful of event-loop turns; poll until
        # the first cycle lands or the budget runs out (loop then sits in its 6h sleep).
        for _ in range(200):
            if state.update_available is not None:
                break
            await asyncio.sleep(0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class TestMainDefaultForkGetsUpdateNotices:
    """The previously-silent failure: remote HEAD -> main must still produce a
    working update check."""

    @pytest.mark.asyncio
    async def test_fork_defaulting_to_main_sees_updates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_git, _ = _make_fake_git(default_branch="main", behind=3)
        monkeypatch.setattr(update_checker, "_run_git", fake_git)
        state = SimpleNamespace(update_available=None, websocket_manager=None)

        await _run_one_check_cycle(state)

        assert state.update_available is not None, (
            "a fork whose remote default branch is 'main' silently saw no update notice"
        )
        assert state.update_available["commits_behind"] == 3
        # The neutral CE update message must be preserved verbatim.
        assert "Run 'git pull', then restart your server to update." in state.update_available["message"]

    @pytest.mark.asyncio
    async def test_master_default_repo_still_sees_updates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mainline guard: the stock master-default clone keeps working."""
        fake_git, _ = _make_fake_git(default_branch="master", behind=1)
        monkeypatch.setattr(update_checker, "_run_git", fake_git)
        state = SimpleNamespace(update_available=None, websocket_manager=None)

        await _run_one_check_cycle(state)

        assert state.update_available is not None
        assert state.update_available["commits_behind"] == 1


class TestResolveDefaultBranch:
    """Unit coverage for the resolution ladder: symbolic-ref -> set-head retry -> master."""

    @pytest.mark.asyncio
    async def test_symbolic_ref_present_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_git, call_state = _make_fake_git(default_branch="main", symbolic_ref_set=True)
        monkeypatch.setattr(update_checker, "_run_git", fake_git)

        assert await update_checker._resolve_default_branch("origin") == "origin/main"
        assert not call_state["set_head_called"], "set-head must not run when the symbolic ref is set"

    @pytest.mark.asyncio
    async def test_unset_symbolic_ref_recovers_via_set_head_auto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_git, call_state = _make_fake_git(default_branch="main", symbolic_ref_set=False, set_head_works=True)
        monkeypatch.setattr(update_checker, "_run_git", fake_git)

        assert await update_checker._resolve_default_branch("origin") == "origin/main"
        assert call_state["set_head_called"], "documented fallback: git remote set-head <remote> --auto"

    @pytest.mark.asyncio
    async def test_detection_dead_end_falls_back_to_master(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_git, _ = _make_fake_git(default_branch="main", symbolic_ref_set=False, set_head_works=False)
        monkeypatch.setattr(update_checker, "_run_git", fake_git)

        assert await update_checker._resolve_default_branch("origin") == "origin/master"

    @pytest.mark.asyncio
    async def test_git_error_falls_back_to_master(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Graceful-None discipline: any git-layer error degrades to the old default."""

        async def exploding_git(*args: str) -> tuple[int, str, str]:
            raise FileNotFoundError("git binary not on PATH")

        monkeypatch.setattr(update_checker, "_run_git", exploding_git)

        assert await update_checker._resolve_default_branch("origin") == "origin/master"
