# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    task = asyncio.create_task(update_checker._update_check_loop(state))
    try:
        for _ in range(200):
            if state.update_available is not None:
                break
            await asyncio.sleep(0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class TestMainDefaultForkGetsUpdateNotices:

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
        assert "Run 'git pull', then restart your server to update." in state.update_available["message"]

    @pytest.mark.asyncio
    async def test_master_default_repo_still_sees_updates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_git, _ = _make_fake_git(default_branch="master", behind=1)
        monkeypatch.setattr(update_checker, "_run_git", fake_git)
        state = SimpleNamespace(update_available=None, websocket_manager=None)

        await _run_one_check_cycle(state)

        assert state.update_available is not None
        assert state.update_available["commits_behind"] == 1


class TestResolveDefaultBranch:

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

        async def exploding_git(*args: str) -> tuple[int, str, str]:
            raise FileNotFoundError("git binary not on PATH")

        monkeypatch.setattr(update_checker, "_run_git", exploding_git)

        assert await update_checker._resolve_default_branch("origin") == "origin/master"
