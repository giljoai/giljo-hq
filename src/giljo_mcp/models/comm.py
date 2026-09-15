# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from giljo_mcp.utils.taxonomy_alias import format_taxonomy_alias

from .base import Base, generate_uuid


VALID_THREAD_STATUSES = ("open", "active", "resolved", "closed")
TERMINAL_THREAD_STATUSES = ("resolved", "closed")

CHT_TAXONOMY_ABBR = "CHT"

LOOP_DIRECTIVE_MESSAGE_TYPE = "loop_directive"

VALID_PARTICIPANT_TYPES = ("agent", "user")

VALID_SELF_REPORTED_STATUSES = ("working", "waiting", "blocked", "idle", "sleeping", "complete")

BOUND_THREAD_MARKER_SUBJECT = "(project comms)"


class CommThread(Base):

    __tablename__ = "comm_threads"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    serial = Column(Integer, nullable=False)
    subject = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, server_default="open")
    next_action_owner = Column(String(255), nullable=True)
    severity = Column(String(20), nullable=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    resolution = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    sequence_run_id = Column(String(36), ForeignKey("sequence_runs.id", ondelete="SET NULL"), nullable=True)

    participants = relationship("CommParticipant", back_populates="thread", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_key", "serial", name="uq_comm_thread_serial"),
        Index("idx_comm_thread_owner", "tenant_key", "next_action_owner"),
        Index("idx_comm_thread_status", "tenant_key", "status"),
        Index("idx_comm_threads_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_comm_thread_product", "product_id"),
        Index("idx_comm_thread_project", "project_id"),
        Index(
            "idx_comm_thread_sequence_run",
            "tenant_key",
            "sequence_run_id",
            postgresql_where=text("sequence_run_id IS NOT NULL"),
        ),
    )

    @property
    def taxonomy_alias(self) -> str:
        return format_taxonomy_alias(CHT_TAXONOMY_ABBR, self.serial)

    def __repr__(self) -> str:
        return f"<CommThread(id={self.id}, alias='{self.taxonomy_alias}', status='{self.status}')>"


class CommThreadProjectTag(Base):

    __tablename__ = "comm_thread_project_tags"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    thread_id = Column(String(36), ForeignKey("comm_threads.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("thread_id", "project_id", name="uq_comm_thread_project_tag"),
        Index("idx_comm_thread_project_tag_thread", "thread_id"),
        Index("idx_comm_thread_project_tag_project", "tenant_key", "project_id"),
    )

    def __repr__(self) -> str:
        return f"<CommThreadProjectTag(thread_id={self.thread_id}, project_id={self.project_id})>"


class CommParticipant(Base):

    __tablename__ = "comm_participants"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    thread_id = Column(String(36), ForeignKey("comm_threads.id", ondelete="CASCADE"), nullable=False)
    participant_id = Column(String(255), nullable=False)
    participant_type = Column(String(20), nullable=False)
    display_name = Column(String(255), nullable=True)
    role = Column(String(50), nullable=True)
    harness = Column(String(32), nullable=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_read_message_id = Column(String(36), nullable=True)
    last_read_at = Column(DateTime(timezone=True), nullable=True)
    self_reported_status = Column(String(20), nullable=True)
    self_reported_status_at = Column(DateTime(timezone=True), nullable=True)

    thread = relationship("CommThread", back_populates="participants")

    __table_args__ = (
        UniqueConstraint("thread_id", "participant_id", name="uq_comm_participant"),
        Index("idx_comm_participant_lookup", "tenant_key", "participant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CommParticipant(thread_id={self.thread_id}, "
            f"participant_id={self.participant_id}, type={self.participant_type})>"
        )
