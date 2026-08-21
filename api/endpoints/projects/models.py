# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Pydantic models for projects endpoints.

Request/response models for project operations with validation.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from giljo_mcp.schemas.responses.project import ProjectBase


# ============================================================================
# CRUD Models
# ============================================================================


class ProjectCreate(BaseModel):
    """Request model for project creation."""

    name: str = Field(..., max_length=255, description="Project name")
    description: str = Field(..., description="User-written project description (what you want to accomplish)")
    mission: str = Field(
        default="", description="AI-generated mission statement (initially empty, filled by orchestrator)"
    )
    # BE-9437: min_length=1 is load-bearing, not decoration. Required-ness alone
    # admits "", which then satisfies the column's NOT NULL and dies on the
    # products foreign key as a 500. The constraint belongs at the transport so
    # the browser gets a 422 naming the field; ProjectService.create_project
    # backstops it (and catches whitespace-only) for every non-REST caller.
    product_id: str = Field(
        ..., min_length=1, description="Product ID to associate with (required; projects must belong to a product)"
    )
    status: str = Field(default="inactive", description="Project status (Handover 0050b: defaults to inactive)")
    # Handover 0260: Execution mode for Claude Code CLI toggle.
    # NULL-state redesign: no default — a project is born without a mode (NULL =
    # "not yet selected"). The user picks a mode in the dashboard; the boundary
    # gates block staging/spawn until then. Do NOT default to 'multi_terminal'.
    execution_mode: str | None = Field(
        default=None,
        description=(
            "Execution mode: 'multi_terminal' | 'subagent' | 'claude_code_cli' | 'codex_cli' | "
            "'gemini_cli' | 'antigravity_cli'; None = not yet selected"
        ),
    )
    # Handover 0440a: Project taxonomy fields
    project_type_id: str | None = Field(None, description="Project type ID for taxonomy classification")
    series_number: int | None = Field(None, description="Sequential number within a project type (e.g., 1 in BE-0001)")
    subseries: str | None = Field(None, description="Single-letter subseries suffix (e.g., 'a' in BE-0001a)")
    # FE-5073 / BE-5122 follow-up: CTX project_type renders its mission from the
    # CTX bootstrap template against the product's vision-document state. The
    # REST handler routes this through ProjectService.render_ctx_bootstrap_mission
    # (the same helper the MCP path uses) when project_type_id resolves to the
    # CTX taxonomy. Ignored for non-CTX project types.
    bootstrap_template_vars: dict | None = Field(
        None,
        description=(
            "CTX-only render inputs. Required when project_type_id resolves to the CTX taxonomy. "
            "Shape: {new_documents?: [{document_name?, document_type?, ...}]}. "
            "Caps: at most 50 new_documents; each string field at most 200 chars."
        ),
    )


class ProjectUpdate(BaseModel):
    """Request model for project updates."""

    name: str | None = Field(None, max_length=255)
    description: str | None = None
    mission: str | None = None
    status: str | None = None
    # Handover 0260: Execution mode for Claude Code CLI toggle
    execution_mode: str | None = Field(
        None,
        description=(
            "Execution mode to set: 'multi_terminal' | 'subagent' | 'claude_code_cli' | 'codex_cli' | "
            "'gemini_cli' | 'antigravity_cli'. "
            "Omit to leave unchanged (None = not part of this update). NULL on the project means not yet "
            "selected. Validated against the supported modes by the service layer."
        ),
    )
    # Handover 0440a: Project taxonomy fields
    project_type_id: str | None = None
    series_number: int | None = None
    subseries: str | None = None
    # CE-OPT-4: UI visibility flag
    hidden: bool | None = None
    # BE-9157: successor pointer, set when marking a project superseded (the
    # service validates it is a real within-tenant project and not self).
    successor_project_id: str | None = None
    # Handover 0904/0960: Orchestrator auto check-in
    auto_checkin_enabled: bool | None = None
    auto_checkin_interval: int | None = Field(
        None,
        description="Auto check-in interval in minutes (5, 10, 15, 20, 30, 40, or 60)",
    )


class AgentSimple(BaseModel):
    """Simple agent schema for project response."""

    id: str  # job_id
    job_id: str
    agent_display_name: str
    agent_name: str | None = None
    status: str
    thin_client: bool = True


