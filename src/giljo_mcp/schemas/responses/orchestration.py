# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Orchestration service response models."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer


def build_next_action(*, why: str, tool: str | None = None, args_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the canonical `next_action` response-envelope object (BE-8003a).

    Single shared shape for every tool response that carries forward guidance —
    replaces the 5 legacy field names (`next_step`, `action_required`,
    `suggested_actions`, `guidance`, and the pre-existing plain-string
    `next_action`) with one machine-readable envelope: `{"tool", "args_hint", "why"}`.

    `tool=None` means the directive does not correspond to an MCP tool call the
    agent should make right now (e.g. "stop and wait for a human") — `why` still
    carries the instruction text. Use a bare top-level `None` (not this helper)
    for a genuinely open-ended response with no forward guidance to give at all.
    """
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
    # BE-9242 deliverable #3: the subset of unread_messages (the broader
    # badge total) that is genuinely requires_action + non-auto_generated --
    # i.e. the subset that will actually block complete_job. Sourced from the
    # same gate-definition query the closeout gate uses, in
    # agent_completion_repository's get_unread_messages_for_agent method,
    # aggregated per agent. A badge>0 with action_required_unread==0 will NOT
    # block completion.
    action_required_unread: int = 0
    # BE-9242 deliverable #2: WHICH thread(s) the unread total lives on.
    # sum(t.unread_count for t in unread_by_thread) == unread_messages by
    # construction (same "unread" definition, thread_id added to the group-by).
    unread_by_thread: list[ThreadUnreadDetail] = []
    todos: AgentTodoCounts = AgentTodoCounts()


class WorkflowStatus(BaseModel):
    """Workflow status for a project.

    Fields match OrchestrationService.get_workflow_status() output.
    Tracks agent execution counts and overall progress.
    """

    active_agents: int = 0
    completed_agents: int = 0
    # BE-9541: a ``closed`` execution is terminal-done (TERMINAL_EXECUTION_STATUSES
    # groups it with "complete"), but was never counted anywhere -- a project
    # whose sole agent was closed reported 0 completed / 0% / "Unknown" stage.
    # Additive; defaults 0 for every pre-existing caller.
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
    # BE-6013: live auto check-in slider state so a running multi-terminal
    # orchestrator re-reads the current cadence (and on/off) every cycle
    # instead of using the value baked into its prompt at boot.
    # FE-9296b: the slider is retired; these two raw-column fields are kept for
    # in-flight orchestrators whose CH6 prose still reads them (tolerance).
    auto_checkin_enabled: bool = False
    auto_checkin_interval: int | None = None
    # FE-9296b: the RESOLVED check-in cadence (project override -> tenant
    # override -> account default). New CH6 prose reads THIS every cycle.
    checkin_cadence_minutes: int | None = None

    # BE-6188: CH_CHAIN_DRIVE polls this field to detect when a sub-orch's project
    # is closed out (the conductor's advance signal). Additive; defaults None for
    # solo / non-chain projects. ISO 8601 string or None.
    project_closeout_at: str | None = None

    # BE-6193: the project's staging_status so the chain orchestrator's drive loop can
    # detect when a spawned sub-orch reached "staging_complete" (the moment to cross its
    # gate). Additive; None for solo / non-chain callers. Read from project.staging_status.
    staging_status: str | None = None

    # BE-6208f: single authoritative advance signal for the chain conductor.
    # current_stage/progress_percent report "Completed"/100% while
    # project_closeout_at is still null for ~2 min (agents flip complete before
    # the closeout writes), so they are the WRONG advance trigger. This derived
    # flag is True ONLY once closeout has actually executed. Additive; defaults
    # False. Computed at the service read boundary, not stored.
    ready_to_advance: bool = False

    # BE-8003a: canonical next_action envelope, derived ONLY from the agent
    # counts + ready_to_advance already computed above (no new queries). None
    # when the caller genuinely has nothing forced to do next (agents still
    # actively working/pending).
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
    # CE-0033 Task 9: echo `phase` so orchestrators can verify ordering intent
    # persisted without an extra get_workflow_status round-trip.
    phase: int | None = Field(
        default=None,
        description=(
            "Ordering metadata stored on the spawned execution. Echoes the "
            "`phase` arg the orchestrator passed (or None if not provided). "
            "Allows immediate verification that the server stored the value."
        ),
    )
    # BE-5103: signal whether agent_prompt body is the real bootstrap or a pointer.
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
    # BE-9083b: lifecycle breadcrumb footer — plain prose stating what the
    # dashboard now shows (agent:created) and the next step, computed from live
    # phase (protocol_survival.build_spawn_footer). Additive.
    lifecycle_footer: str | None = Field(
        default=None,
        description=(
            "Breadcrumb: what the dashboard shows now after this call, and your next step. Plain prose, phase-computed."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# BE-9333: identity-resolution status vocabulary (the wire contract, so it lives
# with the field). Two healthy outcomes and two degraded ones; only the degraded
# pair is serialized, so the key's presence is itself the signal.
# ---------------------------------------------------------------------------
IDENTITY_RESOLVED = "resolved"  # bound template loaded
IDENTITY_ORCHESTRATOR_DEFAULT = "orchestrator_default"  # composed orchestrator seed (by design)
IDENTITY_TEMPLATE_UNRESOLVED = "template_unresolved"  # bound, then the template was deleted
IDENTITY_TEMPLATE_UNBOUND = "template_unbound"  # never bound to any template

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
    # BE-9083a: numbered phase-x-role checklist of the agent's exact next protocol
    # steps, computed server-side from LIVE state (protocol_survival module).
    # Rides EARLY so it survives tail truncation of the multi-KB blocks below.
    # None (stripped from the wire by the serializer below) on blocked/legacy
    # responses where no cell can be determined.
    next_required_actions: list[str] | None = Field(
        default=None,
        description=(
            "Authoritative numbered checklist of your immediate next protocol steps, "
            "computed from live phase + role. Follow it even if later fields were "
            "truncated by your harness."
        ),
    )
    # FE-9408: where the orchestrator identity in this response came from — the
    # product rung, the account-wide rung, or the built-in seed. A short scalar, so it
    # rides HERE (before the multi-KB blocks) and survives the tail truncation that
    # eats agent_identity: an agent that lost its persona to truncation can still say
    # which one it was owed. None (and stripped) for every non-orchestrator identity
    # and for a withheld one.
    identity_source: str | None = Field(
        default=None,
        description=(
            "Where your orchestrator identity came from: a product override, an "
            "account-wide override with the date it was saved, or the built-in default."
        ),
    )
    # BE-9083a: head truncation sentinel — states the payload size and how to verify
    # the END-OF-PROTOCOL tail marker arrived; names the recovery path. None (and
    # stripped) when full_protocol is absent (blocked / etag-match responses).
    truncation_check: str | None = Field(
        default=None,
        description=(
            "Truncation sentinel: how to verify this response arrived complete and "
            "how to recover if your harness truncated it."
        ),
    )
    # BE-9083d: section-fetch recovery TOC. Present whenever full_protocol ships (and
    # on section responses); rides EARLY so a truncated receiver still learns the
    # section names. Each entry: {"section", "chars", "lines"}, in exact slice order.
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
    # BE-6208g: OPT-IN protocol cache signal. Populated ONLY when the caller passed a
    # `protocol_etag` to get_job_mission (a known cached static-block hash). When the
    # caller omits it, both fields stay at default and are STRIPPED from the serialized
    # payload by the model_serializer below — so the wire response is byte-identical to
    # today for every existing (non-opt-in) caller. When opted in: `protocol_etag` is the
    # sha256 of the static identity+protocol block; if it matches the caller's hash,
    # `protocol_unchanged` is True and the static block (agent_identity / full_protocol)
    # is omitted so the caller reuses its cache.
    protocol_etag: str | None = Field(
        default=None,
        description="Opt-in. sha256 of the static agent_identity+full_protocol block. Absent unless requested.",
    )
    protocol_unchanged: bool = Field(
        default=False,
        description="Opt-in. True when the caller's protocol_etag matched and the static block was omitted.",
    )
    # BE-9083a: the multi-KB blocks serialize LAST (see class docstring). mission is
    # the smallest of the three; full_protocol carries the END-OF-PROTOCOL tail
    # marker and must be the final field on the wire.
    mission: str | None = None
    current_team_state: list[dict] | None = Field(
        default=None,
        description="Orchestrator-only. Live team state with agent statuses. Null for non-orchestrator agents.",
    )
    # BE-9083d: the requested slice on a section-fetch response — byte-identical to
    # the corresponding slice of the full render (single-render-then-slice). The
    # multi-KB blocks below are nulled on such a response.
    protocol_section_content: str | None = Field(
        default=None,
        description=(
            "The requested full_protocol section (section-fetch responses only), "
            "byte-identical to that slice of the full render."
        ),
    )
    agent_identity: str | None = None
    # BE-9333: WHY agent_identity looks the way it does. An empty identity used to be
    # indistinguishable from a healthy one (blocked false, error null), so an agent whose
    # template was deleted mid-run degraded silently with nothing to correlate against.
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
        """Omit the opt-in / conditional fields unless they carry data.

        Guarantees byte-identical wire output for every caller that does not opt in
        to the protocol_etag mechanism (BE-6208g), and keeps worker/legacy/blocked
        responses free of empty BE-9083a survival keys: the four conditional keys
        never appear in the serialized payload while at their defaults.
        """
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
        if self.protocol_section_content is None:
            data.pop("protocol_section_content", None)
        # FE-9408: absent rather than null when there is no identity to attribute, so
        # every worker/blocked/withheld response stays byte-identical to before.
        if self.identity_source is None:
            data.pop("identity_source", None)
        # BE-9333: identity_status rides the wire ONLY when the identity is DEGRADED.
        # 'resolved' and 'orchestrator_default' are the two healthy, by-design outcomes and
        # say nothing actionable, so omitting them keeps every healthy response
        # byte-identical. The key's PRESENCE is therefore itself the signal.
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
    # BE-8003a: canonical envelope (was `next_step: str`). `tool=None` = no MCP
    # tool call to make right now; `why` still carries the directive text.
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
    # BE-6083: complete_job is overloaded three ways, switched on hidden
    # server-side state (staging-end / deliverable-done / orchestrator-closeout).
    # These two fields make the overload TRANSPARENT — the response self-explains
    # which phase just ran and the next action, so the agent does not have to
    # know its own phase to interpret the result.
    phase: str = Field(
        default="deliverable",
        description="Which complete_job phase ran: 'staging_end' | 'closeout' | 'deliverable' (BE-6083)",
    )
    # BE-8003a: canonical envelope object (was `str`). See build_next_action().
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
    # BE-9083b: lifecycle breadcrumb footer — plain prose stating what the
    # dashboard now shows and the next step, phase-specific (staging_end /
    # closeout / deliverable) via protocol_survival.build_complete_job_footer.
    # Additive; agrees with phase/message/next_action.
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


# Legacy aliases for backward compatibility with existing imports.
InstructionsResponse = SuccessionContextResult
SuccessionResult = SuccessionContextResult
