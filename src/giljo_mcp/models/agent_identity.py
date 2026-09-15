# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

    __tablename__ = "agent_jobs"

    job_id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(50), nullable=False)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=True,
        comment="Project this job belongs to (Handover 0062)",
    )

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

    status = Column(
        String(50),
        default="active",
        nullable=False,
        comment="Job status: active, completed, cancelled",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    job_metadata = Column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Job-level metadata (field priorities, depth config, etc.)",
    )

    template_id = Column(
        String(36),
        ForeignKey("agent_templates.id"),
        nullable=True,
        comment="Template used to create this job (if any)",
    )

    phase = Column(
        Integer,
        nullable=True,
        default=None,
        comment="Execution phase for multi-terminal ordering (1=first, same=parallel)",
    )

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
        Index("idx_agent_jobs_project", "project_id"),
        Index("idx_agent_jobs_tenant_project", "tenant_key", "project_id"),
        Index("idx_agent_jobs_tenant_created", "tenant_key", text("created_at DESC")),
        Index("idx_agent_jobs_status", "status"),
        CheckConstraint("status IN ('active', 'completed', 'cancelled')", name="ck_agent_job_status"),
    )

    def __repr__(self) -> str:
        return f"<AgentJob(job_id={self.job_id}, job_type={self.job_type}, status={self.status})>"


TERMINAL_EXECUTION_STATUSES: tuple[str, ...] = ("complete", "closed", "decommissioned")


class AgentExecution(Base):

    __tablename__ = "agent_executions"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    agent_id = Column(String(36), nullable=False, default=generate_uuid)
    job_id = Column(
        String(36),
        ForeignKey("agent_jobs.job_id"),
        nullable=False,
        comment="Foreign key to parent AgentJob",
    )
    tenant_key = Column(String(50), nullable=False)

    agent_display_name = Column(
        String(100),
        nullable=False,
        comment="Human-readable display name for UI",
    )

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
    working_started_at = Column(DateTime(timezone=True), nullable=True)

    spawned_by = Column(
        String(36),
        nullable=True,
        comment="Agent ID of parent executor (clear: agent, not job)",
    )

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

    health_status = Column(
        String(20),
        default="unknown",
        nullable=False,
        comment="Health state: unknown, healthy, warning, critical, timeout",
    )
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    health_failure_count = Column(Integer, default=0, nullable=False)

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

    tool_type = Column(
        String(20),
        default="universal",
        nullable=False,
        comment="AI coding agent assigned (claude-code, codex, universal)",
    )

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

    result = Column(
        JSONB,
        nullable=True,
        comment="Structured completion result from agent (summary, artifacts, commits)",
    )

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

    agent_name = Column(
        String(255),
        nullable=True,
        comment="Human-readable display name for UI",
    )

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

    job = relationship("AgentJob", back_populates="executions")

    __table_args__ = (
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

    __tablename__ = "agent_todo_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(
        String(36),
        ForeignKey("agent_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        comment="Foreign key to parent AgentJob",
    )
    tenant_key = Column(String(64), nullable=False)

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
    todo_kind = Column(
        String(32),
        nullable=True,
        comment="Self-closeout kind (self_closeout|closeout_intent|chain_drive) or NULL for ordinary work",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    job = relationship("AgentJob", back_populates="todo_items")

    __table_args__ = (
        Index("idx_todo_items_tenant_status", "tenant_key", "status"),
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


@event.listens_for(AgentExecution.status, "set", propagate=True)
def _anchor_working_started_at(target, value, oldvalue, initiator):
    if value == "working" and target.working_started_at is None:
        target.working_started_at = datetime.now(UTC)
