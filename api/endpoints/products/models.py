# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Pydantic Models for Product Endpoints - Handover 0126

Request/response models for product operations.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TechStackSchema(BaseModel):
    """Typed schema for product tech stack configuration. Handover 0840i."""

    programming_languages: str | None = None
    frontend_frameworks: str | None = None
    backend_frameworks: str | None = None
    databases_storage: str | None = None
    infrastructure: str | None = None
    dev_tools: str | None = None


class ArchitectureSchema(BaseModel):
    """Typed schema for product architecture configuration. Handover 0840i."""

    primary_pattern: str | None = None
    design_patterns: str | None = None
    api_style: str | None = None
    architecture_notes: str | None = None
    coding_conventions: str | None = None


class TestConfigSchema(BaseModel):
    """Typed schema for product test configuration. Handover 0840i."""

    quality_standards: str | None = None
    test_strategy: str | None = None
    coverage_target: int = 80
    testing_frameworks: str | None = None


class ProductCreate(BaseModel):
    """Request model for creating a product"""

    # FE-9320: a blank name is DELIBERATELY accepted here and must stay that way.
    # The onboarding "existing codebase" door pre-creates a nameless draft so the
    # agent can name it -- update_product_context writes product_name only while the
    # existing name is blank, and skips it once non-empty (locked by
    # tests/test_fe9200_tutorial_prompt_contract.py). A min_length here forces that
    # door's fallback to "My product", which the agent can then never rename. The
    # nameless-product problem is guarded at ACTIVATION instead, in the wizard.
    name: str = Field(..., max_length=255, description="Product name")
    description: str | None = Field(None, description="Product description")
    project_path: str | None = Field(None, description="File system path to product folder (required for agent export)")
    tech_stack: TechStackSchema | None = Field(None, description="Tech stack configuration - Handover 0840i")
    architecture: ArchitectureSchema | None = Field(None, description="Architecture configuration - Handover 0840i")
    test_config: TestConfigSchema | None = Field(None, description="Test configuration - Handover 0840i")
    core_features: str | None = Field(None, description="Core product features - Handover 0840i")
    brand_guidelines: str | None = Field(None, description="Brand & design guidelines for frontend agents")
    product_memory: dict[str, Any] | None = Field(
        None, description="360 Memory storage (git integration, learnings, context) - Handover 0135"
    )
    target_platforms: list[str] | None = Field(
        default=["all"],
        description="Target platforms: windows, linux, macos, android, ios, web, or all - Handover 0425",
    )


