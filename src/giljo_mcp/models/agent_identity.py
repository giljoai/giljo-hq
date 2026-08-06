# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Agent Identity Models - AgentJob and AgentExecution.

Handover 0366a: Separates work order (job) from executor (execution).

Design Philosophy:
- AgentJob: Persistent work order (mission, scope, goals) - WHAT
- AgentExecution: Executor instance (who's working, when, status) - WHO

Semantic Clarity:
- job_id = The work to be done (persistent)
- agent_id = The executor doing the work

Data Normalization:
- Mission stored ONCE in AgentJob (no duplication)
- All executions reference the same job via foreign key
- Progress/status tracked per execution (executor-specific)
"""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base, generate_uuid


class AgentJob(Base):
    """
    Persistent work order - survives agent succession.

    Represents the WHAT (mission, scope, objectives).
    Does NOT change when agents hand over to successors.

    Handover 0366a: Extracted from MCPAgentJob to separate concerns.

    Relationships:
    - executions: One job → Many executions (succession history)
    - project: Many jobs → One project

    Multi-tenant Isolation:
    - All queries MUST filter by tenant_key
    - Indexes include tenant_key for performance
    """

    __tablename__ = "agent_jobs"

    job_id = Column(String(36), primary_key=True, default=generate_uuid)
    # BE-8000c: indexed via explicit Index("idx_agent_jobs_tenant_created") below.
    tenant_key = Column(String(50), nullable=False)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=True,
        # BE-8000c: indexed via explicit Index("idx_agent_jobs_project") below.
        comment="Project this job belongs to (Handover 0062)",
    )

    # Job definition (stored ONCE, not duplicated across executions)
    mission = Column(
        Text,
        nullable=True,
        comment="Agent mission/instructions (null while staged; written at Phase-2)",
    )
    job_type = Column(
        String(100),
        nullable=False,
        comment="Job type: orchestrator, analyzer, implementer, tester, etc.",
    )

    # Job lifecycle
    status = Column(
        String(50),
        default="active",
        nullable=False,
        comment="Job status: active, completed, cancelled",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Metadata (job-level configuration)
    job_metadata = Column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Job-level metadata (field priorities, depth config, etc.)",
    )

    # Template reference (optional)
    template_id = Column(
        String(36),
        ForeignKey("agent_templates.id"),
        nullable=True,
        comment="Template used to create this job (if any)",
    )

    # Execution phase for multi-terminal ordering (1=first, same=parallel)
    phase = Column(
        Integer,
        nullable=True,
        default=None,
        comment="Execution phase for multi-terminal ordering (1=first, same=parallel)",
    )

    # Relationships
    project = relationship("Project", back_populates="agent_jobs_v2")
    executions = relationship(
        "AgentExecution",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="AgentExecution.started_at",
    )
    todo_items = relationship(
        "AgentTodoItem",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="AgentTodoItem.sequence",
    )

    __table_args__ = (
        # BE-8000c: idx_agent_jobs_tenant dropped (leftmost-covered by the two
        # tenant-leading composites). idx_agent_jobs_tenant_created is the
        # ce_0046 perf index for paginated "recent jobs for tenant" reads —
        # now declared on the model so autogenerate stops flagging it.
        Index("idx_agent_jobs_project", "project_id"),
        Index("idx_agent_jobs_tenant_project", "tenant_key", "project_id"),
        Index("idx_agent_jobs_tenant_created", "tenant_key", text("created_at DESC")),
        Index("idx_agent_jobs_status", "status"),
        CheckConstraint("status IN ('active', 'completed', 'cancelled')", name="ck_agent_job_status"),
    )

    def __repr__(self) -> str:
        return f"<AgentJob(job_id={self.job_id}, job_type={self.job_type}, status={self.status})>"


# BE-9292b: the execution statuses that mean "this run is over" — the exact set
# every "find the ACTIVE (non-terminal) execution" lookup excludes. Every other
# status, INCLUDING 'silent', is still completable: a stalled agent the health
# monitor marked silent can be driven to 'complete' (and then 'closed') by the
# orchestrator that verified its deliverable.
#
# Named once because close_job's wrong-state error now ADVERTISES that recovery.
# The advertisement is only true while it agrees with the query it describes, and
# the two used to be independent literals — the class of defect this project
# exists to fix is a contract that describes a behavior the code does not have.
#
# BE-9304 made this the ONLY definition. It absorbed two near-identical rivals:
# monitoring/agent_health_monitor's private ``_TERMINAL_EXECUTION_STATUSES``
# (identical value, name differing by one underscore, in the very module that
# SETS 'silent' — so a maintainer editing this line could not see it) and
# repositories/mission_repository's ``TERMINAL_AGENT_STATUSES``, which carried a
# fourth element, "failed". That fourth element was inert: "failed" is not an
# admissible agent_executions.status (see the ck_agent_execution_status CHECK
# constraint below — it was legal under the v3.2 baseline and dropped by v3.3),
# and op.create_check_constraint validates existing rows, so a database at head
# provably holds no 'failed' row. Dropping it therefore changed no result set.
# tests/scripts/test_be9304_terminal_status_single_source.py pins both facts and
# fails if a new literal predicate appears or the schema re-admits 'failed'.
#
# BE-9165: anything NOT listed here — 'waiting', 'working', 'blocked', 'silent',
# 'awaiting_user', 'staged', ... — counts as IN FLIGHT. Unknown statuses land on
# the in-flight side deliberately, so the closeout gates stay conservative.
# Order carries no meaning — membership is the whole semantics.
TERMINAL_EXECUTION_STATUSES: tuple[str, ...] = ("complete", "closed", "decommissioned")


class AgentExecution(Base):
    """
    Executor instance - represents an active agent.

    Represents the WHO (which agent instance is executing).

    Relationships:
    - job: Many executions → One job (work order)
    - spawned_by: Points to parent agent_id (who spawned this executor)

    Multi-tenant Isolation:
    - All queries MUST filter by tenant_key
    """

    __tablename__ = "agent_executions"

    # Primary key: Internal UUID for database integrity (Handover 0429)
    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Agent identity: Same agent_id can have multiple instances (succession)
    # BE-8000c: indexed via explicit Index("idx_agent_executions_agent_id") below.
    agent_id = Column(String(36), nullable=False, default=generate_uuid)
    job_id = Column(
        String(36),
        ForeignKey("agent_jobs.job_id"),
        nullable=False,
        # BE-8000c: indexed via explicit Index("idx_agent_executions_job") below.
        comment="Foreign key to parent AgentJob",
    )
    # BE-8000c: tenant lookups served by idx_agent_executions_tenant_job_started
    # (tenant_key-leading); no column-level index=True.
    tenant_key = Column(String(50), nullable=False)

    # Executor identity
    agent_display_name = Column(
        String(100),
        nullable=False,
        comment="Human-readable display name for UI",
    )

    # Execution lifecycle
    status = Column(
        String(50),
        default="waiting",
        nullable=False,
        comment=(
            "Execution status: waiting, working, blocked, idle, sleeping, complete, closed, "
            "silent, decommissioned, awaiting_user (BE-5029: system-set when user approval pending), "
            "staged (BE-6008: created pre-mission, messageable but play-locked until Phase-2 write)"
        ),
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # BE-5107: anchored once on first transition INTO 'working' by an event
    # listener (see bottom of file). Read by duration_seconds property.
    working_started_at = Column(DateTime(timezone=True), nullable=True)

    # Succession tracking (points to OTHER executions via agent_id)
    spawned_by = Column(
        String(36),
        nullable=True,
        comment="Agent ID of parent executor (clear: agent, not job)",
    )

    # Progress tracking
    progress = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Execution completion progress (0-100%)",
    )
    current_task = Column(Text, nullable=True, comment="Description of current task")
    block_reason = Column(
        Text,
        nullable=True,
        comment="Explanation of why execution is blocked (NULL if not blocked)",
    )

    # Health monitoring
    health_status = Column(
        String(20),
        default="unknown",
        nullable=False,
        comment="Health state: unknown, healthy, warning, critical, timeout",
    )
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    health_failure_count = Column(Integer, default=0, nullable=False)

    # Activity tracking
    last_progress_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last progress update from agent",
    )
    last_message_check_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last message queue check",
    )
    mission_acknowledged_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when agent first fetched mission",
    )
    last_activity_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last authenticated MCP call (heartbeat, 30s debounce)",
    )

    # Tool assignment
    tool_type = Column(
        String(20),
        default="universal",
        nullable=False,
        comment="AI coding agent assigned (claude-code, codex, gemini, universal)",
    )

    # Message counter columns (Handover 0387e - AUTHORITATIVE)
    # Note: JSONB messages column removed in Handover 0700c
    messages_sent_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Count of outbound messages sent by this agent",
    )
    messages_waiting_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Count of inbound messages waiting to be read",
    )
    messages_read_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Count of inbound messages that have been acknowledged/read",
    )

    # Completion result (0497b)
    result = Column(
        JSONB,
        nullable=True,
        comment="Structured completion result from agent (summary, artifacts, commits)",
    )

    # Reactivation tracking (Handover 0827c)
    accumulated_duration_seconds = Column(
        Float,
        default=0.0,
        nullable=False,
        server_default="0.0",
        comment="Total working time across reactivation cycles (seconds)",
    )
    reactivation_count = Column(
        Integer,
        default=0,
        nullable=False,
        server_default="0",
        comment="Number of times this agent has been reactivated after completion",
    )

    # Display name (optional)
    agent_name = Column(
        String(255),
        nullable=True,
        comment="Human-readable display name for UI",
    )

    # Lifecycle phase (CE-0026): which phase of the project this execution
    # belongs to. Set at execution creation, never mutated.
    project_phase = Column(
        String(20),
        nullable=False,
        default="implementation",
        server_default="implementation",
        comment=(
            "Lifecycle phase this orchestrator execution belongs to: "
            "'staging' or 'implementation'. Set at execution creation."
        ),
    )

    # Relationships
    job = relationship("AgentJob", back_populates="executions")

    __table_args__ = (
        # BE-8000c: idx_agent_executions_tenant + idx_agent_executions_tenant_job
        # dropped — both leftmost-covered by the ce_0051 perf composite
        # idx_agent_executions_tenant_job_started (tenant_key, job_id,
        # started_at DESC), now declared on the model. idx_agent_executions_agent_id
        # is the baseline agent_id index (was column index=True → ix_* drift).
        Index("idx_agent_executions_agent_id", "agent_id"),
        Index("idx_agent_executions_job", "job_id"),
        Index("idx_agent_executions_tenant_job_started", "tenant_key", "job_id", text("started_at DESC")),
        Index("idx_agent_executions_status", "status"),
        Index("idx_agent_executions_health", "health_status"),
        Index("idx_agent_executions_last_progress", "last_progress_at"),
        CheckConstraint(
            (
                "status IN ('waiting', 'working', 'blocked', 'complete', 'closed', 'silent', "
                "'decommissioned', 'idle', 'sleeping', 'awaiting_user', 'staged')"
            ),
            name="ck_agent_execution_status",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_agent_execution_progress_range",
        ),
        CheckConstraint(
            "tool_type IN ('claude-code', 'codex', 'gemini', 'antigravity', 'universal')",
            name="ck_agent_execution_tool_type",
        ),
        CheckConstraint(
            "health_status IN ('unknown', 'healthy', 'warning', 'critical', 'timeout')",
            name="ck_agent_execution_health_status",
        ),
        CheckConstraint(
            "project_phase IN ('staging', 'implementation')",
            name="ck_agent_execution_project_phase",
        ),
    )

    @property
    def duration_seconds(self) -> float | None:
        """BE-5107: working time in seconds.

        Returns None until working_started_at is anchored. Ticks against
        now() while the agent is in any non-terminal status; freezes at
        completed_at once status reaches 'complete' or 'closed'.
        """
        if self.working_started_at is None:
            return None
        if self.status in ("complete", "closed") and self.completed_at:
            end = self.completed_at
        else:
            end = datetime.now(UTC)
        return max(0.0, (end - self.working_started_at).total_seconds())

    def __repr__(self) -> str:
        return (
            f"<AgentExecution(agent_id={self.agent_id}, job_id={self.job_id}, "
            f"agent_display_name={self.agent_display_name}, status={self.status})>"
        )


class AgentTodoItem(Base):
    """
    Agent TODO item - tracks individual tasks within an agent job.

    Handover 0402: Replaces JSONB storage with proper relational table.

    Purpose:
    - Store agent TODO items as structured data for UI display
    - Enable real-time updates via WebSocket when items change
    - Support progress tracking with status indicators

    Relationships:
    - job: Many items → One job (work order)

    Multi-tenant Isolation:
    - All queries MUST filter by tenant_key
    - Composite indexes for (job_id, sequence) queries
    """

    __tablename__ = "agent_todo_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(
        String(36),
        ForeignKey("agent_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        # BE-8000c: indexed via idx_todo_items_job_sequence (job_id leftmost).
        comment="Foreign key to parent AgentJob",
    )
    # BE-8000c: tenant lookups served by idx_todo_items_tenant_status
    # (tenant_key-leading); no column-level index=True.
    tenant_key = Column(String(64), nullable=False)

    # TODO item details
    content = Column(
        String(255),
        nullable=False,
        comment="TODO item description/task text",
    )
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        comment="Item status: pending, in_progress, completed, skipped",
    )
    sequence = Column(
        Integer,
        nullable=False,
        comment="Display order (0-based index in agent's TODO list)",
    )
    # BE-9012b (D7): structural self-closeout marker, classified at write time by
    # ``domain.todo_kinds.classify_todo_kind`` and read by the completion gate in
    # place of re-matching keyword regexes at ``complete_job``. NULL = an ordinary
    # work TODO (the common case) that blocks completion until genuinely done.
    todo_kind = Column(
        String(32),
        nullable=True,
        comment="Self-closeout kind (self_closeout|closeout_intent|chain_drive) or NULL for ordinary work",
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    job = relationship("AgentJob", back_populates="todo_items")

    __table_args__ = (
        # BE-8000c: idx_todo_items_job dropped — leftmost-covered by
        # idx_todo_items_job_sequence (job_id, sequence).
        Index("idx_todo_items_tenant_status", "tenant_key", "status"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_agent_todo_items_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_todo_items_job_sequence", "job_id", "sequence"),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'skipped')",
            name="ck_agent_todo_item_status",
        ),
        CheckConstraint(
            "sequence >= 0",
            name="ck_agent_todo_item_sequence_positive",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentTodoItem(id={self.id}, job_id={self.job_id}, "
            f"content={self.content[:30]}..., status={self.status}, sequence={self.sequence})>"
        )


# BE-5107: anchor working_started_at on the FIRST transition INTO 'working'.
# This is the single chokepoint for all 5 status-flip sites
# (mission_service, progress_service, user_approval_service,
# orchestration_agent_state_service, agent_operations_repository) and any
# future ones. Never resets; reactivation keeps the original anchor so the
# duration_seconds property tracks cumulative wall-clock time naturally.
@event.listens_for(AgentExecution.status, "set", propagate=True)
def _anchor_working_started_at(target, value, oldvalue, initiator):
    if value == "working" and target.working_started_at is None:
        target.working_started_at = datetime.now(UTC)
