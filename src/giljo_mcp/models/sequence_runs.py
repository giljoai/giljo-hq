# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from giljo_mcp.platform_registry import ACCEPTED_EXECUTION_MODES, VALID_EXECUTION_MODES

from .base import Base, generate_uuid



VALID_RUN_STATUSES: frozenset[str] = frozenset(
    {"pending", "running", "completed", "stalled", "failed", "terminated", "cancelled"}
)

VALID_PROJECT_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "staged",
        "planning",
        "implementing",
        "awaiting_review",
        "completed",
        "failed",
        "stalled",
        "terminated",
    }
)

CHAIN_TERMINAL_PROJECT_STATUSES: frozenset[str] = frozenset({"completed", "terminated", "cancelled", "failed"})

CHAIN_UNSTARTED_PROJECT_STATUSES: frozenset[str] = frozenset({"", "pending", "staged"})

VALID_REVIEW_POLICIES: frozenset[str] = frozenset({"per_card", "auto_close"})

__all__ = ["ACCEPTED_EXECUTION_MODES", "VALID_EXECUTION_MODES"]

MAX_SEQUENCE_PROJECTS: int = 5


class SequenceRun(Base):

    __tablename__ = "sequence_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)

    project_ids = Column(JSONB, nullable=False)

    resolved_order = Column(JSONB, nullable=False)

    current_index = Column(Integer, nullable=False, default=0)

    execution_mode = Column(String(50), nullable=False)

    status = Column(String(30), nullable=False, default="pending")

    review_policy = Column(String(30), nullable=False, default="per_card")

    locked = Column(Boolean, nullable=False, server_default="false", default=False)

    project_statuses = Column(JSONB, nullable=False, default=dict)

    reviewed_project_ids = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)

    reviewed_via = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)

    chain_mission = Column(Text, nullable=True)

    conductor_agent_id = Column(String(64), nullable=True)
    conductor_project_id = Column(String(36), nullable=True)
    conductor_label = Column(String(80), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_sequence_runs_tenant", "tenant_key"),
        Index("idx_sequence_runs_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<SequenceRun(id={self.id}, status={self.status}, index={self.current_index})>"
