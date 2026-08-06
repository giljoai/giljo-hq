# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Task and message-related models for Giljo HQ.

This module contains models for tasks and inter-agent messages.
Tasks track work items across sessions, while messages handle agent communication.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    case,
    literal,
    select,
    text,
)
from sqlalchemy.orm import column_property, relationship
from sqlalchemy.sql import func

from .base import Base, generate_uuid
from .projects import TaxonomyType


class Task(Base):
    """
    Task model - work items tracked across sessions.
    Tasks can be assigned to agents and tracked through completion.

    Phase 4 Enhancement: User assignment support
    - created_by_user_id: User who created the task
    - assigned_to_user_id: User responsible for completing the task
    - Nullable fields for backward compatibility and MCP tool creation

    Handover 0072: Task Integration
    - project_id: Now nullable to support unassigned tasks

    Handover 0433: Task Product Binding (Security Enhancement)
    - product_id: Now required (NOT NULL) for tenant isolation
    - All tasks must be bound to a product
    - Eliminates "unassigned tasks" vulnerability
    """

    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    org_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        # BE-8000c: indexed via explicit Index("idx_task_org_id") below.
        comment="Organization for org-level tasks (Handover 0424)",
    )
    product_id = Column(
        String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )  # Product-level scope for task isolation (Handover 0433: Made required)
    project_id = Column(
        String(36), ForeignKey("projects.id"), nullable=True
    )  # Handover 0072: Nullable for unassigned tasks
    parent_task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)
    # Handover 0076: Removed assigned_agent_id field

    # Phase 4: User ownership (Handover 0076: removed assigned_to_user_id)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Phase 4: Task-to-project conversion tracking
    converted_to_project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # Phase B (agent-parity, 2026-05): replaced free-form category with FK to
    # taxonomy_types so tasks share the project taxonomy. Migrations
    # ce_0015 (add+backfill) and ce_0016 (drop category) handle the schema move.
    task_type_id = Column(
        String(36),
        ForeignKey("taxonomy_types.id", ondelete="SET NULL"),
        nullable=True,
        comment="FK to taxonomy_types for task classification",
    )
    # BE-5058: parity with Project taxonomy fields so tasks can carry the
    # same structured naming (e.g. BE-0001a). Migration ce_0017 creates the
    # columns + index in the CE chain.
    series_number = Column(
        Integer,
        nullable=True,
        comment="Sequential number within a task type (e.g., 1 in BE-0001)",
    )
    subseries = Column(
        String(1),
        nullable=True,
        comment="Single-letter subseries suffix (e.g., 'a' in BE-0001a)",
    )
    status = Column(String(50), default="pending")  # pending, in_progress, completed, blocked, cancelled
    priority = Column(String(20), default="medium")  # low, medium, high, critical
    # FE-5046: per-row UI declutter flag (mirrors Project.hidden). Does NOT
    # affect default visibility -- agents see hidden and non-hidden alike.
    # BE-2002: user-facing name is "Archived" in the dashboard/UI; the backend
    # field, param, and DB column stay `hidden` (do not rename).
    hidden = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Whether task is hidden from default list view (UI declutter only)",
    )
    estimated_effort = Column(Float, nullable=True)  # Hours
    actual_effort = Column(Float, nullable=True)  # Hours
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    # BE-6130b: soft-delete (trash/recover). NULL = live, non-NULL = trashed.
    # All live reads filter ``deleted_at IS NULL``; a trashed task is excluded
    # from the shared project/task serial high-water mark (so its number frees)
    # and gets a FRESH serial on restore (mirrors Project decision C, BE-6049b).
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when task was soft deleted (NULL for live tasks)",
    )

    # Relationships
    product = relationship("Product", back_populates="tasks", foreign_keys=[product_id])
    project = relationship(
        "Project", back_populates="tasks", foreign_keys=[project_id]
    )  # Specify FK to avoid ambiguity with converted_to_project_id
    subtasks = relationship("Task", back_populates="parent_task", foreign_keys="Task.parent_task_id")
    parent_task = relationship("Task", back_populates="subtasks", remote_side="Task.id")
    task_type = relationship("TaxonomyType", foreign_keys=[task_type_id])

    # Phase 4: User relationships (Handover 0076: removed assigned_to_user)
    created_by_user = relationship("User", foreign_keys=[created_by_user_id], back_populates="created_tasks")

    __table_args__ = (
        # BE-8000c: idx_task_tenant dropped — leftmost-covered by
        # idx_task_tenant_created_user (tenant_key, created_by_user_id).
        Index("idx_task_org_id", "org_id"),
        Index("idx_task_product", "product_id"),
        Index("idx_task_project", "project_id"),
        Index("idx_task_status", "status"),
        Index("idx_task_priority", "priority"),
        Index("idx_task_task_type_id", "task_type_id"),
        # Phase 4: User assignment indexes (Handover 0076: removed assignment indexes)
        Index("idx_task_created_by_user", "created_by_user_id"),
        Index("idx_task_tenant_created_user", "tenant_key", "created_by_user_id"),  # Composite for "Created by Me"
        Index("idx_task_converted_to_project", "converted_to_project_id"),  # Conversion tracking
        # BE-5065: shared task+project series counter — partial unique index on
        # typed rows. Mirrors uq_project_taxonomy_active. NULLS NOT DISTINCT
        # collapses any all-NULL slot, but the WHERE clause keeps legacy
        # untyped tasks (series_number IS NULL) exempt.
        Index(
            "uq_task_taxonomy_active",
            "tenant_key",
            "product_id",
            "task_type_id",
            "series_number",
            "subseries",
            unique=True,
            # BE-6130b: also exclude soft-deleted rows so a trashed task's serial
            # can be re-minted on a later create/restore without a unique clash
            # (mirrors uq_project_taxonomy_active's deleted_at predicate).
            postgresql_where=text("series_number IS NOT NULL AND deleted_at IS NULL"),
        ),
        # BE-6130b: partial index over trashed rows for the recover dialog.
        Index("idx_tasks_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
    )

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, title='{self.title}', status='{self.status}')>"


