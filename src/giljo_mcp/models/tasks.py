# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    org_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        comment="Organization for org-level tasks (Handover 0424)",
    )
    product_id = Column(
        String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    project_id = Column(
        String(36), ForeignKey("projects.id"), nullable=True
    )
    parent_task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)

    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    converted_to_project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    task_type_id = Column(
        String(36),
        ForeignKey("taxonomy_types.id", ondelete="SET NULL"),
        nullable=True,
        comment="FK to taxonomy_types for task classification",
    )
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
    status = Column(String(50), default="pending")
    priority = Column(String(20), default="medium")
    hidden = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Whether task is hidden from default list view (UI declutter only)",
    )
    estimated_effort = Column(Float, nullable=True)
    actual_effort = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when task was soft deleted (NULL for live tasks)",
    )

    product = relationship("Product", back_populates="tasks", foreign_keys=[product_id])
    project = relationship(
        "Project", back_populates="tasks", foreign_keys=[project_id]
    )
    subtasks = relationship("Task", back_populates="parent_task", foreign_keys="Task.parent_task_id")
    parent_task = relationship("Task", back_populates="subtasks", remote_side="Task.id")
    task_type = relationship("TaxonomyType", foreign_keys=[task_type_id])

    created_by_user = relationship("User", foreign_keys=[created_by_user_id], back_populates="created_tasks")

    __table_args__ = (
        Index("idx_task_org_id", "org_id"),
        Index("idx_task_product", "product_id"),
        Index("idx_task_project", "project_id"),
        Index("idx_task_status", "status"),
        Index("idx_task_priority", "priority"),
        Index("idx_task_task_type_id", "task_type_id"),
        Index("idx_task_created_by_user", "created_by_user_id"),
        Index("idx_task_tenant_created_user", "tenant_key", "created_by_user_id"),
        Index("idx_task_converted_to_project", "converted_to_project_id"),
        Index(
            "uq_task_taxonomy_active",
            "tenant_key",
            "product_id",
            "task_type_id",
            "series_number",
            "subseries",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("series_number IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("idx_tasks_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
    )

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, title='{self.title}', status='{self.status}')>"


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
                (func.nullif(_task_abbr_subq, literal("")).is_not(None), literal("-")),
                else_=literal(""),
            )
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

    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    thread_id = Column(String(36), ForeignKey("comm_threads.id", ondelete="CASCADE"), nullable=True)
    message_type = Column(String(50), default="direct")
    subject = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)
    priority = Column(String(20), default="normal")
    status = Column(String(50), default="pending")
    result = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    from_agent_id = Column(String(64), nullable=True)
    from_display_name = Column(String(255), nullable=True)
    from_kind = Column(String(10), nullable=False, server_default="agent")
    auto_generated = Column(Boolean, server_default="false", nullable=False)

    requires_action = Column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
        comment="True if recipient must take action. False for informational messages.",
    )

    loop_interval_minutes = Column(Integer, nullable=True)

    project = relationship("Project", back_populates="messages")
    recipients = relationship("MessageRecipient", back_populates="message", cascade="all, delete-orphan")
    acknowledgments = relationship("MessageAcknowledgment", back_populates="message", cascade="all, delete-orphan")
    completions = relationship("MessageCompletion", back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_messages_tenant_created", "tenant_key", text("created_at DESC")),
        Index("idx_messages_tenant_from_agent_created", "tenant_key", "from_agent_id", "created_at"),
        Index("idx_message_project", "project_id"),
        Index("idx_messages_thread_created", "thread_id", "created_at"),
        Index("idx_message_status", "status"),
        Index("idx_message_priority", "priority"),
        Index("idx_message_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, subject='{self.subject}', status='{self.status}')>"


class MessageRecipient(Base):

    __tablename__ = "message_recipients"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(String(64), nullable=False)
    tenant_key = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="recipients")

    __table_args__ = (
        UniqueConstraint("message_id", "agent_id", name="uq_msg_recipient"),
        Index("idx_message_recipients_agent", "agent_id", "tenant_key"),
        Index("idx_message_recipients_tenant", "tenant_key"),
    )


class MessageAcknowledgment(Base):

    __tablename__ = "message_acknowledgments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(String(64), nullable=False)
    tenant_key = Column(String(255), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="acknowledgments")

    __table_args__ = (
        UniqueConstraint("message_id", "agent_id", name="uq_msg_ack"),
        Index("idx_message_acks_agent", "agent_id", "tenant_key"),
        Index("idx_message_acks_tenant", "tenant_key"),
    )


class MessageCompletion(Base):

    __tablename__ = "message_completions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(String(64), nullable=False)
    tenant_key = Column(String(255), nullable=False)
    completed_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="completions")

    __table_args__ = (
        UniqueConstraint("message_id", "agent_id", name="uq_msg_completion"),
        Index("idx_message_completions_agent", "agent_id", "tenant_key"),
        Index("idx_message_completions_tenant", "tenant_key"),
    )
