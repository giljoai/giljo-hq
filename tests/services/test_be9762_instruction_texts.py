# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from giljo_mcp.prompts._canonical_tool_list import CANONICAL_WORKER_TOOLS
from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder
from giljo_mcp.prompts.spawn_prompt import build_agent_prompt
from giljo_mcp.prompts.subagent_prompt_builder import SubagentPromptBuilder
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.memory_entry_write_validator import CONTROLLED_TAG_VOCABULARY
from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol
from giljo_mcp.services.protocol_sections.chapters_chain_suborch import (
    CHAIN_ESCALATION_PATH,
    _build_ch_sub_orchestrator,
)
from giljo_mcp.services.protocol_sections.chapters_reference import _CH3_CLAUDE, _CH3_CODEX
from giljo_mcp.services.protocol_sections.orchestrator_body import (
    _GIT_CONSTRAINT_SELF_ADOPT,
    _GIT_CONSTRAINT_SUBAGENT,
    CHAIN_DRIVER_MODEL,
)
from giljo_mcp.services.protocol_sections.team_context import (
    ORCHESTRATOR_TEAM_ROLE,
    _generate_team_context_header,
    summarize_mission,
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _worker_protocol(tool: str = "claude-code") -> str:
    return _generate_agent_protocol(job_id="J", tenant_key="T", agent_name="implementer", agent_id="A", tool=tool)


def _orchestrator_protocol(execution_mode: str = "subagent") -> str:
    return _generate_agent_protocol(
        job_id="J",
        tenant_key="T",
        agent_name="orchestrator",
        agent_id="A",
        execution_mode=execution_mode,
        job_type="orchestrator",
        tool="claude-code",
    )


def _agent(name: str, job_id: str, mission: str, *, display: str = "implementer", model: str | None = None):
    template = SimpleNamespace(model=model, effort="inherit") if model else None
    return SimpleNamespace(
        agent_name=name,
        agent_display_name=display,
        job_id=job_id,
        agent_id=f"agent-{job_id}",
        status="waiting",
        job=SimpleNamespace(mission=mission),
        launch_template=template,
    )


_PROJECT = SimpleNamespace(name="Text Project", id="P", product_id="PR", taxonomy_alias="BE-1")




def test_worker_start_prompt_loads_its_tool_schemas_in_one_call():
    prompt = build_agent_prompt("implementer-backend", "implementer", "P", "job-1")
    assert "Claude Code only" in prompt
    assert "ToolSearch(" in prompt
    for tool in CANONICAL_WORKER_TOOLS:
        assert tool in prompt
    assert prompt.index("ToolSearch(") < prompt.index("## STARTUP (MANDATORY)")


def test_orchestrator_start_prompt_is_unchanged_by_the_worker_line():
    assert "ToolSearch" not in build_agent_prompt("orchestrator", "orchestrator", "P", "job-1")




@pytest.mark.parametrize("builder", [ClaudePromptBuilder(), CodexPromptBuilder(), SubagentPromptBuilder()])
def test_implementation_prompt_carries_the_server_issued_launch_prompt(builder):
    agents = [
        _agent("implementer-backend", "job-1", "Build it.", model="sonnet"),
        _agent("tester", "job-2", "Test it.", display="tester"),
    ]
    prompt = builder.build_execution_prompt("orch-1", _PROJECT, agents)

    for agent in agents:
        issued = build_agent_prompt(
            agent.agent_name, agent.agent_display_name, _PROJECT.name, agent.job_id, agent.launch_template
        )
        assert issued.rstrip("\n") in prompt
    assert "Model hint: sonnet" in prompt
    assert "You are {agent_name} (job_id: {job_id})" not in prompt
    assert "You are implementer-backend (job_id: job-1)" not in prompt


@pytest.mark.parametrize("chapter", [_CH3_CLAUDE, _CH3_CODEX])
def test_ch3_spawn_reference_hands_the_agent_prompt_over_verbatim(chapter):
    text = _flat("\n".join(chapter))
    assert "agent_prompt spawn_job returned" in text or "agent_prompt that spawn_job call returned" in text
    assert "First action: get_job_mission(job_id='{job_id}')" not in text




@pytest.mark.parametrize("constraint", [_GIT_CONSTRAINT_SELF_ADOPT, _GIT_CONSTRAINT_SUBAGENT])
def test_self_adoption_is_only_for_a_harness_without_a_spawn_mechanism(constraint):
    assert "SELF-ADOPT (only when your harness has no spawn mechanism at all)" in constraint




def test_worker_report_progress_example_has_single_braces():
    protocol = _worker_protocol()
    assert '{"content": "Task 1 description", "status": "completed"}' in protocol
    assert "{{" not in protocol


def test_orchestrator_protocol_has_no_broken_character_and_no_missing_chapter():
    protocol = _orchestrator_protocol()
    assert "�" not in protocol
    assert "TODO items incomplete → review and update your TODO list" in protocol
    assert "Chapter 5" not in protocol
    for tag in CONTROLLED_TAG_VOCABULARY:
        assert tag in protocol


def test_awaiting_user_names_both_doors():
    protocol = _flat(_orchestrator_protocol())
    assert "ONLY way to clear the gate" not in protocol
    assert "decide_approval(approval_id, option_id)" in protocol
    assert "ApprovalCard" in protocol


def test_approval_refusals_name_decide_approval():
    from giljo_mcp.services import job_completion_closeout_gate, project_closeout_readiness

    for module in (job_completion_closeout_gate, project_closeout_readiness):
        assert "decide_approval(approval_id, option_id)" in inspect.getsource(module)
    assert "decide_approval(approval_id, option_id)" in inspect.getsource(JobCompletionService)




def test_mission_summary_never_cuts_a_path_in_half():
    path = "/srv/repos/acme-app/src/acme_app/services/billing/next_action.py"
    summary = summarize_mission(f"Repo: {path} first. Then " + "more words " * 30, 100)
    assert summary == f"Repo: {path} first."
    assert summarize_mission("word " * 40, 80).endswith("word...")
    assert summarize_mission("**Edition:** `Both` | x", 80) == "Edition: Both x"




def test_worker_todo_rule_matches_the_orchestrator_rule():
    protocol = _worker_protocol()
    assert "MANDATORY: Create your TodoWrite list" not in protocol
    assert "Publish them with `report_progress(todo_items=[...])`" in protocol
    assert "optional and never replaces it: do not mirror into one" in protocol




def test_team_table_lists_the_orchestrator_as_coordinator_not_as_a_deliverable():
    orchestrator = SimpleNamespace(
        agent_name="orchestrator", agent_display_name="orchestrator", agent_id="o-1", job_id="oj"
    )
    worker = SimpleNamespace(agent_name="implementer", agent_display_name="implementer", agent_id="w-1", job_id="wj")
    header = _generate_team_context_header(
        worker,
        [worker, orchestrator],
        mission_lookup={"oj": "PLAN: phase 1 does a, phase 2 does b, and so on", "wj": "Fix the hint."},
    )
    assert "This project has 1 agent(s) and its orchestrator:" in header
    assert f"| orchestrator | `o-1` | orchestrator | {ORCHESTRATOR_TEAM_ROLE} |" in header
    assert "PLAN: phase 1" not in header
    assert "| Fix the hint. |" in header




def test_rename_refusals_no_longer_claim_the_thread_is_named_after_its_project():
    from api.endpoints import comm_threads
    from api.endpoints.mcp_tools import _comm_tools
    from giljo_mcp.services import _comm_thread_edit_mixin

    for module in (_comm_tools, comm_threads, _comm_thread_edit_mixin):
        source = inspect.getsource(module)
        assert "named after its project" not in source
        assert "takes its name from that project" not in source




def test_conductor_staging_identity_carries_no_tenant_key():
    from giljo_mcp.services.conductor_staging_builder import build_conductor_staging_response
    from giljo_mcp.services.sequence_chain_context import ChainContext

    chain_ctx = ChainContext(
        run_id="run-9762",
        role="conductor",
        current_index=0,
        resolved_order=["p1", "p2"],
        is_staging=True,
        conductor_agent_id="cond-1",
        execution_mode="subagent",
    )
    response = build_conductor_staging_response(
        chain_ctx=chain_ctx, job_id="job-9762", agent_id="cond-1", tenant_key="tk_secret9762"
    )
    assert "tenant_key" not in response["identity"]
    assert "tk_secret9762" not in repr(response)




def test_chain_staging_end_states_the_driver_sentence_not_a_conductor_gate():
    _phase, _message, next_action = JobCompletionService._phase_response(
        is_staging_end=True, is_closeout_phase=False, is_chain_member_suborch=True
    )
    why = next_action["why"]
    assert "CHAIN ORCHESTRATOR" not in why
    assert "return to the dashboard" not in why
    assert CHAIN_DRIVER_MODEL in why
    assert next_action["tool"] == "get_job_mission"


@pytest.mark.parametrize("phase", [None, "implementation"])
def test_sub_orchestrator_escalates_to_whoever_drives_the_chain(phase):
    chapter = _build_ch_sub_orchestrator(
        run_id="run-1", position=2, n_projects=3, execution_mode="subagent", phase=phase
    )
    flat = _flat(chapter)
    assert _flat(CHAIN_ESCALATION_PATH) in flat
    assert "the CONDUCTOR is your escalation path" not in flat
    assert "NOT the user" not in flat
    assert "return to the dashboard" not in flat
