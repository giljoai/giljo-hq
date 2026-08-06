# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Product-related models for Giljo HQ.

This module contains models for products, vision documents, and vision chunks.
Products are the top-level organizational unit in the system.
"""

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


# Single source of truth for valid product target platforms.
# Referenced by: DB check constraint, ProductService validation, MCP tool validation,
# extraction prompt, frontend checkboxes, and API schema descriptions.
VALID_TARGET_PLATFORMS = frozenset({"windows", "linux", "macos", "android", "ios", "web", "all"})


class Product(Base):
    """
    Product model - TOP-level organizational unit.
    All projects, tasks, and agents belong to a product.

    Vision Storage (BE-5115: inline-only — file-based storage removed):
    - vision_document: Inline text storage (only supported shape)
    - vision_path: DEPRECATED, always NULL after BE-5115
    - chunked: Has vision been chunked into mcp_context_index

    Handover 0316: Added quality_standards field for testing expectations.
    """

    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # BE-8000c: indexed via explicit Index("idx_product_tenant") below.
    tenant_key = Column(String(36), nullable=False)
    org_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        # BE-8000c: indexed via explicit Index("idx_product_org_id") below.
        comment="Organization that owns this product (Handover 0424)",
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Handover 0084: Project path for agent export (required for copy-command interface)
    project_path = Column(
        String(500), nullable=True, comment="File system path to product folder (required for agent export)"
    )

    # Handover 0316: Quality standards for testing expectations
    quality_standards = Column(Text, nullable=True, comment="Quality standards and testing expectations")

    # Handover 0425: Target platforms for product deployment
    target_platforms = Column(
        ARRAY(String),
        nullable=False,
        server_default=text("'{all}'::text[]"),
        comment="Target platforms: windows, linux, macos, android, ios, web, or all",
    )

    # ✅ Handover 0128e Complete: Deprecated vision fields removed
    # Migration completed - all production code now uses VisionDocument relationship.
    # Use these helper properties instead:
    #    - product.vision_documents (VisionDocument relationship)
    #    - product.primary_vision_text (helper property)
    #    - product.primary_vision_path (helper property)
    #    - product.has_vision (helper property)
    #    - product.vision_is_chunked (helper property)
    #    - product.primary_vision_storage_type (helper property)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when product was soft deleted (NULL for active products)",
    )
    # Product status (Handover 0049)
    is_active = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Active product for token estimation and mission planning (one per tenant)",
    )

    # Core features (extracted from config_data in 0840c)
    core_features = Column(Text, nullable=True, comment="Core product features (was config_data->'features'->>'core')")
    brand_guidelines = Column(Text, nullable=True, comment="Brand & design guidelines for frontend-facing agents")

    # 360 Memory Management storage (Handover 0135, updated 0700c)
    # Note: sequential_history removed in 0700c - use product_memory_entries table
    product_memory = Column(
        JSONB,
        nullable=False,
        server_default=text('\'{"github": {}, "context": {}}\'::jsonb'),
        comment="Product memory config storage. Contains git_integration settings only.",
    )

    # Product Context Tuning state (Handover 0831)
    tuning_state = Column(
        JSONB,
        nullable=True,
        default=None,
        comment="Context tuning state: last_tuned_at, last_tuned_at_sequence",
    )

    # Consolidated vision summaries (Handover 0377)
    # These store pre-computed summaries aggregated from ALL active vision documents
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

    # BE-5117: Gating flag flipped TRUE only when every active vision document
    # and the product aggregate both have light + medium summaries populated.
    # Written by ProductVisionService.evaluate_vision_analysis_complete() at the
    # update_product_context MCP tool write boundary.
    vision_analysis_complete = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="True when all per-doc + product-aggregate summaries are populated. Gates project staging UX (BE-5118).",
    )

    # Handover 0842a: Custom extraction instructions for vision document AI analysis
    extraction_custom_instructions = Column(
        Text, nullable=True, comment="Custom instructions appended to AI vision document extraction prompt"
    )

    # Relationships
    organization = relationship("Organization", back_populates="products")
    projects = relationship("Project", back_populates="product", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="product", cascade="all, delete-orphan")

    # Handover 0043: Multi-Vision Document Support
    vision_documents = relationship(
        "VisionDocument",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="VisionDocument.display_order",
    )

    # Handover 0390a: 360 Memory Entries
    memory_entries = relationship("ProductMemoryEntry", back_populates="product", cascade="all, delete-orphan")

    # Agent assignments (junction table)
    agent_assignments = relationship(
        "ProductAgentAssignment", back_populates="product", cascade="all, delete-orphan", passive_deletes=True
    )

    # Handover 0840c: Normalized config tables (1:1)
    tech_stack = relationship("ProductTechStack", back_populates="product", uselist=False, cascade="all, delete-orphan")
    architecture = relationship(
        "ProductArchitecture", back_populates="product", uselist=False, cascade="all, delete-orphan"
    )
    test_config = relationship(
        "ProductTestConfig", back_populates="product", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_product_tenant", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_products_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_product_org_id", "org_id"),
        Index("idx_product_name", "name"),
        Index(
            "idx_product_memory_gin", "product_memory", postgresql_using="gin"
        ),  # Handover 0135: GIN index for product_memory
        Index(
            "idx_products_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")
        ),  # Soft delete support
        Index("idx_products_consolidated_at", "consolidated_at"),  # Handover 0377: Consolidated vision index
        # Handover 0128e: Removed CheckConstraint for deprecated vision_type field
        # Handover 0425: Validate target_platforms field
        CheckConstraint(
            "target_platforms <@ ARRAY['windows', 'linux', 'macos', 'android', 'ios', 'web', 'all']::VARCHAR[]",
            name="ck_product_target_platforms_valid",
        ),
        CheckConstraint(
            "NOT ('all' = ANY(target_platforms) AND array_length(target_platforms, 1) > 1)",
            name="ck_product_target_platforms_all_exclusive",
        ),
        # Handover 0050: Enforce single active product per tenant (defense in depth)
        Index(
            "idx_product_single_active_per_tenant", "tenant_key", unique=True, postgresql_where=text("is_active = true")
        ),
    )

    @property
    def has_config_data(self) -> bool:
        """Check if product has config data in any of the normalized tables."""
        return bool(self.tech_stack or self.architecture or self.test_config or self.core_features)

    def get_memory_field(self, field_path: str, default: Any = None) -> Any:
        """
        Get memory field using dot notation (e.g., 'github.enabled')

        Args:
            field_path: Dot-separated path (e.g., 'github.enabled' or 'context.summary')
            default: Default value if field not found

        Returns:
            Field value or default

        Examples:
            >>> product.get_memory_field('github.enabled')
            True
            >>> product.get_memory_field('github.repo_url')
            'https://github.com/user/repo'
            >>> product.get_memory_field('context.summary')
            'A product management system'
        """
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

    # Handover 0043: Vision Documents properties
    @property
    def has_vision_documents(self) -> bool:
        """Check if product has any active vision documents"""
        if not hasattr(self, "vision_documents") or not self.vision_documents:
            return False
        return any(doc.is_active for doc in self.vision_documents)

    # Handover 0128e: Migration helper properties (replaces deprecated fields)
    @property
    def primary_vision_text(self) -> str:
        """
        Get primary vision document text.
        Replaces deprecated: product.vision_document field
        """
        if not self.vision_documents:
            return ""
        # Get first active document, or first document if none active
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        doc = active_docs[0] if active_docs else (self.vision_documents[0] if self.vision_documents else None)
        if not doc:
            return ""
        return doc.vision_document or ""

    @property
    def primary_vision_path(self) -> str:
        """
        Get primary vision file path.
        Replaces deprecated: product.vision_path field
        """
        if not self.vision_documents:
            return ""
        # Get first active document, or first document if none active
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        doc = active_docs[0] if active_docs else (self.vision_documents[0] if self.vision_documents else None)
        if not doc:
            return ""
        return doc.vision_path or ""

    @property
    def has_vision(self) -> bool:
        """
        Check if product has vision content.
        Replaces deprecated: bool(product.vision_document) checks
        """
        if not self.vision_documents:
            return False
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        docs_to_check = active_docs if active_docs else self.vision_documents
        return any((doc.vision_document or doc.vision_path) for doc in docs_to_check)

    @property
    def vision_is_chunked(self) -> bool:
        """
        Check if vision is chunked.
        Replaces deprecated: product.chunked field
        """
        if not self.vision_documents:
            return False
        # Get first active document, or first document if none active
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        doc = active_docs[0] if active_docs else (self.vision_documents[0] if self.vision_documents else None)
        if not doc:
            return False
        return doc.chunked

    @property
    def primary_vision_storage_type(self) -> str:
        """
        Get primary vision storage type.
        Replaces deprecated: product.vision_type field
        """
        if not self.vision_documents:
            return "none"
        # Get first active document, or first document if none active
        active_docs = [doc for doc in self.vision_documents if doc.is_active]
        doc = active_docs[0] if active_docs else (self.vision_documents[0] if self.vision_documents else None)
        if not doc:
            return "none"
        return doc.storage_type

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name='{self.name}', tenant_key='{self.tenant_key}')>"


class ProductTechStack(Base):
    """Product tech stack configuration (1:1 with Product). Handover 0840c."""

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
        # BE-8000c: idx_product_tech_stacks_product dropped — the UNIQUE
        # product_tech_stacks_product_id_key (from product_id unique=True) covers it.
        Index("idx_product_tech_stacks_tenant", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_product_tech_stacks_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<ProductTechStack(product_id={self.product_id})>"


class ProductArchitecture(Base):
    """Product architecture configuration (1:1 with Product). Handover 0840c."""

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
        # BE-8000c: idx_product_architectures_product dropped — the UNIQUE
        # product_architectures_product_id_key (from product_id unique=True) covers it.
        Index("idx_product_architectures_tenant", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_product_architectures_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<ProductArchitecture(product_id={self.product_id})>"


class ProductTestConfig(Base):
    """Product test configuration (1:1 with Product). Handover 0840c."""

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
        # BE-8000c: idx_product_test_configs_product dropped — the UNIQUE
        # product_test_configs_product_id_key (from product_id unique=True) covers it.
        Index("idx_product_test_configs_tenant", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_product_test_configs_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<ProductTestConfig(product_id={self.product_id})>"


class VisionDocument(Base):
    """
    Vision Document model - stores multiple vision documents per product.

    Handover 0043: Multi-Vision Document Support - Phase 1
    Enables products to have multiple vision documents (architecture, features, setup, etc.)
    with chunking, versioning, and flexible storage (file-based or inline).

    Storage Types:
    - 'inline': vision_document contains text, vision_path is NULL. After BE-5115
      this is the only supported storage shape. Legacy 'file' / 'hybrid' values
      were migrated to 'inline' by ce_0032_vision_docs_inline_only.

    Document Types:
    - 'vision': Primary vision document
    - 'architecture': Architecture/design documents
    - 'features': Feature specifications
    - 'setup': Setup/installation guides
    - 'api': API documentation
    - 'testing': Test plans and strategies
    - 'deployment': Deployment guides
    - 'custom': User-defined document types

    Multi-tenant isolation: All queries filter by tenant_key.
    CASCADE deletes: Deleting VisionDocument deletes all chunks (via MCPContextIndex).
    """

    __tablename__ = "vision_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # BE-8000c: tenant lookups served by idx_vision_doc_tenant_product
    # (tenant_key-leading); no column-level index=True (dropped ix_* twin).
    tenant_key = Column(String(36), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)

    # Document identification
    document_name = Column(
        String(255), nullable=False, comment="User-friendly document name (e.g., 'Product Architecture', 'API Design')"
    )
    document_type = Column(
        String(50),
        nullable=False,
        default="vision",
        comment="Document category: vision, architecture, features, setup, api, testing, deployment, custom",
    )

    # Storage configuration (inline-only after BE-5115)
    # DEPRECATED: vision_path is kept for migration safety only; always NULL after BE-5115.
    vision_path = Column(
        String(500),
        nullable=True,
        comment="DEPRECATED: kept for migration safety, always NULL after BE-5115.",
    )
    vision_document = Column(Text, nullable=True, comment="Inline vision text (required after BE-5115)")
    storage_type = Column(
        String(20), nullable=False, default="inline", comment="Storage mode: 'inline' (only value after BE-5115)"
    )

    # Chunking state
    chunked = Column(
        Boolean, default=False, nullable=False, comment="Has document been chunked into mcp_context_index for RAG"
    )
    chunk_count = Column(Integer, default=0, nullable=False, comment="Number of chunks created for this document")
    total_tokens = Column(Integer, nullable=True, comment="Estimated total tokens in document")
    file_size = Column(
        BigInteger, nullable=True, comment="Original file size in bytes (NULL for inline content without file)"
    )

    # Summarization metadata (Handover 0345b, enhanced in 0345e, cleaned in 0374)
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

    # Multi-level summaries (Handover 0345e, simplified in 0246b, cleaned in 0374)
    # Handover 0374: 3-tier system (light=33%, medium=66%, full=original)
    summary_light = Column(Text, nullable=True, comment="Light summary (~33% of original, ~13K tokens for 40K doc)")
    summary_medium = Column(Text, nullable=True, comment="Medium summary (~66% of original, ~26K tokens for 40K doc)")
    summary_light_tokens = Column(Integer, nullable=True, comment="Actual token count in light summary")
    summary_medium_tokens = Column(Integer, nullable=True, comment="Actual token count in medium summary")

    # Versioning and integrity
    version = Column(String(50), default="1.0.0", nullable=False, comment="Document version using semantic versioning")
    content_hash = Column(String(64), nullable=True, comment="SHA-256 hash of document content for change detection")

    # Status and display
    is_active = Column(
        Boolean, default=True, nullable=False, comment="Active documents are used for context; inactive are archived"
    )
    display_order = Column(Integer, default=0, nullable=False, comment="Display order in UI (lower numbers first)")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # BE-6130b: soft-delete (trash/recover). NULL = live, non-NULL = trashed.
    # A vision doc and its MCPContextIndex RAG chunks recover as ONE unit: the
    # chunks survive a soft-delete (cascade only fires on a HARD delete), and
    # every chunk-retrieval / doc read excludes those whose parent doc is trashed.
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when vision document was soft deleted (NULL for live docs)",
    )

    # Additional metadata
    meta_data = Column(JSONB, default=dict, comment="Additional metadata: author, tags, source_url, etc.")

    # Relationships
    product = relationship("Product", back_populates="vision_documents")
    chunks = relationship(
        "MCPContextIndex",
        back_populates="vision_document",
        cascade="all, delete-orphan",
        foreign_keys="MCPContextIndex.vision_document_id",
    )

    __table_args__ = (
        # Unique document name per product — BE-6130b made this partial (live rows
        # only) so a name can be reused after its prior doc is trashed.
        Index(
            "uq_vision_doc_product_name",
            "product_id",
            "document_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Partial index over trashed rows for the recover dialog.
        Index("idx_vision_doc_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
        # BE-8000c: idx_vision_doc_tenant dropped (leftmost-covered by
        # idx_vision_doc_tenant_product); idx_vision_doc_product dropped
        # (leftmost-covered by idx_vision_doc_product_type / _product_active).
        # Query optimization indexes
        Index("idx_vision_doc_type", "document_type"),
        Index("idx_vision_doc_active", "is_active"),
        Index("idx_vision_doc_chunked", "chunked"),
        # Composite indexes for common queries
        Index("idx_vision_doc_tenant_product", "tenant_key", "product_id"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_vision_documents_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_vision_doc_product_type", "product_id", "document_type"),
        Index("idx_vision_doc_product_active", "product_id", "is_active", "display_order"),
        # Storage type constraint (BE-5115: inline-only)
        CheckConstraint("storage_type = 'inline'", name="ck_vision_doc_storage_type"),
        # Document type constraint
        CheckConstraint(
            "document_type IN ('vision', 'architecture', 'features', 'setup', 'api', 'testing', 'deployment', 'custom')",
            name="ck_vision_doc_document_type",
        ),
        # Storage consistency constraint (BE-5115: inline-only).
        # Replaces ck_vision_doc_storage_consistency dropped in ce_0032_vision_docs_inline_only.
        CheckConstraint(
            "storage_type = 'inline' AND vision_document IS NOT NULL AND vision_path IS NULL",
            name="ck_vision_doc_inline_only",
        ),
        # Chunk count consistency
        CheckConstraint("chunk_count >= 0", name="ck_vision_doc_chunk_count"),
        CheckConstraint(
            "(chunked = false AND chunk_count = 0) OR (chunked = true AND chunk_count > 0)",
            name="ck_vision_doc_chunked_consistency",
        ),
    )

    def __repr__(self) -> str:
        return f"<VisionDocument(id={self.id}, name='{self.document_name}', product_id='{self.product_id}')>"