class ProjectTypeInfo(BaseModel):
    """Nested project type info for project responses (Handover 0440c)."""

    id: str
    abbreviation: str
    label: str
    color: str

    model_config = ConfigDict(from_attributes=True)


class ProjectResponse(ProjectBase):
    """Response model for project details (REST).

    Inherits the universal field set from
    ``giljo_mcp.schemas.responses.project.ProjectBase`` and adds the
    presentation extras the REST consumer (frontend project page) depends
    on: ``alias``, ``staging_status``, ``implementation_launched_at``, agent
    counts + list, and the nested REST-local ``ProjectTypeInfo``.

    Overrides inherited fields to preserve the REST wire contract:
      * timestamps as ``datetime`` (Pydantic v2 normalizes to ``...Z`` ISO);
      * ``mission`` as required ``str`` (REST never emits null mission);
      * ``execution_mode`` stays ``str | None`` (NULL = mode not yet selected;
        the REST wire must report it honestly so the UI can prompt the user to
        pick — NOT fabricate ``"multi_terminal"``).
    """

    # REST-specific required identity
    alias: str

    # Override base ``str | None`` defaults with REST-strict contract types.
    # execution_mode intentionally NOT overridden to a non-null default — it
    # inherits ProjectBase's ``str | None = None`` so a NULL surfaces as null.
    mission: str
    execution_mode: str | None = None

    # Override base ``str | None`` timestamps with ``datetime`` for Z-normalized wire
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    # Detail-only fields (not on MCP ProjectData)
    staging_status: str | None = None
    # CE-0036: implementation_launched_at must flow through the REST API for
    # the frontend's useProjectCloseout guard (staging_status='staging_complete'
    # && !implementation_launched_at → button hidden). CE-0028b added this to
    # the MCP-side response schema but missed the REST schema — the one the
    # project page actually consumes — so the Close Project button never
    # appeared after impl-end. CE-0038 keeps this on the REST subclass (not
    # on ProjectBase) because the MCP ProjectData compact shape intentionally
    # omits it.
    implementation_launched_at: datetime | None = None

    # REST presentation extras
    agent_count: int
    message_count: int
    agents: list[AgentSimple] = Field(default_factory=list)

    # Nested taxonomy info (REST-local ProjectTypeInfo above; MCP has its own)
    project_type: ProjectTypeInfo | None = None  # Handover 0440c: Nested type with color


class ProjectListResponse(BaseModel):
    """Thin wire shape for the dashboard project LIST endpoints (IMP-1002).

    ``GET /api/v1/projects/`` and ``/deleted`` return one row per project for
    every dashboard reload. The list UI renders only name + status + taxonomy
    badges; the full ``mission``/``description`` bodies are fetched lazily on
    row-open via the single-project detail endpoint (``ProjectResponse``).

    This model is ``ProjectResponse`` minus ``mission``/``description`` so those
    two large free-text columns no longer ship per-row on the list wire (the
    payload grew monotonically with project count — ~434 rows). The shared
    internal ``ProjectListItem`` projection KEEPS both fields: the MCP
    ``list_projects`` planning/audit/forensic modes still read them. Only the
    REST list wire is thinned here. The single-project DETAIL endpoint continues
    to return the full ``ProjectResponse`` (mission/description intact).

    Field set is otherwise identical to ``ProjectResponse`` so the dashboard
    list keeps every badge/identity field it renders today.
    """

    # Identity
    id: str
    alias: str
    name: str
    status: str

    # Product association
    product_id: str | None = None

    # Execution config (NULL-state: real mode, None until user picks)
    execution_mode: str | None = None

    # Timestamps (datetime → Z-normalized ISO on the wire, matching ProjectResponse)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    # Staging / lifecycle
    staging_status: str | None = None
    implementation_launched_at: datetime | None = None

    # Presentation extras
    agent_count: int = 0
    message_count: int = 0
    agents: list[AgentSimple] = Field(default_factory=list)

    # Taxonomy
    project_type_id: str | None = None
    project_type: ProjectTypeInfo | None = None
    series_number: int | None = None
    subseries: str | None = None
    taxonomy_alias: str | None = None

    # UI visibility flag
    hidden: bool = False

    model_config = ConfigDict(from_attributes=True)


