# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base, generate_uuid


VALID_TARGET_PLATFORMS = frozenset({"windows", "linux", "macos", "android", "ios", "web", "all"})


class Product(Base):

    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    org_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        comment="Organization that owns this product (Handover 0424)",
    )
    name = Column(String(255), nullable=False)

    slug = Column(
        String(64),
        nullable=True,
        comment="Stable URL-safe short name qualifying exported agent filenames (BE-9385b)",
    )
    description = Column(Text, nullable=True)

    project_path = Column(
        String(500), nullable=True, comment="File system path to product folder (required for agent export)"
    )

    quality_standards = Column(Text, nullable=True, comment="Quality standards and testing expectations")

    target_platforms = Column(
        ARRAY(String),
        nullable=False,
        server_default=text("'{all}'::text[]"),
        comment="Target platforms: windows, linux, macos, android, ios, web, or all",
    )


    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when product was soft deleted (NULL for active products)",
    )
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Shown as a tab in the product tab strip (FE-9524/D1). A new product is shown by default.",
    )

    is_default = Column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
        comment="The single per-tenant default product: where an unscoped read resolves. Independent of is_active/shown.",
    )

    core_features = Column(Text, nullable=True, comment="Core product features (was config_data->'features'->>'core')")
    brand_guidelines = Column(Text, nullable=True, comment="Brand & design guidelines for frontend-facing agents")

    product_memory = Column(
        JSONB,
        nullable=False,
        server_default=text('\'{"github": {}, "context": {}}\'::jsonb'),
        comment="Product memory config storage. Contains git_integration settings only.",
    )

    tuning_state = Column(
        JSONB,
        nullable=True,
        default=None,
        comment="Context tuning state: last_tuned_at, last_tuned_at_sequence",
    )

    consolidated_vision_light = Column(
        Text, nullable=True, comment="33% summary of all active vision documents (consolidated)"
    )
    consolidated_vision_light_tokens = Column(
        Integer, nullable=True, comment="Token count of consolidated light summary"
    )
    consolidated_vision_medium = Column(
        Text, nullable=True, comment="66% summary of all active vision documents (consolidated)"
    )
    consolidated_vision_medium_tokens = Column(
        Integer, nullable=True, comment="Token count of consolidated medium summary"
    )
    consolidated_vision_hash = Column(
        String(64), nullable=True, comment="SHA-256 hash of aggregated vision documents (for change detection)"
    )
    consolidated_at = Column(
        DateTime(timezone=True), nullable=True, comment="Timestamp when consolidated summaries were last generated"
    )

    vision_analysis_complete = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="True when all per-doc + product-aggregate summaries are populated. Gates project staging UX (BE-5118).",
    )

    extraction_custom_instructions = Column(
        Text, nullable=True, comment="Custom instructions appended to AI vision document extraction prompt"
    )

    organization = relationship("Organization", back_populates="products")
    projects = relationship("Project", back_populates="product", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="product", cascade="all, delete-orphan")

    vision_documents = relationship(
        "VisionDocument",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="VisionDocument.display_order",
    )

    memory_entries = relationship("ProductMemoryEntry", back_populates="product", cascade="all, delete-orphan")

    agent_assignments = relationship(
        "ProductAgentAssignment", back_populates="product", cascade="all, delete-orphan", passive_deletes=True
    )

    tech_stack = relationship("ProductTechStack", back_populates="product", uselist=False, cascade="all, delete-orphan")
    architecture = relationship(
        "ProductArchitecture", back_populates="product", uselist=False, cascade="all, delete-orphan"
    )
    test_config = relationship(
        "ProductTestConfig", back_populates="product", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_product_tenant", "tenant_key"),
        Index("idx_products_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_product_org_id", "org_id"),
        Index("idx_product_name", "name"),
        Index(
            "idx_product_memory_gin", "product_memory", postgresql_using="gin"
        ),
        Index(
            "idx_products_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")
        ),
        Index("idx_products_consolidated_at", "consolidated_at"),
        Index(
            "idx_product_single_default_per_tenant",
            "tenant_key",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
        CheckConstraint(
            "target_platforms <@ ARRAY['windows', 'linux', 'macos', 'android', 'ios', 'web', 'all']::VARCHAR[]",
            name="ck_product_target_platforms_valid",
        ),
        CheckConstraint(
            "NOT ('all' = ANY(target_platforms) AND array_length(target_platforms, 1) > 1)",
            name="ck_product_target_platforms_all_exclusive",
        ),
        Index(
            "idx_product_slug_unique_per_tenant",
            "tenant_key",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND slug IS NOT NULL"),
        ),
    )

    @property
    def has_config_data(self) -> bool:
        return bool(self.tech_stack or self.architecture or self.test_config or self.core_features)

    def get_memory_field(self, field_path: str, default: Any = None) -> Any:
        if not self.product_memory:
            return default

        keys = field_path.split(".")
        value = self.product_memory

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    @property
    def has_vision_documents(self) -> bool:
        if not hasattr(self, "vision_documents") or not self.vision_documents:
            return False
        return any(doc.is_active for doc in self.vision_documents)

    @property
    def primary_vision_text(self) -> str:
        if not self.vision_documents:
            return ""
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        doc = active_docs[0] if active_docs else (self.vision_documents[0] if self.vision_documents else None)
        if not doc:
            return ""
        return doc.vision_document or ""

    @property
    def primary_vision_path(self) -> str:
        if not self.vision_documents:
            return ""
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        doc = active_docs[0] if active_docs else (self.vision_documents[0] if self.vision_documents else None)
        if not doc:
            return ""
        return doc.vision_path or ""

    @property
    def has_vision(self) -> bool:
        if not self.vision_documents:
            return False
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        docs_to_check = active_docs if active_docs else self.vision_documents
        return any((doc.vision_document or doc.vision_path) for doc in docs_to_check)

    @property
    def vision_is_chunked(self) -> bool:
        if not self.vision_documents:
            return False
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        doc = active_docs[0] if active_docs else (self.vision_documents[0] if self.vision_documents else None)
        if not doc:
            return False
        return doc.chunked

    @property
    def primary_vision_storage_type(self) -> str:
        if not self.vision_documents:
            return "none"
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        doc = active_docs[0] if active_docs else (self.vision_documents[0] if self.vision_documents else None)
        if not doc:
            return "none"
        return doc.storage_type

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name='{self.name}', tenant_key='{self.tenant_key}')>"


