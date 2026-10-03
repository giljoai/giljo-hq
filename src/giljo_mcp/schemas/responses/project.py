# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pydantic import BaseModel, ConfigDict, Field


class ProjectTypeInfo(BaseModel):
    """Minimal project type info for embedding in project responses."""

    id: str
    abbreviation: str
    label: str
    color: str

    model_config = ConfigDict(from_attributes=True)


class ProjectBase(BaseModel):
    """Shared base for Project response schemas (REST + MCP).

    Declares the fields universal to REST ``ProjectResponse``, MCP
    ``ProjectDetail``, and MCP ``ProjectData``. New ``Project`` model
    columns that should appear in every response shape go here; columns
    specific to one shape stay on the subclass.

    Field-type override is allowed in subclasses (Pydantic v2 supports it)
    and is the mechanism REST uses to keep ``datetime``-normalized
    timestamps while MCP keeps pre-formatted ISO strings.
    """

    id: str
    name: str
    status: str

    description: str | None = None
    mission: str | None = None

    product_id: str | None = None

    execution_mode: str | None = None
    auto_checkin_enabled: bool = False
    auto_checkin_interval: int = 10

    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None

    project_type_id: str | None = None
    series_number: int | None = None
    subseries: str | None = None
    taxonomy_alias: str | None = None

    hidden: bool = False

    successor_project_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectDetail(ProjectBase):
    """Full project detail with agent information.

    Fields match ProjectService.get_project() output. Inherits the universal
    field set from ``ProjectBase``; adds MCP-detail-specific bookkeeping
    (tenant_key, agents, agent_count, message_count) and the staging-handoff
    fields the closeout UI depends on.
    """

    alias: str | None = None
    tenant_key: str

    staging_status: str | None = None
    implementation_launched_at: str | None = None

    reviewed_at: str | None = None
    review_pending: bool = False

    cancellation_reason: str | None = None
    early_termination: bool = False

    agents: list[dict] = Field(default_factory=list)
    agent_count: int = 0
    message_count: int = 0

    project_type: ProjectTypeInfo | None = None


class ProjectListItem(BaseModel):
    """Project item for list operations.

    Fields match ProjectService.list_projects() output per item.

    Intentionally NOT inheriting ``ProjectBase`` — this is a thin list
    projection with required (not Optional) timestamps and no
    ``auto_checkin_*`` fields. Kept standalone on purpose: inheriting
    ``ProjectBase`` would force ``auto_checkin_*`` into
    the list shape (Pydantic v2 cannot drop an inherited field) and relax the
    required ``created_at``/``updated_at`` to optional. Drift against the
    ``crud.py`` list/deleted projection is prevented by the real-router guard
    in ``tests/integration/api/test_list_projects_execution_mode_serialization.py``,
    not by inheritance.
    """

    id: str
    name: str
    mission: str | None = None
    description: str | None = None
    status: str
    staging_status: str | None = None
    implementation_launched_at: str | None = None
    execution_mode: str | None = None
    tenant_key: str
    product_id: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None
    project_type_id: str | None = None
    project_type: ProjectTypeInfo | None = None
    series_number: int | None = None
    subseries: str | None = None
    taxonomy_alias: str | None = None
    hidden: bool = False

    model_config = ConfigDict(from_attributes=True)


class ActiveProjectDetail(ProjectBase):
    """Active project detail.

    Fields match ProjectService.get_active_projects() output (one instance per
    active project). Inherits
    ``ProjectBase`` and adds the active-project bookkeeping (deleted_at,
    counts, nested type info). Overrides ``alias``/``mission`` defaults
    to empty-string to match the existing wire shape.
    """

    alias: str = ""
    mission: str = ""

    implementation_launched_at: str | None = None

    staging_status: str | None = None

    reviewed_at: str | None = None
    review_pending: bool = False

    deleted_at: str | None = None
    agent_count: int = 0
    message_count: int = 0
    project_type: ProjectTypeInfo | None = None


