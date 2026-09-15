# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base, generate_uuid


VALID_NOTIFICATION_SEVERITIES = frozenset(
    {
        "info",
        "success",
        "warning",
        "error",
        "critical",
    }
)


VALID_NOTIFICATION_SURFACES = frozenset(
    {
        "bell",
        "banner",
        "both",
    }
)


class Notification(Base):

    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    type = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)

    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)

    payload = Column(JSONB, nullable=False, default=dict)

    dedupe_key = Column(String(255), nullable=False)

    surface = Column(Text, nullable=False, server_default=text("'bell'"))
    role_filter = Column(Text, nullable=True)
    cta_label = Column(Text, nullable=True)
    cta_route = Column(Text, nullable=True)
    dismissible = Column(Boolean, nullable=False, server_default=text("true"))

    read_at = Column(DateTime(timezone=True), nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")

    __table_args__ = (
        CheckConstraint(
            "surface IN ('bell', 'banner', 'both')",
            name="ck_notifications_surface",
        ),
        Index("idx_notifications_dedupe_key", "dedupe_key"),
        Index(
            "uq_notifications_tenant_dedupe_open",
            "tenant_key",
            "dedupe_key",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index(
            "idx_notifications_tenant_user_created",
            "tenant_key",
            "user_id",
            text("created_at DESC"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, type={self.type}, severity={self.severity}, "
            f"user_id={self.user_id}, resolved={self.resolved_at is not None})>"
        )
