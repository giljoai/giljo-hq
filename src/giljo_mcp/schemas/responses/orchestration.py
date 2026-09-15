# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer


def build_next_action(*, why: str, tool: str | None = None, args_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"tool": tool, "args_hint": args_hint, "why": why}


class AgentTodoCounts(BaseModel):
    """Per-agent todo item counts by status."""

    completed: int = 0
    in_progress: int = 0
    pending: int = 0
    skipped: int = 0


class ThreadUnreadDetail(BaseModel):
    """Per-thread unread breakdown for one agent (BE-9242 deliverable #2).

    ``thread_id`` is "" for unread messages with no thread (legacy/non-hub
    direct messages) so every unread message is still accounted for.
    """

    thread_id: str
    unread_count: int


class AgentWorkflowDetail(BaseModel):
    """Per-agent detail within workflow status."""

    job_id: str
    agent_id: str
    agent_name: str = ""
    display_name: str = ""
    status: str = ""
    job_type: str = ""
    unread_messages: int = 0
    action_required_unread: int = 0
    unread_by_thread: list[ThreadUnreadDetail] = []
    todos: AgentTodoCounts = AgentTodoCounts()


class WorkflowStatus(BaseModel):
    """Workflow status for a project.

    Fields match OrchestrationService.get_workflow_status() output.
    Tracks agent execution counts and overall progress.
    """

    active_agents: int = 0
    completed_agents: int = 0
    closed_agents: int = 0
    pending_agents: int = 0
    blocked_agents: int = 0
    silent_agents: int = 0
    decommissioned_agents: int = 0
    current_stage: str = "Not started"
    progress_percent: float = 0.0
    total_agents: int = 0
    caller_note: str = ""
    agents: list[AgentWorkflowDetail] = []
    auto_checkin_enabled: bool = False
    auto_checkin_interval: int | None = None
    checkin_cadence_minutes: int | None = None

    project_closeout_at: str | None = None

    staging_status: str | None = None

    ready_to_advance: bool = False

    next_action: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class SpawnResult(BaseModel):
    """Agent spawn result.

    Fields match OrchestrationService.spawn_job() output.
    Contains both work order (job_id) and executor (agent_id) UUIDs
    plus the thin client prompt for agent startup.
    """

    job_id: str
    agent_id: str
    execution_id: str | None = None
    agent_display_name: str | None = None
    agent_prompt: str
    mission_stored: bool = True
    thin_client: bool = True
    thin_client_note: list[str] = Field(default_factory=list)
    predecessor_job_id: str | None = None
    phase: int | None = Field(
        default=None,
        description=(
            "Ordering metadata stored on the spawned execution. Echoes the "
            "`phase` arg the orchestrator passed (or None if not provided). "
            "Allows immediate verification that the server stored the value."
        ),
    )
    agent_prompt_location: str = Field(
        default="inline",
        description=(
            "Where the agent_prompt body lives. 'inline' (default) means the "
            "agent_prompt field IS the bootstrap. 'dashboard' means agent_prompt "
            "is a human-readable pointer telling the orchestrator the real prompt "
            "is in the dashboard UI for the user to copy. Set to 'dashboard' in "
            "multi_terminal mode (BE-5103)."
        ),
    )
    lifecycle_footer: str | None = Field(
        default=None,
        description=(
            "Breadcrumb: what the dashboard shows now after this call, and your next step. Plain prose, phase-computed."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


IDENTITY_RESOLVED = "resolved"
IDENTITY_ORCHESTRATOR_DEFAULT = "orchestrator_default"
IDENTITY_TEMPLATE_UNRESOLVED = "template_unresolved"
IDENTITY_TEMPLATE_UNBOUND = "template_unbound"

_HEALTHY_IDENTITY_STATUSES = frozenset({IDENTITY_RESOLVED, IDENTITY_ORCHESTRATOR_DEFAULT})


class MissionResponse(BaseModel):
    """Agent mission response.

    Fields match OrchestrationService.get_job_mission() output.
    Contains the full team-aware mission with lifecycle protocol.

    BE-9083a (truncation survival): declaration order IS the wire order (Pydantic
    serializes in declaration order), and harness-side truncation eats the TAIL of
    a large payload first. So every short critical scalar — identifiers, phase,
    the next_required_actions checklist, the truncation sentinel — is declared
    BEFORE the multi-KB blocks (mission, agent_identity, full_protocol), and
    full_protocol is declared LAST so its END-OF-PROTOCOL tail marker sits at the
    very end of the payload.
    """

    job_id: str
    agent_id: str | None = None
    agent_name: str | None = None
    agent_display_name: str | None = None
    project_id: str | None = None
    parent_job_id: str | None = None
    status: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    thin_client: bool = True
    project_phase: str | None = Field(
        default=None,
        description=(
            "CE-0026: Lifecycle phase for orchestrator executions — 'staging' or "
            "'implementation'. Derived from live project state at read time. Null "
            "for non-orchestrator agents (they don't have phase semantics)."
        ),
    )
    next_required_actions: list[str] | None = Field(
        default=None,
        description=(
            "Authoritative numbered checklist of your immediate next protocol steps, "
            "computed from live phase + role. Follow it even if later fields were "
            "truncated by your harness."
        ),
    )
    identity_source: str | None = Field(
        default=None,
        description=(
            "Where your orchestrator identity came from: a product override, an "
            "account-wide override with the date it was saved, or the built-in default."
        ),
    )
    truncation_check: str | None = Field(
        default=None,
        description=(
            "Truncation sentinel: how to verify this response arrived complete and "
            "how to recover if your harness truncated it."
        ),
    )
    protocol_toc: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Named sections of full_protocol with sizes, in slice order. If your harness "
            "truncated this response, refetch any section with get_job_mission(job_id, "
            "section=<name>) — every section fits under known harness limits."
        ),
    )
    protocol_section: str | None = Field(
        default=None,
        description="Echo of the requested section name (section-fetch responses only).",
    )
    blocked: bool = False
    error: str | None = None
    user_instruction: str | None = Field(
        default=None,
        description="Present only when blocked=True. Contains guidance for the blocked state. Null in normal responses.",
    )
    protocol_etag: str | None = Field(
        default=None,
        description="Opt-in. sha256 of the static agent_identity+full_protocol block. Absent unless requested.",
    )
    protocol_unchanged: bool = Field(
        default=False,
        description="Opt-in. True when the caller's protocol_etag matched and the static block was omitted.",
    )
    agent_profile: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The agent profile for this job: name, role, description, harness, model, effort "
            "(free-text hints; 'inherit' = same as the orchestrator), instructions, "
            "behavioral_rules and success_criteria. This payload is the authoritative source "
            "for the agent's configuration; nothing is installed on disk."
        ),
    )
    mission: str | None = None
    current_team_state: list[dict] | None = Field(
        default=None,
        description="Orchestrator-only. Live team state with agent statuses. Null for non-orchestrator agents.",
    )
    protocol_section_content: str | None = Field(
        default=None,
        description=(
            "The requested full_protocol section (section-fetch responses only), "
            "byte-identical to that slice of the full render."
        ),
    )
    agent_identity: str | None = None
    identity_status: str = Field(
        default=IDENTITY_RESOLVED,
        description=(
            "How this agent's identity resolved: 'resolved' (bound template loaded), "
            "'orchestrator_default' (composed orchestrator seed), 'template_unresolved' "
            "(the bound template was deleted), 'template_unbound' (never bound)."
        ),
    )
    full_protocol: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_serializer(mode="wrap")
    def _strip_optin_fields_when_default(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if self.protocol_etag is None:
            data.pop("protocol_etag", None)
        if not self.protocol_unchanged:
            data.pop("protocol_unchanged", None)
        if self.next_required_actions is None:
            data.pop("next_required_actions", None)
        if self.truncation_check is None:
            data.pop("truncation_check", None)
        if self.protocol_toc is None:
            data.pop("protocol_toc", None)
        if self.protocol_section is None:
            data.pop("protocol_section", None)
        if self.agent_profile is None:
            data.pop("agent_profile", None)
        if self.protocol_section_content is None:
            data.pop("protocol_section_content", None)
        if self.identity_source is None:
            data.pop("identity_source", None)
        if self.identity_status in _HEALTHY_IDENTITY_STATUSES:
            data.pop("identity_status", None)
        return data


class PendingJobsResult(BaseModel):
    """Pending jobs list result.

    Fields match OrchestrationService.get_pending_jobs() output.
    """

    jobs: list[dict] = Field(default_factory=list)
    count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ProgressResult(BaseModel):
    """Progress report result.

    Fields match OrchestrationService.report_progress() output.
    """

    status: str = "success"
    message: str = "Progress reported successfully"
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class StagingDirective(BaseModel):
    """Staging-session-end directive returned by ``complete_job`` (CE-0026).

    Populated only when the staging-phase orchestrator calls ``complete_job``
    to end its staging session. Tells the orchestrator agent to stop and
    informs it that the Implementation phase gate is now open.

    Historical note: previously emitted by the ``send_message`` broadcast
    magic with five diagnostic statuses (NOT_BROADCAST, NOT_ORCHESTRATOR,
    SENDER_NOT_FOUND, ALREADY_COMPLETE, STAGING_SESSION_COMPLETE). That
    mechanism was removed in CE-0026; the success path is the only meaningful
    case once ``complete_job`` is the canonical phase-transition tool.
    """

    status: str = "STAGING_SESSION_COMPLETE"
    action: str = "STOP"
    implementation_gate: str = "OPEN"
    message: str = (
        "STAGING IS COMPLETE. Your session must end NOW. "
        "Do NOT proceed to implementation in this session. "
        "The user will click 'Implement' in the dashboard to start "
        "a new implementation session with a fresh orchestrator execution."
    )
    next_action: dict[str, Any] | None = Field(
        default_factory=lambda: build_next_action(why="Report staging complete to user and stop.")
    )

    model_config = ConfigDict(from_attributes=True)


class CompleteJobResult(BaseModel):
    """Job completion result.

    Fields match OrchestrationService.complete_job() output.

    CE-0026: ``staging_directive`` is populated only when the staging-phase
    orchestrator calls ``complete_job`` (i.e., ``execution.project_phase ==
    'staging'`` and ``project.staging_status`` transitions to
    ``staging_complete``). For all other complete_job calls (implementation
    phase, deliverable agents) it remains None.
    """

    status: str = "success"
    job_id: str
    message: str = "Job completed successfully"
    warnings: list[str] = Field(default_factory=list)
    result_stored: bool = False
    phase: str = Field(
        default="deliverable",
        description="Which complete_job phase ran: 'staging_end' | 'closeout' | 'deliverable' (BE-6083)",
    )
    next_action: dict[str, Any] | None = Field(
        default=None,
        description="Canonical next_action envelope for this completion, phase-specific (BE-6083, BE-8003a)",
    )
    closeout_checklist: dict | None = Field(
        default=None,
        description="HITL closeout checklist (orchestrator jobs only)",
    )
    staging_directive: StagingDirective | None = Field(
        default=None,
        description="STOP directive for end-of-staging orchestrator (CE-0026)",
    )
    lifecycle_footer: str | None = Field(
        default=None,
        description=(
            "Breadcrumb: what the dashboard shows now after this completion, and your next step. "
            "Plain prose, phase-specific."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class ReactivationResult(BaseModel):
    """Reactivation result (Handover 0827c).

    Returned by OrchestrationService.reactivate_job().
    """

    status: str = "reactivated"
    job_id: str
    reactivation_count: int = 1
    instruction: str = ""

    model_config = ConfigDict(from_attributes=True)


class DismissResult(BaseModel):
    """Dismiss reactivation result (Handover 0827c).

    Returned by OrchestrationService.dismiss_reactivation().
    """

    status: str = "dismissed"
    job_id: str
    instruction: str = "Message acknowledged. No action needed. You remain in complete status."

    model_config = ConfigDict(from_attributes=True)


class ErrorReportResult(BaseModel):
    """Agent status change result (Handover 0880: expanded from report_error).

    Returned by OrchestrationService.set_agent_status() for blocked/idle/sleeping states.
    """

    job_id: str
    message: str = "Status updated"
    status: str = "blocked"
    block_reason: str | None = None
    guidance: str = "To resume, call report_progress() with updated todo_items."

    model_config = ConfigDict(from_attributes=True)


class AgentStatusChangeEvent(BaseModel):
    """One per-agent status transition surfaced for a POST-COMMIT WS broadcast (BE-9246).

    ``ProjectCloseoutService.decommission_project_agents`` / ``close_completed_agents``
    capture ``old_status`` BEFORE overwriting ``execution.status``, then return a list of
    these alongside their existing ``list[str]`` display-name return (additive -- the
    string consumers are untouched). The caller emits the actual ``agent:status_changed``
    WS event from this record only AFTER its transaction commits -- never mid-flush,
    since an earlier emit would announce a status a rollback could still undo.
    """

    job_id: str
    agent_id: str
    agent_display_name: str | None = None
    agent_name: str | None = None
    old_status: str | None = None
    new_status: str

    model_config = ConfigDict(from_attributes=True)


class JobListResult(BaseModel):
    """Paginated job list result.

    Fields match OrchestrationService.list_jobs() output.
    """

    jobs: list[dict] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0

    model_config = ConfigDict(from_attributes=True)


class MissionUpdateResult(BaseModel):
    """Mission update result.

    Fields match OrchestrationService.update_job_mission() output.
    """

    job_id: str
    mission_updated: bool = True
    mission_length: int = 0

    model_config = ConfigDict(from_attributes=True)


class SuccessionContextResult(BaseModel):
    """Successor orchestrator context result (Handover 0461f).

    Fields match OrchestrationService.create_successor_orchestrator() output.
    Same agent_id is preserved (no ID swap); context is reset and written to 360 Memory.
    """

    job_id: str
    agent_id: str
    context_reset: bool = True
    memory_entry_created: bool = True
    reason: str = "manual"
    message: str = ""

    model_config = ConfigDict(from_attributes=True)


class SuccessionStatus(BaseModel):
    """Orchestrator succession status check result.

    Fields match OrchestrationService.check_succession_status() output.
    """

    should_trigger: bool = False
    usage_percentage: float = 0.0
    threshold_reached: bool = False
    recommendation: str = ""

    model_config = ConfigDict(from_attributes=True)


InstructionsResponse = SuccessionContextResult
SuccessionResult = SuccessionContextResult