# BE-5058: SELECT-time taxonomy_alias mirror for Task. Tasks have no random
# 6-char fallback alias (unlike Project), so the no-taxonomy case resolves to
# an empty string. Tenant-scoped correlated subquery keeps tenant isolation
# enforced at the model layer.
_task_abbr_subq = (
    select(TaxonomyType.abbreviation)
    .where(
        TaxonomyType.id == Task.task_type_id,
        TaxonomyType.tenant_key == Task.tenant_key,
    )
    .correlate(Task)
    .scalar_subquery()
)

Task.taxonomy_alias = column_property(
    case(
        (
            and_(Task.task_type_id.is_(None), Task.series_number.is_(None)),
            literal(""),
        ),
        (
            Task.series_number.is_(None),
            func.coalesce(_task_abbr_subq, literal("")),
        ),
        else_=(
            func.coalesce(_task_abbr_subq, literal(""))
            + case(
                # BE-6079 (L4): non-EMPTY (not merely non-NULL) abbreviation gates
                # the separator dash, mirroring format_taxonomy_alias so an
                # empty-string abbr renders ``0017`` not ``-0017``.
                (func.nullif(_task_abbr_subq, literal("")).is_not(None), literal("-")),
                else_=literal(""),
            )
            # BE-6049a: pad to a MINIMUM of 4 digits; never truncate (mirrors
            # the Project builder + utils.taxonomy_alias.format_taxonomy_alias).
            + func.lpad(
                func.cast(Task.series_number, String),
                func.greatest(literal(4), func.length(func.cast(Task.series_number, String))),
                literal("0"),
            )
            + func.coalesce(Task.subseries, literal(""))
        ),
    ),
    deferred=False,
)