class ProjectDeleteResponse(BaseModel):
    """Response model for project soft delete."""

    success: bool = Field(..., description="Whether the delete operation succeeded")
    message: str = Field(..., description="User-readable result message")
    deleted_at: datetime | None = Field(
        None,
        description="Timestamp when project was marked as deleted (soft delete)",
    )


class PurgedProject(BaseModel):
    """Response model for a purged project entry."""

    id: str
    name: str
    tenant_key: str
    deleted_at: datetime | None = None


class ProjectPurgeResponse(BaseModel):
    """Response model for project purge operations."""

    success: bool
    purged_count: int
    projects: list[PurgedProject] = []
    message: str | None = None


# ============================================================================
# Summary/Status Models
# ============================================================================


class AgentSummary(BaseModel):
    """Summary of an agent used in the project (Handover 0062)."""

    id: str
    name: str
    type: str
    status: str
    job_mission: str | None = None
    job_id: str | None = None


class MessageSummary(BaseModel):
    """Summary of a message in the project (Handover 0062)."""

    id: str
    from_agent: str
    to_agents: list[str]
    content: str
    timestamp: str


class ProjectSummaryResponse(BaseModel):
    """Comprehensive project summary for after-action review (Handover 0062)."""

    project_id: str
    project_name: str
    description: str
    mission: str | None = None
    status: str
    agents: list[AgentSummary]
    messages: list[MessageSummary]
    created_at: str
    completed_at: str | None = None


# ============================================================================
# Lifecycle Models
# ============================================================================


# ============================================================================
# Completion Models
# ============================================================================


class ProjectCloseOutResponse(BaseModel):
    """Response for project close-out operation (Handover 0113)."""

    success: bool
    message: str
    agents_decommissioned: int
    decommissioned_agent_ids: list[str]
    project_status: str


class ContinueWorkingResponse(BaseModel):
    """Response for continue working operation (Handover 0113)."""

    success: bool
    message: str
    agents_resumed: int
    resumed_agent_ids: list[str]
    project_status: str


# ============================================================================
# Orchestrator Models (Handover 0135)
# ============================================================================


class OrchestratorJobResponse(BaseModel):
    """Orchestrator job details for project."""

    job_id: str
    agent_id: str  # Alias for backward compatibility
    agent_display_name: str
    agent_name: str | None
    mission: str
    status: str
    progress: int
    tool_type: str
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    detected_harness: str | None = None


class OrchestratorResponse(BaseModel):
    """Response for GET /{project_id}/orchestrator."""

    success: bool
    orchestrator: OrchestratorJobResponse | None = None  # Handover 0506: Optional when no orchestrator exists


# ============================================================================
# Taxonomy Endpoint Response Models (Handover 0440d)
# ============================================================================


class SeriesCheckResponse(BaseModel):
    """Response for GET /check-series."""

    available: bool


class UsedSubseriesResponse(BaseModel):
    """Response for GET /used-subseries."""

    used_subseries: list[str]


class NextSeriesResponse(BaseModel):
    """Response for GET /next-series."""

    next_series_number: int


class AvailableSeriesResponse(BaseModel):
    """Response for GET /available-series."""

    available_series_numbers: list[int]


# ============================================================================
# Project Review Models (IMP-3: Project detail with agents + memory)
# ============================================================================


class AgentJobDetail(BaseModel):
    """Agent job detail for project review."""

    job_id: str
    job_type: str
    status: str
    display_name: str
    agent_status: str
    mission: str | None = None
    result: dict | None = None
    created_at: str | None = None
    completed_at: str | None = None


class MemoryEntryDetail(BaseModel):
    """360 memory entry detail for project review."""

    id: str
    entry_type: str
    sequence: int
    project_name: str | None = None
    summary: str | None = None
    key_outcomes: list = Field(default_factory=list)
    decisions_made: list = Field(default_factory=list)
    git_commits: list = Field(default_factory=list)
    timestamp: str | None = None


class ProjectReviewResponse(BaseModel):
    """Extended project detail with agent jobs and 360 memory entries.

    Used by the frontend project review modal (Phase 2).
    """

    project: ProjectResponse
    agent_jobs: list[AgentJobDetail] = Field(default_factory=list)
    memory_entries: list[MemoryEntryDetail] = Field(default_factory=list)
