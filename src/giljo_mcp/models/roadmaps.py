# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Roadmap models for Giljo HQ (FE-6022a).

The Roadmapping Pane gives a product ONE prioritized execution plan built from
its own projects and tasks. The schema is deliberately thin:

- ``Roadmap``      — a 1:1 anchor for a product (``product_id`` UNIQUE). Auto-created
  lazily on the product's first roadmap write. Carries only roadmap-level metadata
  (AI insight ``summary``, ``last_generated_at``).
- ``RoadmapItem``  — a junction row tying a project OR a task into the roadmap with
  an ordering ``sort_order`` plus AI-assessed ``risk`` / ``complexity``. Membership in
  this table IS "on the roadmap"; ordering is ``sort_order``.

Edition Scope: CE. These are CE (tenant_key) tables and live in the standard
models package; the matching migration is ``migrations/versions/ce_0047_roadmaps``.

Design notes:
- Sharing/teams are intentionally absent (no created_by / shares / visibility).
  A roadmap is 1:1 with a product, so "who can move cards" == "who can access the
  product" — sharing attaches at the future product/team ACCESS layer, not here.
- The ``uq_roadmap_item`` UNIQUE carries ``postgresql_nulls_not_distinct=True`` so
  the always-NULL discriminator (one of ``project_id`` / ``task_id`` is NULL for
  every row) does not defeat de-duplication — Postgres treats NULLs as distinct by
  default, which would let the same item be inserted twice and break ON CONFLICT
  upserts. The migration mirrors this flag exactly so create_all (tests) and the
  migration chain (real installs) converge on the identical shape.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base, generate_uuid


# Enum-like membership sets validated at the write boundary (RoadmapService).
VALID_ROADMAP_ITEM_TYPES: frozenset[str] = frozenset({"project", "task"})
VALID_ROADMAP_RISKS: frozenset[str] = frozenset({"low", "med", "high"})
VALID_ROADMAP_COMPLEXITIES: frozenset[str] = frozenset({"light", "med", "heavy"})

# sort_order is a 0-based ordering index within a single roadmap. Capped so a
# malformed agent payload produces a 422 at the boundary rather than an
# unbounded value reaching the column.
MAX_ROADMAP_SORT_ORDER: int = 100_000

# Free-text dependency note ("blocked by the auth gate in BE-6077"), capped at
# the boundary so an oversized agent payload produces a 422, not a DB error.
MAX_BLOCKED_REASON_LEN: int = 500


class Roadmap(Base):
    """Thin 1:1 anchor: one roadmap per product, auto-created on first write."""

    __tablename__ = "roadmaps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    # One roadmap per product. UNIQUE enforces the 1:1; persists when the
    # product is deactivated (deactivation != deletion). CASCADE only on a
    # genuine product hard-delete.
    product_id = Column(
        String(36),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    last_generated_at = Column(DateTime(timezone=True), nullable=True)
    summary = Column(Text, nullable=True)  # AI insight banner copy
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items = relationship("RoadmapItem", back_populates="roadmap", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_roadmap_tenant", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_roadmaps_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<Roadmap(id={self.id}, product_id={self.product_id})>"


class RoadmapItem(Base):
    """Junction row: a project or a task placed on a product's roadmap."""

    __tablename__ = "roadmap_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    roadmap_id = Column(
        String(36),
        ForeignKey("roadmaps.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_type = Column(String(20), nullable=False)  # 'project' | 'task'
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)  # order within roadmap
    risk = Column(String(10), nullable=True)  # 'low' | 'med' | 'high'
    complexity = Column(String(10), nullable=True)  # 'light' | 'med' | 'heavy'
    # Agent-flagged dependency block: the item can't start until something else
    # lands (a gate, often buried in the description). `blocked` drives the red
    # BLOCKED badge; `blocked_reason` is the human-readable "blocked by X" note
    # surfaced in the badge tooltip. Both are roadmap-planning state, NOT the
    # underlying project/task lifecycle status. Added in ce_0048.
    blocked = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    blocked_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    roadmap = relationship("Roadmap", back_populates="items")

    __table_args__ = (
        # NULLS NOT DISTINCT: one of project_id/task_id is always NULL; without
        # this flag Postgres treats those NULLs as distinct and the constraint
        # would never fire (duplicate items + broken ON CONFLICT upsert).
        UniqueConstraint(
            "roadmap_id",
            "item_type",
            "project_id",
            "task_id",
            name="uq_roadmap_item",
            postgresql_nulls_not_distinct=True,
        ),
        # BE-8000c: idx_roadmap_item_roadmap dropped — leftmost-covered by
        # uq_roadmap_item (roadmap_id, item_type, project_id, task_id).
        Index("idx_roadmap_item_tenant", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_roadmap_items_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<RoadmapItem(id={self.id}, type={self.item_type}, sort_order={self.sort_order})>"
