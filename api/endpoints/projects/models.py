# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from giljo_mcp.schemas.responses.project import ProjectBase




class ProjectCreate(BaseModel):
    """Request model for project creation."""

    name: str = Field(..., max_length=255, description="Project name")
    description: str = Field(..., description="User-written project description (what you want to accomplish)")
    mission: str = Field(
        default="", description="AI-generated mission statement (initially empty, filled by orchestrator)"
    )
    product_id: str = Field(
        ..., min_length=1, description="Product ID to associate with (required; projects must belong to a product)"
    )
    status: str = Field(default="inactive", description="Project status (Handover 0050b: defaults to inactive)")
    execution_mode: str | None = Field(
        default=None,
        description=(
            "Execution mode: 'multi_terminal' | 'subagent' (legacy per-CLI tokens such as "
            "'claude_code_cli' | 'codex_cli' are tolerated); None = not yet selected"
        ),
    )
    project_type_id: str | None = Field(None, description="Project type ID for taxonomy classification")
    series_number: int | None = Field(None, description="Sequential number within a project type (e.g., 1 in BE-0001)")
    subseries: str | None = Field(None, description="Single-letter subseries suffix (e.g., 'a' in BE-0001a)")
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
    execution_mode: str | None = Field(
        None,
        description=(
            "Execution mode to set: 'multi_terminal' | 'subagent' (legacy per-CLI tokens such as "
            "'claude_code_cli' | 'codex_cli' are tolerated). "
            "Omit to leave unchanged (None = not part of this update). NULL on the project means not yet "
            "selected. Validated against the supported modes by the service layer."
        ),
    )
    project_type_id: str | None = None
    series_number: int | None = None
    subseries: str | None = None
    hidden: bool | None = None
    successor_project_id: str | None = None
    auto_checkin_enabled: bool | None = None
    auto_checkin_interval: int | None = Field(
        None,
        description="Auto check-in interval in minutes (5, 10, 15, 20, 30, 40, or 60)",
    )


class AgentSimple(BaseModel):
    """Simple agent schema for project response."""

    id: str
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

    alias: str

    mission: str
    execution_mode: str | None = None

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    staging_status: str | None = None
    implementation_launched_at: datetime | None = None

    agent_count: int
    message_count: int
    agents: list[AgentSimple] = Field(default_factory=list)

    project_type: ProjectTypeInfo | None = None


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

    id: str
    alias: str
    name: str
    status: str

    product_id: str | None = None

    execution_mode: str | None = None

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    staging_status: str | None = None
    implementation_launched_at: datetime | None = None

    agent_count: int = 0
    message_count: int = 0
    agents: list[AgentSimple] = Field(default_factory=list)

    project_type_id: str | None = None
    project_type: ProjectTypeInfo | None = None
    series_number: int | None = None
    subseries: str | None = None
    taxonomy_alias: str | None = None

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




class OrchestratorJobResponse(BaseModel):
    """Orchestrator job details for project."""

    job_id: str
    agent_id: str
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
    orchestrator: OrchestratorJobResponse | None = None




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
