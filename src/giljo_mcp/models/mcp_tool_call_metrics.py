# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, Date, Index, Integer, String, UniqueConstraint

from .base import Base


class McpToolCallMetric(Base):

    __tablename__ = "mcp_tool_call_metrics"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_key = Column(String(36), nullable=False, index=True)
    tool_name = Column(String(128), nullable=False)
    day = Column(Date, nullable=False, default=lambda: datetime.now(UTC).date())
    call_count = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_key", "tool_name", "day", name="uq_mcp_tool_call_metric_tenant_tool_day"),
        Index("idx_mcp_tool_call_metrics_tenant_day", "tenant_key", "day"),
    )

    def __repr__(self) -> str:
        return (
            f"<McpToolCallMetric(tenant_key={self.tenant_key!r}, tool_name={self.tool_name!r}, "
            f"day={self.day}, call_count={self.call_count})>"
        )
