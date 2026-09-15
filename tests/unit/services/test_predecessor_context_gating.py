# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.services._predecessor_context import (
    PREDECESSOR_BASE_BRANCH_BLOCK,
    PREDECESSOR_CHAIN_PREAMBLE,
    PREDECESSOR_REPLACEMENT_PREAMBLE,
    SUBAGENT_EXECUTION_MODES,
    _build_base_branch_block,
    _detect_replacement_semantics,
    build_predecessor_context,
)


_TEST_LOGGER = logging.getLogger(__name__)




def _pred_job(status: str = "waiting", project_id: str = "proj-1"):
    return SimpleNamespace(project_id=project_id, status=status)


def _pred_execution(result_status: str | None = None, *, display_name: str = "analyzer"):
    result: dict = {"summary": "Analysis complete.", "commits": ["c1", "c2"]}
    if result_status is not None:
        result["status"] = result_status
    return SimpleNamespace(agent_display_name=display_name, result=result)


def _install_repo(monkeypatch, *, pred_job, pred_execution=None) -> MagicMock:
    repo_instance = MagicMock()
    repo_instance.get_predecessor_job = AsyncMock(return_value=pred_job)
    repo_instance.get_completed_execution_for_job = AsyncMock(return_value=pred_execution)
    monkeypatch.setattr(
        "giljo_mcp.services._predecessor_context.AgentCompletionRepository",
        MagicMock(return_value=repo_instance),
    )
    return repo_instance


@pytest.fixture
def fake_repo_clean_completion(monkeypatch) -> MagicMock:
    return _install_repo(
        monkeypatch,
        pred_job=_pred_job(status="complete"),
        pred_execution=_pred_execution(),
    )


@pytest.fixture
def fake_repo_pre_execution(monkeypatch) -> MagicMock:
    return _install_repo(
        monkeypatch,
        pred_job=_pred_job(status="waiting"),
        pred_execution=None,
    )




def test_subagent_execution_modes_set_is_subagent_plus_the_five_legacy_aliases():
    assert (
        frozenset({"subagent", "claude_code_cli", "codex_cli", "gemini_cli", "antigravity_cli", "generic_mcp"})
        == SUBAGENT_EXECUTION_MODES
    )


def test_multi_terminal_is_not_a_subagent_mode():
    assert "multi_terminal" not in SUBAGENT_EXECUTION_MODES


def test_chain_preamble_uses_forward_handoff_language():
    text = PREDECESSOR_CHAIN_PREAMBLE
    assert "PRIOR PHASE OUTPUT" in text
    assert "continuing a workflow" in text
    assert "replacing a previous agent" not in text
    assert "issues were found" not in text
    assert "REPLACEMENT" not in text


def test_replacement_preamble_uses_replacement_language():
    text = PREDECESSOR_REPLACEMENT_PREAMBLE
    assert "REPLACEMENT" in text
    assert "taking over" in text


def test_neither_preamble_leaks_tenant_key():
    assert "tenant_key" not in PREDECESSOR_CHAIN_PREAMBLE
    assert "tenant_key" not in PREDECESSOR_REPLACEMENT_PREAMBLE




def test_detect_returns_false_when_predecessor_is_pre_execution():
    assert _detect_replacement_semantics(_pred_job(status="waiting"), None) is False


def test_detect_returns_false_when_predecessor_is_running():
    assert _detect_replacement_semantics(_pred_job(status="working"), None) is False


def test_detect_returns_false_for_clean_completion():
    assert _detect_replacement_semantics(_pred_job(status="complete"), _pred_execution()) is False


@pytest.mark.parametrize("job_status", ["failed", "blocked", "decommissioned"])
def test_detect_returns_true_for_failed_job_status(job_status: str):
    assert _detect_replacement_semantics(_pred_job(status=job_status), None) is True


def test_detect_returns_true_for_failed_job_status_case_insensitive():
    assert _detect_replacement_semantics(_pred_job(status="FAILED"), None) is True


@pytest.mark.parametrize("result_status", ["force_completed", "failed", "blocked", "error"])
def test_detect_returns_true_for_failure_result_status(result_status: str):
    assert (
        _detect_replacement_semantics(_pred_job(status="complete"), _pred_execution(result_status=result_status))
        is True
    )


