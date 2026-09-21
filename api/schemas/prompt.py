# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from giljo_mcp.platform_registry import SUBAGENT_TOOL_TYPES




class AgentPromptResponse(BaseModel):
    """
    Schema for agent prompt generation response.
    GET /api/prompts/agent/{agent_id}
    """

    prompt: str = Field(..., description="Multi-line bash commands for agent execution")
    agent_id: str = Field(..., description="Agent job ID")
    agent_name: str = Field(..., description="Agent display name")
    agent_display_name: str = Field(..., description="Human-readable display name for UI")
    tool_type: str = Field(..., description="Tool assigned: claude-code, codex, universal")
    instructions: str = Field(..., description="User-readable instructions for using the prompt")
    mission_preview: str = Field(..., description="First 200 chars of mission")

    model_config = ConfigDict(from_attributes=True)




class AgentStatusSummary(BaseModel):
    """
    Schema for agent status counts in closeout check.
    """

    complete: int = Field(..., description="Count of completed agents")
    failed: int = Field(..., description="Count of failed agents")
    active: int = Field(..., description="Count of active agents (working, preparing, review)")
    blocked: int = Field(..., description="Count of blocked agents")

    model_config = ConfigDict(from_attributes=True)


class ProjectCanCloseResponse(BaseModel):
    """
    Schema for project closeout readiness check.
    GET /api/projects/{project_id}/can-close
    """

    can_close: bool = Field(..., description="Whether project can be closed")
    summary: str | None = Field(None, description="AI-generated summary (if can_close=True)")
    agent_statuses: AgentStatusSummary = Field(..., description="Breakdown of agent statuses")
    all_agents_finished: bool = Field(..., description="Whether all agents have finished")

    model_config = ConfigDict(from_attributes=True)


class ProjectCloseoutPromptResponse(BaseModel):
    """
    Schema for project closeout prompt generation.
    POST /api/projects/{project_id}/generate-closeout
    """

    prompt: str = Field(..., description="Multi-line bash script for closeout")
    checklist: list[str] = Field(..., description="Closeout checklist items")
    project_name: str = Field(..., description="Project name")
    agent_summary: str = Field(..., description="Summary of agent work")

    model_config = ConfigDict(from_attributes=True)


class ProjectCompleteRequest(BaseModel):
    """
    Schema for completing a project.
    POST /api/projects/{project_id}/complete
    """

    summary: str = Field(
        ...,
        min_length=50,
        max_length=5000,
        description="Comprehensive project summary (2-3 paragraphs)",
    )
    key_outcomes: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="List of tangible deliverables/achievements",
    )
    decisions_made: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="List of architectural/technical decisions",
    )
    git_commits: list[dict] = Field(
        default_factory=list,
        max_length=200,
        description=(
            "Optional agent/operator-supplied git commits captured at closeout. "
            "Each item: {sha (required), message (required), author?, date?, "
            "files_changed?, lines_added?}. Omission = empty = no commits "
            "(back-compat). Per-field shape is validated downstream by "
            "validate_git_commits / GitCommitEntry."
        ),
    )
    confirm_closeout: bool = Field(..., description="Must be True to confirm closeout")

    model_config = ConfigDict(from_attributes=True)


class ProjectCompleteResponse(BaseModel):
    """
    Schema for project completion response.
    """

    success: bool = Field(..., description="Whether project was successfully completed")
    completed_at: str = Field(..., description="Completion timestamp (ISO format)")
    memory_updated: bool = Field(..., description="Whether 360 Memory was updated")
    sequence_number: int = Field(..., description="Sequential history entry number")
    git_commits_count: int = Field(..., description="Number of commits captured (if GitHub enabled)")

    model_config = ConfigDict(from_attributes=True)


class ProjectCloseoutDataResponse(BaseModel):
    """
    Schema for project closeout data response.
    GET /api/projects/{project_id}/closeout

    Returns basic project metadata for closeout.
    Frontend fetches 360 memory entries directly from the product.
    """

    project_id: str = Field(..., description="Project UUID")
    project_name: str = Field(..., description="Project name")
    agent_count: int = Field(..., ge=0, description="Number of agents in the project")
    completed_agents: int = Field(..., ge=0, description="Number of completed agents")
    blocked_agents: int = Field(..., ge=0, description="Number of blocked agents")
    silent_agents: int = Field(0, ge=0, description="Number of silent agents")
    all_agents_complete: bool = Field(..., description="Whether all agents finished work")
    has_blocked_agents: bool = Field(..., description="Whether any agents are blocked")

    model_config = ConfigDict(from_attributes=True)




