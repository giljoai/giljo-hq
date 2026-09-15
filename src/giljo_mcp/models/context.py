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
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base


class MCPContextIndex(Base):

    __tablename__ = "mcp_context_index"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_key = Column(String(36), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=True)

    vision_document_id = Column(
        String(36),
        ForeignKey("vision_documents.id", ondelete="CASCADE"),
        nullable=True,
        comment="Link to specific vision document (NULL for legacy product-level chunks)",
    )
    content = Column(Text, nullable=False)
    summary = Column(Text, nullable=True, comment="Optional LLM-generated summary (NULL for Phase 1 non-LLM chunking)")
    keywords = Column(JSONB, default=list, comment="Array of keyword strings extracted via regex or LLM")
    token_count = Column(Integer, nullable=True)
    chunk_order = Column(Integer, nullable=True, comment="Sequential chunk number for maintaining document order")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", backref="context_chunks")
    vision_document = relationship("VisionDocument", back_populates="chunks", foreign_keys=[vision_document_id])

    __table_args__ = (
        Index("idx_mcp_context_tenant_product", "tenant_key", "product_id"),
        Index("idx_mcp_context_vision_doc", "vision_document_id"),
        Index("idx_mcp_context_product_vision_doc", "product_id", "vision_document_id"),
    )

    def __repr__(self) -> str:
        return f"<MCPContextIndex(id={self.id}, product_id={self.product_id})>"