class ProjectMissionUpdateResult(BaseModel):
    """Project mission update result."""

    message: str
    project_id: str
    lifecycle_footer: str | None = Field(
        default=None,
        description=(
            "Breadcrumb: what the dashboard shows now after this call, and your next step. Plain prose, phase-computed."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class ProjectCompleteResult(BaseModel):
    """Project completion result with memory update metadata."""

    message: str
    memory_updated: bool = False
    sequence_number: int = 0
    git_commits_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ProjectCloseOutResult(BaseModel):
    """Project close-out result with decommissioned agent details."""

    message: str
    agents_decommissioned: int = 0
    decommissioned_agent_ids: list[str] = Field(default_factory=list)
    project_status: str = "completed"

    model_config = ConfigDict(from_attributes=True)


class ProjectResumeResult(BaseModel):
    """Project resume (continue_working) result."""

    message: str
    agents_resumed: int = 0
    resumed_agent_ids: list[str] = Field(default_factory=list)
    project_status: str = "inactive"

    model_config = ConfigDict(from_attributes=True)


class ProjectData(ProjectBase):
    """Generic project data for cancel_staging and update_project responses.

    Compact shape — intentionally excludes ``alias``, ``staging_status``,
    ``implementation_launched_at``, agents, and counts. Callers read the
    full detail via ``ProjectDetail`` when they need those fields.
    """

    cancellation_reason: str | None = None
    early_termination: bool = False
    project_type: ProjectTypeInfo | None = None


class ProjectArchiveResult(BaseModel):
    """Result of the archive lifecycle.

    ``project`` is the row as it stands after the terminal transition; the other
    fields report which of the optional lifecycle steps actually did something, so
    a caller can tell the user what happened instead of guessing. Declared after
    ``ProjectData`` because it embeds one.
    """

    project: ProjectData
    deactivated: bool = False
    closed_agents: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ProjectSummaryResult(BaseModel):
    """Project summary with metrics for dashboard display."""

    id: str
    name: str
    status: str
    mission: str | None = None
    total_jobs: int = 0
    completed_jobs: int = 0
    blocked_jobs: int = 0
    active_jobs: int = 0
    pending_jobs: int = 0
    completion_percentage: float = 0.0
    created_at: str | None = None
    activated_at: str | None = None
    last_activity_at: str | None = None
    product_id: str = ""
    product_name: str = ""

    model_config = ConfigDict(from_attributes=True)


class CloseoutData(BaseModel):
    """Project closeout data with agent status counts."""

    project_id: str
    project_name: str
    agent_count: int = 0
    completed_agents: int = 0
    blocked_agents: int = 0
    silent_agents: int = 0
    all_agents_complete: bool = False
    has_blocked_agents: bool = False

    model_config = ConfigDict(from_attributes=True)


class CanCloseResult(BaseModel):
    """Project can-close readiness assessment."""

    can_close: bool = False
    summary: str | None = None
    all_agents_finished: bool = False
    agent_statuses: dict[str, int] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class ProjectLaunchResult(BaseModel):
    """Project launch result with orchestrator details."""

    project_id: str
    orchestrator_job_id: str
    launch_prompt: str
    status: str
    staging_status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectSwitchResult(BaseModel):
    """Project switch/context change result."""

    project_id: str
    name: str
    mission: str | None = None
    tenant_key: str

    model_config = ConfigDict(from_attributes=True)


class NuclearDeleteResult(BaseModel):
    """Nuclear (permanent) project deletion result."""

    message: str
    deleted_counts: dict[str, int] = Field(default_factory=dict)
    project_name: str

    model_config = ConfigDict(from_attributes=True)


class SoftDeleteResult(BaseModel):
    """Soft delete project result."""

    message: str
    deleted_at: str | None = None
    decommissioned_jobs: int = 0

    model_config = ConfigDict(from_attributes=True)


class ProjectPurgeResult(BaseModel):
    """Purge deleted projects result."""

    purged_count: int = 0
    projects: list[dict] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
