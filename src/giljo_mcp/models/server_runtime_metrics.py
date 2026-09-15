# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from .base import Base


class ServerRuntimeMetric(Base):

    __tablename__ = "server_runtime_metrics"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    worker_id = Column(String(128), nullable=False)
    metric = Column(String(64), nullable=False)
    value = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("worker_id", "metric", name="uq_server_runtime_metric_worker_metric"),)

    def __repr__(self) -> str:
        return f"<ServerRuntimeMetric(worker_id={self.worker_id!r}, metric={self.metric!r}, value={self.value})>"