def test_detect_returns_true_for_failure_result_status_case_insensitive():
    assert (
        _detect_replacement_semantics(_pred_job(status="complete"), _pred_execution(result_status="FORCE_COMPLETED"))
        is True
    )


def test_detect_returns_false_for_unknown_result_status():
    assert (
        _detect_replacement_semantics(
            _pred_job(status="complete"), _pred_execution(result_status="succeeded_with_warnings")
        )
        is False
    )


def test_detect_returns_false_when_both_signals_absent():
    assert _detect_replacement_semantics(None, None) is False




@pytest.mark.parametrize("subagent_mode", sorted(SUBAGENT_EXECUTION_MODES))
@pytest.mark.asyncio
async def test_subagent_mode_returns_mission_unchanged(
    fake_repo_clean_completion: MagicMock, subagent_mode: str
) -> None:
    original_mission = "Implement the new feature according to spec."
    result = await build_predecessor_context(
        session=None,
        predecessor_job_id="pred-1",
        tenant_key="tk-test",
        project_id="proj-1",
        mission=original_mission,
        agent_display_name="implementer",
        execution_mode=subagent_mode,
        logger=_TEST_LOGGER,
    )
    assert result == original_mission


@pytest.mark.asyncio
async def test_multi_terminal_pre_execution_predecessor_injects_chain_preamble(
    fake_repo_pre_execution: MagicMock,
) -> None:
    result = await build_predecessor_context(
        session=None,
        predecessor_job_id="pred-1",
        tenant_key="tk-test",
        project_id="proj-1",
        mission="Implement.",
        agent_display_name="implementer",
        execution_mode="multi_terminal",
        logger=_TEST_LOGGER,
    )
    assert "PRIOR PHASE OUTPUT" in result
    assert "continuing a workflow" in result
    assert "REPLACEMENT" not in result
    assert "replacing a previous agent" not in result


@pytest.mark.asyncio
async def test_multi_terminal_clean_completion_injects_chain_preamble(
    fake_repo_clean_completion: MagicMock,
) -> None:
    result = await build_predecessor_context(
        session=None,
        predecessor_job_id="pred-1",
        tenant_key="tk-test",
        project_id="proj-1",
        mission="Implement.",
        agent_display_name="implementer",
        execution_mode="multi_terminal",
        logger=_TEST_LOGGER,
    )
    assert "PRIOR PHASE OUTPUT" in result
    assert "REPLACEMENT" not in result


@pytest.mark.parametrize("job_status", ["failed", "blocked", "decommissioned"])
@pytest.mark.asyncio
async def test_multi_terminal_failed_job_injects_replacement_preamble(monkeypatch, job_status: str) -> None:
    _install_repo(
        monkeypatch,
        pred_job=_pred_job(status=job_status),
        pred_execution=None,
    )
    result = await build_predecessor_context(
        session=None,
        predecessor_job_id="pred-1",
        tenant_key="tk-test",
        project_id="proj-1",
        mission="Pick up.",
        agent_display_name="implementer",
        execution_mode="multi_terminal",
        logger=_TEST_LOGGER,
    )
    assert "REPLACEMENT" in result
    assert "PRIOR PHASE OUTPUT" not in result


@pytest.mark.parametrize("result_status", ["force_completed", "failed", "blocked", "error"])
@pytest.mark.asyncio
async def test_multi_terminal_force_completed_predecessor_injects_replacement_preamble(
    monkeypatch, result_status: str
) -> None:
    _install_repo(
        monkeypatch,
        pred_job=_pred_job(status="complete"),
        pred_execution=_pred_execution(result_status=result_status),
    )
    result = await build_predecessor_context(
        session=None,
        predecessor_job_id="pred-1",
        tenant_key="tk-test",
        project_id="proj-1",
        mission="Pick up.",
        agent_display_name="implementer",
        execution_mode="multi_terminal",
        logger=_TEST_LOGGER,
    )
    assert "REPLACEMENT" in result




@pytest.mark.asyncio
async def test_predecessor_validated_even_when_subagent_skips(monkeypatch) -> None:
    _install_repo(monkeypatch, pred_job=None)
    with pytest.raises(ResourceNotFoundError):
        await build_predecessor_context(
            session=None,
            predecessor_job_id="bogus-id",
            tenant_key="tk-test",
            project_id="proj-1",
            mission="x",
            agent_display_name="impl",
            execution_mode="claude_code_cli",
            logger=_TEST_LOGGER,
        )