class OrchestratorPromptRequest(BaseModel):
    """
    Schema for thin client orchestrator prompt request.
    POST /api/prompts/orchestrator
    """

    project_id: str = Field(..., min_length=1, description="Project UUID")
    tool: Literal[SUBAGENT_TOOL_TYPES] = Field("claude-code", description="Target AI tool")

    model_config = ConfigDict(from_attributes=True)


class StagingPromptResponse(BaseModel):
    """
    Schema for staging prompt generation response.
    GET /api/prompts/staging/{project_id}

    Returns the thin client staging prompt with orchestrator metadata.
    """

    orchestrator_id: str = Field(..., description="Created orchestrator job ID")
    agent_id: str | None = Field(None, description="Executor agent ID for MCP tool calls")
    prompt: str = Field(..., description="Staging prompt for orchestrator")
    estimated_prompt_tokens: int = Field(..., description="Token estimate for the staging prompt")

    model_config = ConfigDict(from_attributes=True)


class ThinOrchestratorPromptResponse(BaseModel):
    """
    Schema for thin orchestrator prompt response.
    POST /api/prompts/orchestrator-thin

    Returns a thin prompt with orchestrator metadata for the thin client architecture.
    """

    success: bool = Field(..., description="Whether prompt generation succeeded")
    orchestrator_id: str = Field(..., description="Created orchestrator job ID")
    prompt: str = Field(..., description="Thin orchestrator prompt")
    estimated_prompt_tokens: int = Field(..., description="Token estimate for prompt")
    thin_client: bool = Field(default=True, description="Always True for thin client architecture")
    status: str = Field(..., description="Orchestrator readiness status")

    model_config = ConfigDict(from_attributes=True)


class ImplementationPromptResponse(BaseModel):
    """
    Schema for implementation prompt response (Handover 0337).
    GET /api/prompts/implementation/{project_id}
    """

    prompt: str = Field(..., description="Implementation prompt for orchestrator to spawn agents")
    orchestrator_job_id: str = Field(..., description="Orchestrator job UUID")
    agent_count: int = Field(..., description="Number of spawned agents ready to execute")
    ready_to_close: bool = Field(
        default=False,
        description="True when all specialist agents are already complete and the project is ready to close",
    )

    model_config = ConfigDict(from_attributes=True)


class TerminationPromptResponse(BaseModel):
    """
    Schema for termination prompt response (Handover 0498).
    GET /api/v1/prompts/termination/{project_id}
    """

    prompt: str = Field(..., description="Termination prompt for user to paste into orchestrator terminal")
    orchestrator_job_id: str = Field(..., description="Orchestrator job UUID")
    agent_count: int = Field(..., description="Number of agents included in termination prompt")

    model_config = ConfigDict(from_attributes=True)


class ChainPromptResponse(BaseModel):
    """
    Schema for chain conductor prompt responses (BE-6165d).
    GET /api/v1/prompts/chain-staging/{run_id}
    GET /api/v1/prompts/chain-implementation/{run_id}

    Returns a THIN bootstrap prompt for the chain run's dedicated, project-less
    conductor — the single prompt the user pastes to stage or drive the whole
    chain. The bootstrap carries the conductor's identity and tells it to fetch
    its own full chain protocol over MCP (get_staging_instructions for staging,
    get_job_mission for implementation); since BE-6191 the protocol chapters are
    named here, never pasted in. The conductor owns no project of its own, so
    this response is about the chain, not about the head project.
    """

    run_id: str = Field(..., description="Chain run UUID")
    head_project_id: str = Field(..., description="Head project UUID (resolved_order[0])")
    orchestrator_job_id: str = Field(
        ...,
        description=("Job UUID of the chain's dedicated, project-less conductor (not the head project's orchestrator)"),
    )
    prompt: str = Field(..., description="Thin conductor bootstrap prompt (fetches its chain protocol over MCP)")

    model_config = ConfigDict(from_attributes=True)


class ChainMemberPromptResponse(BaseModel):
    """
    Schema for a single chain MEMBER's orchestrator prompt (FE-9629).
    GET /api/v1/prompts/chain-member/{project_id}

    A chain runs one project at a time, and each member starts from its own play
    button the way a single project does. This is the prompt behind that button:
    the same thin bootstrap the conductor gets, addressed to THIS member's own
    orchestrator, which stages and implements this one project and stops when it
    closes out. The next member's button unlocks then.
    """

    run_id: str = Field(..., description="Chain run UUID this project is a member of")
    project_id: str = Field(..., description="Member project UUID the prompt is for")
    orchestrator_job_id: str = Field(..., description="Job UUID of this member's own orchestrator")
    prompt: str = Field(..., description="Thin orchestrator bootstrap prompt (fetches its protocol over MCP)")

    model_config = ConfigDict(from_attributes=True)
