# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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


VALID_ROADMAP_ITEM_TYPES: frozenset[str] = frozenset({"project", "task"})
VALID_ROADMAP_RISKS: frozenset[str] = frozenset({"low", "med", "high"})
VALID_ROADMAP_COMPLEXITIES: frozenset[str] = frozenset({"light", "med", "heavy"})

MAX_ROADMAP_SORT_ORDER: int = 100_000

MAX_BLOCKED_REASON_LEN: int = 500


class Roadmap(Base):

    __tablename__ = "roadmaps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    product_id = Column(
        String(36),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    last_generated_at = Column(DateTime(timezone=True), nullable=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items = relationship("RoadmapItem", back_populates="roadmap", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_roadmap_tenant", "tenant_key"),
        Index("idx_roadmaps_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<Roadmap(id={self.id}, product_id={self.product_id})>"


class RoadmapItem(Base):

    __tablename__ = "roadmap_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    roadmap_id = Column(
        String(36),
        ForeignKey("roadmaps.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_type = Column(String(20), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    risk = Column(String(10), nullable=True)
    complexity = Column(String(10), nullable=True)
    blocked = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    blocked_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    roadmap = relationship("Roadmap", back_populates="items")

    __table_args__ = (
        UniqueConstraint(
            "roadmap_id",
            "item_type",
            "project_id",
            "task_id",
            name="uq_roadmap_item",
            postgresql_nulls_not_distinct=True,
        ),
        Index("idx_roadmap_item_tenant", "tenant_key"),
        Index("idx_roadmap_items_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<RoadmapItem(id={self.id}, type={self.item_type}, sort_order={self.sort_order})>"