class ProductTechStack(Base):

    __tablename__ = "product_tech_stacks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, unique=True)
    tenant_key = Column(String(255), nullable=False)
    programming_languages = Column(Text, nullable=True)
    frontend_frameworks = Column(Text, nullable=True)
    backend_frameworks = Column(Text, nullable=True)
    databases_storage = Column(Text, nullable=True)
    infrastructure = Column(Text, nullable=True)
    dev_tools = Column(Text, nullable=True)
    target_windows = Column(Boolean, server_default=text("false"))
    target_linux = Column(Boolean, server_default=text("false"))
    target_macos = Column(Boolean, server_default=text("false"))
    target_android = Column(Boolean, server_default=text("false"))
    target_ios = Column(Boolean, server_default=text("false"))
    target_cross_platform = Column(Boolean, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="tech_stack")

    __table_args__ = (
        Index("idx_product_tech_stacks_tenant", "tenant_key"),
        Index("idx_product_tech_stacks_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<ProductTechStack(product_id={self.product_id})>"


class ProductArchitecture(Base):

    __tablename__ = "product_architectures"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, unique=True)
    tenant_key = Column(String(255), nullable=False)
    primary_pattern = Column(Text, nullable=True)
    design_patterns = Column(Text, nullable=True)
    api_style = Column(Text, nullable=True)
    architecture_notes = Column(Text, nullable=True)
    coding_conventions = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="architecture")

    __table_args__ = (
        Index("idx_product_architectures_tenant", "tenant_key"),
        Index("idx_product_architectures_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<ProductArchitecture(product_id={self.product_id})>"


class ProductTestConfig(Base):

    __tablename__ = "product_test_configs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, unique=True)
    tenant_key = Column(String(255), nullable=False)
    quality_standards = Column(Text, nullable=True)
    test_strategy = Column(String(50), nullable=True)
    coverage_target = Column(Integer, server_default=text("80"))
    testing_frameworks = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="test_config")

    __table_args__ = (
        Index("idx_product_test_configs_tenant", "tenant_key"),
        Index("idx_product_test_configs_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<ProductTestConfig(product_id={self.product_id})>"


class VisionDocument(Base):

    __tablename__ = "vision_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)

    document_name = Column(
        String(255), nullable=False, comment="User-friendly document name (e.g., 'Product Architecture', 'API Design')"
    )
    document_type = Column(
        String(50),
        nullable=False,
        default="vision",
        comment="Document category: vision, architecture, features, setup, api, testing, deployment, custom",
    )

    vision_path = Column(
        String(500),
        nullable=True,
        comment="DEPRECATED: kept for migration safety, always NULL after BE-5115.",
    )
    vision_document = Column(Text, nullable=True, comment="Inline vision text (required after BE-5115)")
    storage_type = Column(
        String(20), nullable=False, default="inline", comment="Storage mode: 'inline' (only value after BE-5115)"
    )

    chunked = Column(
        Boolean, default=False, nullable=False, comment="Has document been chunked into mcp_context_index for RAG"
    )
    chunk_count = Column(Integer, default=0, nullable=False, comment="Number of chunks created for this document")
    total_tokens = Column(Integer, nullable=True, comment="Estimated total tokens in document")
    file_size = Column(
        BigInteger, nullable=True, comment="Original file size in bytes (NULL for inline content without file)"
    )

    is_summarized = Column(
        Boolean,
        default=False,
        nullable=False,
        comment=(
            "True once the per-document agent summaries (summary_light + summary_medium) "
            "have been populated on this row via update_product_context."
        ),
    )
    original_token_count = Column(Integer, nullable=True, comment="Original document token count before summarization")

    summary_light = Column(Text, nullable=True, comment="Light summary (~33% of original, ~13K tokens for 40K doc)")
    summary_medium = Column(Text, nullable=True, comment="Medium summary (~66% of original, ~26K tokens for 40K doc)")
    summary_light_tokens = Column(Integer, nullable=True, comment="Actual token count in light summary")
    summary_medium_tokens = Column(Integer, nullable=True, comment="Actual token count in medium summary")

    version = Column(String(50), default="1.0.0", nullable=False, comment="Document version using semantic versioning")
    content_hash = Column(String(64), nullable=True, comment="SHA-256 hash of document content for change detection")

    is_active = Column(
        Boolean, default=True, nullable=False, comment="Active documents are used for context; inactive are archived"
    )
    display_order = Column(Integer, default=0, nullable=False, comment="Display order in UI (lower numbers first)")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when vision document was soft deleted (NULL for live docs)",
    )

    meta_data = Column(JSONB, default=dict, comment="Additional metadata: author, tags, source_url, etc.")

    product = relationship("Product", back_populates="vision_documents")
    chunks = relationship(
        "MCPContextIndex",
        back_populates="vision_document",
        cascade="all, delete-orphan",
        foreign_keys="MCPContextIndex.vision_document_id",
    )

    __table_args__ = (
        Index(
            "uq_vision_doc_product_name",
            "product_id",
            "document_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_vision_doc_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
        Index("idx_vision_doc_type", "document_type"),
        Index("idx_vision_doc_active", "is_active"),
        Index("idx_vision_doc_chunked", "chunked"),
        Index("idx_vision_doc_tenant_product", "tenant_key", "product_id"),
        Index("idx_vision_documents_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_vision_doc_product_type", "product_id", "document_type"),
        Index("idx_vision_doc_product_active", "product_id", "is_active", "display_order"),
        CheckConstraint("storage_type = 'inline'", name="ck_vision_doc_storage_type"),
        CheckConstraint(
            "document_type IN ('vision', 'architecture', 'features', 'setup', 'api', 'testing', 'deployment', 'custom')",
            name="ck_vision_doc_document_type",
        ),
        CheckConstraint(
            "storage_type = 'inline' AND vision_document IS NOT NULL AND vision_path IS NULL",
            name="ck_vision_doc_inline_only",
        ),
        CheckConstraint("chunk_count >= 0", name="ck_vision_doc_chunk_count"),
        CheckConstraint(
            "(chunked = false AND chunk_count = 0) OR (chunked = true AND chunk_count > 0)",
            name="ck_vision_doc_chunked_consistency",
        ),
    )

    def __repr__(self) -> str:
        return f"<VisionDocument(id={self.id}, name='{self.document_name}', product_id='{self.product_id}')>"
