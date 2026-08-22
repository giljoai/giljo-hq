# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9483 item 6 — promote_lan_to_public.sh never deleted the branch it pushed.

A probe verified: scripts/promote_lan_to_public.sh creates a timestamped
``promote/*`` branch, pushes it to public GitHub, and then never deletes it on
ANY path — including the success path and every failure path that occurs
after the push. Four local ``git branch -D`` calls exist on abort paths, but
all four run BEFORE the push, so they cannot retire a pushed branch. Stale
``promote/*`` heads piled up on the public repo until hand-deleted.

The fix adds ``delete_promote_branch()``, wired into the script's existing
``cleanup()`` (already registered on ``trap cleanup EXIT``), so branch cleanup
runs on every exit path — success, every ``fail()`` call, an unexpected
``set -e`` abort, or a signal — without a bespoke delete at each call site.

This test exercises the ACTUAL shipped function, extracted verbatim from the
script between its ``delete_promote_branch begin``/``end`` markers (same
technique as ``test_promote_github_preserve.sh``'s tree-replace extraction),
against a real local git sandbox: a bare repo standing in for public GitHub,
and a working clone standing in for the script's ``$PUBLIC_LOCAL_PATH``. No
network, no real public repo, no gh/gitleaks dependency.

Safety property under test: the function only ever targets the EXACT
``$BRANCH_NAME`` this run generated — never a pattern, never "master" — and
only attempts a REMOTE delete when ``$BRANCH_PUSHED`` records that this run
actually pushed it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PROMOTE_SCRIPT = REPO_ROOT / "scripts" / "promote_lan_to_public.sh"

# On Windows, an unqualified `subprocess.run(["bash", ...])` resolves via
# CreateProcess's implicit search order, which checks System32 BEFORE PATH —
# so "bash" silently launches the WSL launcher stub at
# C:\Windows\System32\bash.exe instead of Git Bash, even though Git Bash comes
# first in PATH and `where bash`/an interactive shell both find it first. The
# WSL stub only forwards an allowlisted subset of env vars across the VM
# boundary (WSLENV), so BRANCH_NAME/PUBLIC_LOCAL_PATH/BRANCH_PUSHED vanish and
# the harness silently no-ops (BRANCH_NAME reads as unset, every test "passes"
# by doing nothing). shutil.which() walks PATH directly and is immune to that
# search-order quirk on both platforms.
BASH = shutil.which("bash") or "bash"

_BEGIN_MARKER = "delete_promote_branch begin"
_END_MARKER = "delete_promote_branch end"


def _extract_delete_promote_branch_block() -> str:
    text = PROMOTE_SCRIPT.read_text(encoding="utf-8")
    block = re.search(
        rf"# ── {re.escape(_BEGIN_MARKER)}.*?\n(.*?)# ── {re.escape(_END_MARKER)} ──",
        text,
        re.DOTALL,
    )
    assert block is not None, (
        f"could not extract delete_promote_branch — {_BEGIN_MARKER}/{_END_MARKER} "
        "markers moved or removed from scripts/promote_lan_to_public.sh"
    )
    return block.group(1)


DELETE_BLOCK = _extract_delete_promote_branch_block()


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def _build_sandbox(tmp_path: Path) -> Path:
    """Bare 'origin.git' (stands in for public GitHub) + a clone (stands in
    for $PUBLIC_LOCAL_PATH), with one commit on master already pushed."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git("init", "--bare", "-b", "master", cwd=origin)

    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", "-b", "master", cwd=seed)
    _git(
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=test",
        "commit",
        "--allow-empty",
        "-m",
        "initial",
        cwd=seed,
    )
    _git("remote", "add", "origin", str(origin), cwd=seed)
    _git("push", "origin", "master", cwd=seed)

    public = tmp_path / "public"
    _git("clone", "--quiet", str(origin), str(public), cwd=tmp_path)
    _git(
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=test",
        "config",
        "user.email",
        "test@example.com",
        cwd=public,
    )
    return public


def _run_delete_promote_branch(
    *, public_local_path: Path, branch_name: str, branch_pushed: bool
) -> subprocess.CompletedProcess:
    harness = f"""
set -uo pipefail
log()  {{ :; }}
warn() {{ echo "WARN: $*"; }}
err()  {{ :; }}
{DELETE_BLOCK}
delete_promote_branch
"""
    # Full parent environment (Git for Windows spawns msys helper processes
    # that need SYSTEMROOT/TEMP/etc. — a stripped-down env produces an opaque
    # RPC/handle error before git ever runs), with just the three inputs the
    # extracted block reads pinned to the sandbox under test.
    env = dict(os.environ)
    env["PUBLIC_LOCAL_PATH"] = str(public_local_path)
    env["BRANCH_NAME"] = branch_name
    env["BRANCH_PUSHED"] = "true" if branch_pushed else "false"
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _local_branch_exists(repo: Path, branch: str) -> bool:
    r = subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        check=False,
    )
    return r.returncode == 0


def _remote_branch_exists(origin_bare: Path, branch: str) -> bool:
    r = subprocess.run(
        ["git", "-C", str(origin_bare), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        check=False,
    )
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Behavioral tests against the real sandbox
# ---------------------------------------------------------------------------


def test_deletes_local_and_remote_branch_when_pushed(tmp_path):
    public = _build_sandbox(tmp_path)
    origin = tmp_path / "origin.git"
    branch = "promote/2099-01-01-000000"

    _git("checkout", "-b", branch, cwd=public)
    _git("push", "origin", branch, cwd=public)

    assert _local_branch_exists(public, branch)
    assert _remote_branch_exists(origin, branch)

    result = _run_delete_promote_branch(public_local_path=public, branch_name=branch, branch_pushed=True)

    assert result.returncode == 0, result.stderr
    assert not _local_branch_exists(public, branch), "local promote branch survived cleanup"
    assert not _remote_branch_exists(origin, branch), "remote promote branch survived cleanup"

    current = _git("branch", "--show-current", cwd=public).stdout.strip()
    assert current == "master", f"clone left on {current!r} instead of master after cleanup"


def test_does_not_delete_remote_when_this_run_never_pushed(tmp_path):
    """BRANCH_PUSHED=false must gate the remote delete off entirely — even if
    a branch of the same name happens to exist on the remote already."""
    public = _build_sandbox(tmp_path)
    origin = tmp_path / "origin.git"
    branch = "promote/2099-01-01-000001"

    _git("checkout", "-b", branch, cwd=public)
    _git("push", "origin", branch, cwd=public)  # exists on remote out-of-band
    assert _remote_branch_exists(origin, branch)

    result = _run_delete_promote_branch(public_local_path=public, branch_name=branch, branch_pushed=False)

    assert result.returncode == 0, result.stderr
    assert not _local_branch_exists(public, branch), "local branch should still be cleaned up"
    assert _remote_branch_exists(origin, branch), (
        "remote branch was deleted despite BRANCH_PUSHED=false — "
        "the function must never touch the remote unless THIS run pushed"
    )


def test_refuses_to_touch_master(tmp_path):
    public = _build_sandbox(tmp_path)
    origin = tmp_path / "origin.git"

    result = _run_delete_promote_branch(public_local_path=public, branch_name="master", branch_pushed=True)

    assert result.returncode == 0, result.stderr
    assert _local_branch_exists(public, "master"), "master was deleted locally!"
    assert _remote_branch_exists(origin, "master"), "master was deleted on the remote!"


@pytest.mark.parametrize(
    "bad_name",
    ["", "hotfix/urgent-fix", "master", "not-a-promote-branch"],
)
def test_refuses_empty_or_non_promote_branch_names(tmp_path, bad_name):
    public = _build_sandbox(tmp_path)
    if bad_name and bad_name != "master":
        _git("checkout", "-b", bad_name, cwd=public)
        _git("checkout", "master", cwd=public)
        assert _local_branch_exists(public, bad_name)

    result = _run_delete_promote_branch(public_local_path=public, branch_name=bad_name, branch_pushed=True)

    assert result.returncode == 0, result.stderr
    if bad_name and bad_name != "master":
        assert _local_branch_exists(public, bad_name), (
            f"non-promote branch {bad_name!r} was deleted — pattern guard failed"
        )


def test_idempotent_second_call_is_a_noop(tmp_path):
    public = _build_sandbox(tmp_path)
    branch = "promote/2099-01-01-000002"
    _git("checkout", "-b", branch, cwd=public)
    _git("push", "origin", branch, cwd=public)

    first = _run_delete_promote_branch(public_local_path=public, branch_name=branch, branch_pushed=True)
    assert first.returncode == 0, first.stderr

    second = _run_delete_promote_branch(public_local_path=public, branch_name=branch, branch_pushed=True)
    assert second.returncode == 0, second.stderr


def test_noop_when_public_local_path_missing_or_not_a_clone(tmp_path):
    result = _run_delete_promote_branch(
        public_local_path=tmp_path / "does-not-exist",
        branch_name="promote/2099-01-01-000003",
        branch_pushed=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Static no-regress checks against the shipped script
# ---------------------------------------------------------------------------


def test_cleanup_wires_in_delete_promote_branch():
    text = PROMOTE_SCRIPT.read_text(encoding="utf-8")
    cleanup_body = re.search(r"cleanup\(\)\s*\{(.*?)\n\}", text, re.DOTALL)
    assert cleanup_body is not None, "cleanup() function not found"
    assert "delete_promote_branch" in cleanup_body.group(1), (
        "cleanup() no longer calls delete_promote_branch — branch cleanup would stop firing on the EXIT trap"
    )


def test_trap_cleanup_exit_still_registered():
    text = PROMOTE_SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"^trap cleanup EXIT\s*$", text, re.MULTILINE), (
        "trap cleanup EXIT is missing — cleanup (and branch deletion) would never fire on any exit path"
    )


def test_branch_pushed_flag_set_immediately_after_the_real_push():
    """BRANCH_PUSHED=true must be set right after the actual
    `git push origin "$BRANCH_NAME"` line — not before (that would mark an
    unpushed branch as pushed) and not deferred past later fail() sites that
    exit before reaching it (that would silently un-gate their cleanup)."""
    text = PROMOTE_SCRIPT.read_text(encoding="utf-8")
    push_line = next(
        i for i, line in enumerate(text.splitlines()) if line.strip() == 'git push origin "$BRANCH_NAME" --quiet'
    )
    following = text.splitlines()[push_line + 1 : push_line + 4]
    assert any(line.strip() == "BRANCH_PUSHED=true" for line in following), (
        f"BRANCH_PUSHED=true is not set immediately after the promotion push — lines after push: {following}"
    )


def test_delete_promote_branch_never_uses_a_wildcard_or_pattern_delete():
    """The safety contract is: only the exact $BRANCH_NAME, never a glob."""
    assert "branch -D" in DELETE_BLOCK
    assert "push origin --delete" in DELETE_BLOCK
    # Every ACTUAL git invocation (lines starting with `git -C`, as opposed to
    # the operator-facing warn() strings that merely mention the command) must
    # reference the literal $BRANCH_NAME variable, not a wildcard/glob.
    invocation_lines = [
        line
        for line in DELETE_BLOCK.splitlines()
        if "git -C" in line
        and ("branch -D" in line or "push origin --delete" in line)
        and not line.strip().startswith("warn ")
    ]
    assert len(invocation_lines) == 2, (
        f"expected exactly 2 real git delete invocations, found {len(invocation_lines)}: {invocation_lines}"
    )
    for line in invocation_lines:
        assert '"$BRANCH_NAME"' in line, f"deletion line does not target the exact branch: {line}"
        assert "*" not in line, f"deletion line contains a wildcard: {line}"