@pytest.mark.asyncio
async def test_cross_project_predecessor_rejected_even_when_subagent_skips(
    monkeypatch,
) -> None:
    _install_repo(monkeypatch, pred_job=_pred_job(status="waiting", project_id="proj-OTHER"))
    with pytest.raises(ValidationError, match="different project"):
        await build_predecessor_context(
            session=None,
            predecessor_job_id="pred-x",
            tenant_key="tk-test",
            project_id="proj-1",
            mission="x",
            agent_display_name="impl",
            execution_mode="gemini_cli",
            logger=_TEST_LOGGER,
        )




def _pred_execution_isolated_pr(branch: str, pr_url: str | None = None, *, display_name: str = "web-coder"):
    result: dict = {"summary": "Delivered as PR.", "commits": ["c1"], "branch": branch}
    if pr_url is not None:
        result["pr_url"] = pr_url
    return SimpleNamespace(agent_display_name=display_name, result=result)


def test_base_branch_block_helper_renders_branch_and_optional_pr():
    with_pr = _build_base_branch_block({"branch": "feat/job1-foo", "pr_url": "https://git.example/pr/5"})
    assert "feat/job1-foo" in with_pr
    assert "https://git.example/pr/5" in with_pr
    assert "BASE BRANCH" in with_pr

    without_pr = _build_base_branch_block({"branch": "feat/job1-foo"})
    assert "feat/job1-foo" in without_pr
    assert "Predecessor PR" not in without_pr


def test_base_branch_block_helper_empty_without_branch():
    assert _build_base_branch_block({"summary": "no branch here"}) == ""
    assert _build_base_branch_block({"branch": "   "}) == ""
    assert _build_base_branch_block({}) == ""


def test_base_branch_block_constant_is_neutral_and_leaks_no_tenant_key():
    assert "tenant_key" not in PREDECESSOR_BASE_BRANCH_BLOCK
    assert "chain hand-off" in PREDECESSOR_BASE_BRANCH_BLOCK


@pytest.mark.asyncio
async def test_isolated_pr_predecessor_injects_branch_into_successor_seed(monkeypatch) -> None:
    job1_branch = "feat/job1-auth-endpoint"
    pr_url = "https://gitea.internal/org/repo/pulls/42"
    _install_repo(
        monkeypatch,
        pred_job=_pred_job(status="complete"),
        pred_execution=_pred_execution_isolated_pr(job1_branch, pr_url),
    )
    rendered = await build_predecessor_context(
        session=None,
        predecessor_job_id="job-1",
        tenant_key="tk-test",
        project_id="proj-1",
        mission="Build the profile page on top of the auth endpoint.",
        agent_display_name="web-coder-2",
        execution_mode="multi_terminal",
        logger=_TEST_LOGGER,
    )
    assert job1_branch in rendered
    assert "BASE BRANCH" in rendered
    assert pr_url in rendered
    assert "PRIOR PHASE OUTPUT" in rendered
    assert "Build the profile page" in rendered


@pytest.mark.asyncio
async def test_shared_working_tree_predecessor_injects_no_base_branch_block(monkeypatch) -> None:
    _install_repo(
        monkeypatch,
        pred_job=_pred_job(status="complete"),
        pred_execution=_pred_execution(),
    )
    rendered = await build_predecessor_context(
        session=None,
        predecessor_job_id="job-1",
        tenant_key="tk-test",
        project_id="proj-1",
        mission="Continue the work.",
        agent_display_name="implementer-2",
        execution_mode="multi_terminal",
        logger=_TEST_LOGGER,
    )
    assert "BASE BRANCH" not in rendered
    assert "PRIOR PHASE OUTPUT" in rendered


@pytest.mark.asyncio
async def test_isolated_pr_branch_skipped_in_subagent_mode(monkeypatch) -> None:
    _install_repo(
        monkeypatch,
        pred_job=_pred_job(status="complete"),
        pred_execution=_pred_execution_isolated_pr("feat/job1-foo"),
    )
    original = "Do the next phase."
    rendered = await build_predecessor_context(
        session=None,
        predecessor_job_id="job-1",
        tenant_key="tk-test",
        project_id="proj-1",
        mission=original,
        agent_display_name="impl",
        execution_mode="subagent",
        logger=_TEST_LOGGER,
    )
    assert rendered == original