class ProductUpdate(BaseModel):
    """Request model for updating a product"""

    name: str | None = Field(None, max_length=255)
    description: str | None = None
    project_path: str | None = None
    tech_stack: TechStackSchema | None = Field(None, description="Tech stack configuration - Handover 0840i")
    architecture: ArchitectureSchema | None = Field(None, description="Architecture configuration - Handover 0840i")
    test_config: TestConfigSchema | None = Field(None, description="Test configuration - Handover 0840i")
    core_features: str | None = Field(None, description="Core product features - Handover 0840i")
    brand_guidelines: str | None = Field(None, description="Brand & design guidelines for frontend agents")
    extraction_custom_instructions: str | None = Field(
        None, description="Custom instructions for vision document extraction"
    )
    product_memory: dict[str, Any] | None = Field(
        None,
        description=(
            "Not updatable via this endpoint — product memory has its own write path "
            "(360 memory tools). Sending this field returns 422. (TSK-9265)"
        ),
    )
    target_platforms: list[str] | None = Field(
        None, description="Target platforms: windows, linux, macos, android, ios, web, or all - Handover 0425"
    )

    @field_validator("product_memory")
    @classmethod
    def _reject_product_memory(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """TSK-9265: the service allowlist silently dropped this field while the
        endpoint returned 200 — reject it honestly at the boundary instead."""
        raise ValueError(
            "product_memory cannot be updated via PUT /api/v1/products/{id}; "
            "product memory is written through the 360 memory tools "
            "(write_memory_entry / project closeout)."
        )


class ProductResponse(BaseModel):
    """Response model for product operations"""

    id: str
    name: str
    # BE-9385b: the stable short name that qualifies exported agent filenames
    # (``<agent>--<slug>.md``). Exposed because it is user-visible -- it is literally
    # in the names of the files they install -- and because it never changes, so the
    # UI can show what an export will be called without guessing. Optional: rows
    # predating ce_0092 have none, and the render path derives one for them.
    slug: str | None = None
    description: str | None
    vision_path: str | None
    created_at: datetime
    updated_at: datetime | None
    project_count: int = 0
    task_count: int = 0
    has_vision: bool = False
    unresolved_tasks: int = 0
    unfinished_projects: int = 0
    vision_documents_count: int = 0
    tech_stack: TechStackSchema | None = Field(None, description="Tech stack configuration - Handover 0840i")
    architecture: ArchitectureSchema | None = Field(None, description="Architecture configuration - Handover 0840i")
    test_config: TestConfigSchema | None = Field(None, description="Test configuration - Handover 0840i")
    core_features: str | None = Field(None, description="Core product features - Handover 0840i")
    brand_guidelines: str | None = Field(None, description="Brand & design guidelines for frontend agents")
    # INF-9321: was write-only (ProductUpdate accepted it, ProductResponse never
    # echoed it), so the wizard's patch map received undefined and VISUALLY
    # cleared a user's typed custom instructions on analysis completion, and the
    # form could never display the persisted value at all.
    extraction_custom_instructions: str | None = Field(
        None, description="Custom instructions for vision document extraction"
    )
    is_active: bool = Field(default=False, description="Shown as a tab in the product tab strip (FE-9524/D1)")
    is_default: bool = Field(
        default=False,
        description="The tenant's single default product: where an unscoped read resolves. Independent of is_active/shown (FE-9524).",
    )
    project_path: str | None = Field(None, description="File system path to product folder (required for agent export)")
    product_memory: dict[str, Any] | None = Field(
        default_factory=lambda: {"git_integration": {}, "sequential_history": [], "context": {}},
        description="360 Memory storage (git integration, sequential_history, context) - Handover 0412",
    )
    target_platforms: list[str] | None = Field(
        default=["all"],
        description="Target platforms: windows, linux, macos, android, ios, web, or all - Handover 0425",
    )
    # BE-5117/BE-5118: AI-owned vision analysis surface. The flag gates project
    # staging UX in the frontend; the consolidated_* fields back the existing
    # "Consolidated Vision Summaries" panel in ProductDetailsDialog.vue.
    vision_analysis_complete: bool = Field(
        default=False,
        description="True when every active vision doc + the product aggregate have light + medium summaries. Gates ProductForm Next + tab nav (BE-5118).",
    )
    consolidated_vision_light: str | None = Field(
        None, description="Aggregate 33% summary across all active vision documents (BE-5117)."
    )
    consolidated_vision_medium: str | None = Field(
        None, description="Aggregate 66% summary across all active vision documents (BE-5117)."
    )
    consolidated_vision_light_tokens: int | None = Field(None, description="Token count of aggregate light summary.")
    consolidated_vision_medium_tokens: int | None = Field(None, description="Token count of aggregate medium summary.")
    consolidated_vision_hash: str | None = Field(
        None, description="SHA-256 of aggregated vision text used to detect drift."
    )
    consolidated_at: datetime | None = Field(
        None, description="Timestamp the consolidated summaries were last regenerated."
    )
    # BE-5122: derived (NOT a DB column). SHA-256 of the *current* vision
    # document inputs, prefixed ``sha256:``. Compare against
    # ``consolidated_vision_hash`` (raw hex) to detect drift. Empty input set
    # returns the sentinel ``sha256:empty``.
    vision_inputs_hash: str = Field(
        default="sha256:empty",
        description="Derived SHA-256 fingerprint of current vision inputs (BE-5122). Compare to consolidated_vision_hash for drift detection.",
    )


class VisionSummarySchema(BaseModel):
    """BE-6066 P4: per-product vision-document aggregates for the products LIST.

    Mirrors the four values ``ProductCard.vue`` used to compute client-side from
    the full ``vision_documents`` array (now no longer shipped on the list):

    - ``doc_count``     -> ``vision_documents.length``
    - ``chunked_count`` -> count of docs where ``chunked`` is true
    - ``chunk_total``   -> sum of ``chunk_count`` across docs
    - ``embedded_count``-> count of docs where both ``summary_light`` and
      ``summary_medium`` are populated (the card's ``getAnalyzedDocCount``).
    """

    doc_count: int = 0
    chunked_count: int = 0
    chunk_total: int = 0
    embedded_count: int = 0


class ProductListResponse(BaseModel):
    """BE-6066 P4: lean response model for the products LIST endpoint.

    The list cards only need identity/flags/timestamps, the P1 count fields, and
    vision AGGREGATES — NOT the full detail graph (tech_stack / architecture /
    test_config / vision_documents). Those load on demand when the user opens
    Edit/Details (``GET /products/{id}`` still returns the full ``ProductResponse``).
    Deliberately omits the 4 heavy relations to drop the list's eager-load +
    over-fetch.
    """

    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime | None
    is_active: bool = Field(default=False, description="Shown as a tab in the product tab strip (FE-9524/D1)")
    is_default: bool = Field(
        default=False,
        description="The tenant's single default product: where an unscoped read resolves. Independent of is_active/shown (FE-9524).",
    )
    project_path: str | None = Field(None, description="File system path to product folder")
    target_platforms: list[str] | None = Field(default=["all"], description="Target platforms - Handover 0425")
    # P1 batched count fields (same semantics as ProductResponse).
    project_count: int = 0
    task_count: int = 0
    has_vision: bool = False
    unresolved_tasks: int = 0
    unfinished_projects: int = 0
    vision_documents_count: int = 0
    # BE-5118 analysis flag backs the card's analysis pill (kept; product column).
    vision_analysis_complete: bool = Field(
        default=False, description="True when vision analysis is complete (BE-5118 card pill)."
    )
    # BE-6066 P4: vision aggregates that replace the card's vision_documents computeds.
    vision_summary: VisionSummarySchema = Field(default_factory=VisionSummarySchema)


class ActiveProductInfo(BaseModel):
    """Minimal active product info for efficient responses"""

    id: str
    name: str
    description: str | None
    activated_at: datetime = Field(description="When this product was activated")
    active_projects_count: int = Field(default=0, description="Number of active projects")


class ProductActivationResponse(BaseModel):
    """Response for product activation matching frontend expectations (Handover 0503)"""

    product_id: str = Field(..., description="ID of the activated product")
    previous_active_product_id: str | None = Field(
        None, description="ID of previously active product (if any) that was deactivated"
    )
    product: ProductResponse = Field(..., description="Full activated product details")
    message: str = Field(..., description="Success message")
    deactivated_projects: list[str] = Field(default_factory=list, description="IDs of projects that were auto-paused")


class ProductPurgeResponse(BaseModel):
    """Response for permanent product deletion (purge)"""

    success: bool = True
    product_name: str
    message: str


class ProductDeleteResponse(BaseModel):
    """Enhanced response for product deletion"""

    message: str
    deleted_product_id: str
    was_active: bool = Field(description="Whether the deleted product was active")
    remaining_products_count: int
    new_active_product: ActiveProductInfo | None = Field(
        None, description="Auto-activated product (if deleted product was active)"
    )


class ActiveProductRefreshResponse(BaseModel):
    """Response for /refresh-active endpoint"""

    has_active_product: bool = Field(default=False, description="Whether there is an active product")
    product: ProductResponse | None = Field(None, description="Full product details if active")
    total_products_count: int | None = None
    last_refreshed_at: datetime | None = None


class DeletedProductResponse(BaseModel):
    """Response model for deleted products list"""

    id: str
    name: str
    description: str | None
    deleted_at: datetime
    days_until_purge: int = Field(ge=0, description="Days remaining before permanent deletion")
    purge_date: datetime = Field(description="Date when product will be permanently deleted")
    project_count: int = Field(ge=0, description="Total projects under this product")
    vision_documents_count: int = Field(ge=0, description="Total vision documents")


class VisionChunk(BaseModel):
    """Response model for vision document chunks"""

    chunk_number: int
    total_chunks: int
    content: str
    char_start: int
    char_end: int
    boundary_type: str
    keywords: list[str]
    headers: list[str]


class VisionDocumentStatsResponse(BaseModel):
    """Aggregated vision document statistics for active product.

    Stats are summed across all active vision documents for the product,
    since products support multiple uploaded documents (Handover 0043).
    """

    product_id: str = Field(..., description="Active product ID")
    product_name: str = Field(..., description="Active product name")
    has_vision_document: bool = Field(..., description="Whether active product has any active vision documents")
    total_tokens: int = Field(default=0, description="Total tokens across all active vision documents")
    chunk_count: int = Field(default=0, description="Total chunks across all active vision documents")
    is_summarized: bool = Field(default=False, description="Whether any vision document has been summarized")
    summary_tokens: int = Field(default=0, description="Total summary tokens across all summarized documents")


class ContextUpdateProjectResponse(BaseModel):
    """BE-5122: idempotency lookup for an open CTX project on a product.

    Returned by ``GET /api/v1/products/{product_id}/context_update_project``.
    Lets the frontend skip spawning a duplicate CTX project when one is already
    active or inactive (not yet completed/cancelled).
    """

    product_id: str = Field(..., description="Product UUID this CTX project belongs to.")
    project_id: str = Field(..., description="Existing CTX project UUID.")
    taxonomy_alias: str | None = Field(None, description="e.g. CTX-0001.")
    status: str = Field(..., description="Project lifecycle status (inactive/active/etc).")
    created_at: datetime = Field(..., description="When the CTX project was created.")
    vision_inputs_hash: str = Field(
        ..., description="Derived hash of the product's current vision inputs at lookup time."
    )
    consolidated_vision_hash: str | None = Field(
        None, description="Persisted hash of inputs at the last consolidation run."
    )
    hash_matches: bool = Field(
        ..., description="True iff vision_inputs_hash == consolidated_vision_hash (frontend may self-close)."
    )


class CascadeImpact(BaseModel):
    """Cascade impact response for product deletion"""

    product_id: str
    product_name: str = Field(..., description="Product name")
    total_projects: int = Field(..., description="Total number of projects")
    total_tasks: int = Field(..., description="Total number of tasks")
    total_vision_documents: int = Field(..., description="Number of vision documents")
    warning: str = Field(..., description="Warning message about deletion impact")


# ============================================================================
# 360 Memory Entries (Handover 0490)
# ============================================================================


class MemoryEntryResponse(BaseModel):
    """Response model for a single 360 memory entry"""

    id: str = Field(..., description="Entry UUID")
    sequence: int = Field(..., description="Sequence number within product")
    entry_type: str = Field(..., description="Entry type (project_closeout, session_handover, etc.)")
    source: str = Field(..., description="Source tool identifier")
    timestamp: str = Field(..., description="ISO timestamp of entry creation")
    project_id: str | None = Field(None, description="Source project UUID (if applicable)")
    project_name: str | None = Field(None, description="Project name at time of entry")
    summary: str | None = Field(None, description="2-3 paragraph summary")
    key_outcomes: list[str] = Field(default_factory=list, description="Key achievements")
    decisions_made: list[str] = Field(default_factory=list, description="Architectural/design decisions")
    git_commits: list[dict[str, Any]] = Field(default_factory=list, description="Git commit objects")
    deliverables: list[Any] = Field(default_factory=list, description="Deliverables/artifacts")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Metrics dictionary")
    priority: int = Field(default=3, description="Priority level 1-5")
    significance_score: float = Field(default=0.5, description="Significance score 0.0-1.0")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    author_job_id: str | None = Field(None, description="Job ID of authoring agent")
    author_name: str | None = Field(None, description="Name of authoring agent")
    author_type: str | None = Field(None, description="Type of authoring agent")
    deleted_by_user: bool = Field(default=False, description="Whether entry was soft-deleted")


class MemoryEntriesResponse(BaseModel):
    """Response model for memory entries list endpoint"""

    success: bool = Field(default=True, description="Operation success status")
    entries: list[MemoryEntryResponse] = Field(default_factory=list, description="Memory entries array")
    total_count: int = Field(..., description="Total entries for product (including deleted)")
    filtered_count: int = Field(..., description="Count of entries returned (after filters)")