class Message(Base):
    """
    Message model - inter-agent communication with acknowledgment tracking.
    Supports broadcast, direct, and priority messages.

    Handover 0840b: Normalized — JSONB arrays replaced by junction tables
    (MessageRecipient, MessageAcknowledgment, MessageCompletion) and
    meta_data fields extracted to proper columns.
    """

    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    # BE-6054a: NULLABLE. Project-anchored messages carry project_id; standalone
    # chat-thread messages (thread_id set, project_id NULL) do not. Legacy rows
    # all have project_id — the hazard is FORWARD (NEW null rows reaching readers
    # that assume non-null), audited + hardened in the same project.
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    # BE-6054a: optional anchor to a comm-hub thread (standalone or project-anchored).
    thread_id = Column(String(36), ForeignKey("comm_threads.id", ondelete="CASCADE"), nullable=True)
    message_type = Column(String(50), default="direct")  # direct, broadcast, system
    subject = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)
    priority = Column(String(20), default="normal")  # low, normal, high, critical
    status = Column(String(50), default="pending")  # pending, acknowledged, completed, failed
    result = Column(Text, nullable=True)  # Completion result for completed messages
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # 0840b: Extracted from meta_data JSONB
    from_agent_id = Column(String(64), nullable=True)  # BE-9214: hub agent ids validate to 64
    from_display_name = Column(String(255), nullable=True)
    # BE-9289a: who the author IS ('agent' | 'user'), resolved SERVER-SIDE at post time.
    # from_agent_id is the FUNCTIONAL identity (self-exclusion, baton matching, read
    # cursors) and is self-declared, so its SHAPE says nothing about the author's kind —
    # an agent may legitimately post under a UUID slug. Readers previously guessed from
    # that shape and mislabeled such agents as the human user. CommThreadService.post()
    # already branches on the agent path vs the principal fallback, which is the only
    # place the server actually knows; this column records that answer.
    # NOT NULL with a server default ON PURPOSE: a nullable column would force every
    # reader to keep exactly the fallback heuristic this replaces. 'agent' is the right
    # default because every non-Hub insert path here (project bus, agent job messaging,
    # forwarding) is agent traffic; only post() produces 'user', and it says so.
    from_kind = Column(String(10), nullable=False, server_default="agent")
    auto_generated = Column(Boolean, server_default="false", nullable=False)

    # 0435d: Message intent — controls whether completed agents get auto-blocked
    requires_action = Column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
        comment="True if recipient must take action. False for informational messages.",
    )

    # FE-6140: auto-check-in interval (minutes) carried on a loop_directive message.
    # NULL on every non-directive message. The latest live loop_directive message on
    # a thread defines the thread's current check-in cadence (rolling, latest wins).
    loop_interval_minutes = Column(Integer, nullable=True)

    # Relationships
    project = relationship("Project", back_populates="messages")
    recipients = relationship("MessageRecipient", back_populates="message", cascade="all, delete-orphan")
    acknowledgments = relationship("MessageAcknowledgment", back_populates="message", cascade="all, delete-orphan")
    completions = relationship("MessageCompletion", back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (
        # BE-8000c: idx_message_tenant dropped — leftmost-covered by the two
        # tenant-leading perf composites below (ce_0046 / ce_0051), now declared
        # on the model so autogenerate stops flagging them.
        Index("idx_messages_tenant_created", "tenant_key", text("created_at DESC")),
        Index("idx_messages_tenant_from_agent_created", "tenant_key", "from_agent_id", "created_at"),
        Index("idx_message_project", "project_id"),
        # BE-9061: the hot thread-timeline read filters thread_id and orders by
        # created_at (get_thread_messages). This composite serves that AND fully
        # leftmost-covers the old single-column idx_message_thread (thread_id),
        # which is dropped in the same change (ce_0074) to avoid a redundant index.
        Index("idx_messages_thread_created", "thread_id", "created_at"),  # BE-9061 (was idx_message_thread, BE-6054a)
        Index("idx_message_status", "status"),
        Index("idx_message_priority", "priority"),
        Index("idx_message_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, subject='{self.subject}', status='{self.status}')>"


class MessageRecipient(Base):
    """Junction table: message -> recipient agents (replaces to_agents JSONB array)."""

    __tablename__ = "message_recipients"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(String(64), nullable=False)  # BE-9214: hub agent ids validate to 64
    tenant_key = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="recipients")

    __table_args__ = (
        UniqueConstraint("message_id", "agent_id", name="uq_msg_recipient"),
        Index("idx_message_recipients_agent", "agent_id", "tenant_key"),
        # BE-8000c: idx_message_recipients_message dropped (leftmost-covered by
        # uq_msg_recipient on message_id). idx_message_recipients_tenant is the
        # ce_0051 reaper index (DELETE WHERE tenant_key=?) — now declared here.
        Index("idx_message_recipients_tenant", "tenant_key"),
    )


class MessageAcknowledgment(Base):
    """Junction table: message -> acknowledging agents (replaces acknowledged_by JSONB array)."""

    __tablename__ = "message_acknowledgments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(String(64), nullable=False)  # BE-9214: hub agent ids validate to 64
    tenant_key = Column(String(255), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="acknowledgments")

    __table_args__ = (
        UniqueConstraint("message_id", "agent_id", name="uq_msg_ack"),
        Index("idx_message_acks_agent", "agent_id", "tenant_key"),
        # BE-8000c: idx_message_acks_message dropped (leftmost-covered by
        # uq_msg_ack on message_id). idx_message_acks_tenant is the ce_0051
        # reaper index (DELETE WHERE tenant_key=?) — now declared here.
        Index("idx_message_acks_tenant", "tenant_key"),
    )


class MessageCompletion(Base):
    """Junction table: message -> completing agents (replaces completed_by JSONB array)."""

    __tablename__ = "message_completions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(String(64), nullable=False)  # BE-9214: hub agent ids validate to 64
    tenant_key = Column(String(255), nullable=False)
    completed_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="completions")

    __table_args__ = (
        UniqueConstraint("message_id", "agent_id", name="uq_msg_completion"),
        Index("idx_message_completions_agent", "agent_id", "tenant_key"),
        # BE-8000c: idx_message_completions_message dropped (leftmost-covered by
        # uq_msg_completion on message_id). idx_message_completions_tenant is the
        # ce_0051 reaper index (DELETE WHERE tenant_key=?) — now declared here.
        Index("idx_message_completions_tenant", "tenant_key"),
    )
