# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field

from api.endpoints.mcp_tools._base import (
    MCP_DESCRIPTION_MAX,
    MCP_ID_MAX,
    MCP_LIST_ITEMS_MAX,
    MCP_NAME_MAX,
    MCP_SHORT_TEXT_MAX,
    READ_PRODUCT_ID_DESC,
    _call_tool,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.services.product_memory_service import (
    SEARCH_MEMORY_LIMIT_DEFAULT,
    SEARCH_MEMORY_LIMIT_MAX,
)


_PRODUCT_LABEL = Field(max_length=MCP_NAME_MAX)
_PRODUCT_PROSE = Field(max_length=MCP_DESCRIPTION_MAX)


class _TechStackContext(BaseModel):
    """Grouped tech-stack fields. Unpacked to flat ProductService kwargs."""

    model_config = {"extra": "forbid"}

    programming_languages: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    frontend_frameworks: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    backend_frameworks: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    databases: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    infrastructure: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    dev_tools: str = Field(
        "",
        max_length=MCP_DESCRIPTION_MAX,
        description="Developer tooling: editors, linters, formatters, build/test runners, local services.",
    )
    target_platforms: list[str] | None = Field(
        None, description="Subset of: windows, linux, macos, android, ios, web, all."
    )


class _ArchitectureContext(BaseModel):
    """Grouped architecture/design fields. Unpacked to flat kwargs."""

    model_config = {"extra": "forbid"}

    architecture_pattern: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    design_patterns: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    api_style: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    architecture_notes: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    coding_conventions: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    brand_guidelines: str = Field("", max_length=MCP_DESCRIPTION_MAX)


class _QualityContext(BaseModel):
    """Grouped quality field(s). Unpacked to flat kwargs."""

    model_config = {"extra": "forbid"}

    quality_standards: str = Field("", max_length=MCP_DESCRIPTION_MAX)


class _TestingContext(BaseModel):
    """Grouped testing fields. Unpacked to flat kwargs."""

    model_config = {"extra": "forbid"}

    testing_strategy: str = Field(
        "",
        max_length=MCP_DESCRIPTION_MAX,
        description="One of: TDD, BDD, Integration-First, E2E-First, Manual, Hybrid.",
    )
    testing_frameworks: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    test_coverage_target: int | None = Field(None, description="Integer 0-100.")


def _merge_group(kwargs: dict[str, Any], group: BaseModel | None) -> None:
    if group is None:
        return
    for field_name, value in group.model_dump().items():
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        kwargs[field_name] = value


@mcp.tool(
    title="Get Context",
    description=(
        "Fetch product/project context by category in one call (pass a list). categories=['project'] "
        "returns one project's description and mission and names it two ways: project_alias is the short "
        "permanent share code (e.g. A1B2C3), taxonomy_alias the human-readable serial (e.g. BE-0007). "
        "Token costs per category: see categories. Never pass tenant_key."
    ),
    annotations=_tool_hints("get_context"),
)
async def get_context(
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=(
                "Product UUID. Optional when project_id is given (the product is resolved from it) and for "
                "tenant-scoped categories (products, threads, project, chain, self_identity, todos); omit it to "
                "resolve a product with categories=['products']."
            ),
        ),
    ] = "",
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Project id.")] = "",
    agent_name: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description="Agent template name (e.g. 'implementer-backend') for self_identity category. Optional.",
        ),
    ] = "",
    job_id: Annotated[
        str,
        Field(max_length=MCP_ID_MAX, description=("Agent job UUID; needed only for the todos category.")),
    ] = "",
    categories: Annotated[
        list[Annotated[str, Field(max_length=MCP_ID_MAX)]] | None,
        Field(
            max_length=MCP_LIST_ITEMS_MAX,
            description=(
                "Categories to fetch (a list, required). Light: product_core (~100 tokens), tech_stack (200-400),"
                " architecture (300-1.5K), testing (0-400), project (~300), products (~25 per product: id, name, "
                "is_active; resolves a name to an id, works with no product set, names may repeat), tasks (open "
                "tasks), todos (a job's TODO list; pass job_id), chain (the caller's active chain run; needs "
                "project_id, error no_active_chain_run outside one), threads (25 most recent Hub threads), "
                "self_identity (agent template content). Heavy: vision_documents (0-24K), memory_360 (500-5K; "
                "latest 3 closeouts by sequence DESC, tune with depth_config={'memory_360': N} or {'memory_360': {'last_n_projects':"
                " N, 'shape': 'full'|'headlines'}}), git_history (500-5K), agent_templates (400-2.4K)."
            ),
        ),
    ] = None,
    depth_config: Annotated[
        dict | None,
        Field(
            description=(
                "Per-category depth overrides keyed by category name, e.g. {'vision_documents': 'full', "
                "'git_history': 'summary'}. An unknown key is rejected with the accepted list. Omit to use the "
                "saved depth settings."
            )
        ),
    ] = None,
    output_format: Annotated[
        Literal["structured", "flat"], Field(description="Output format: 'structured' (default) or 'flat'.")
    ] = "structured",
    ctx: Context = None,
) -> dict[str, Any]:
    if isinstance(categories, str):
        categories = [categories]
    kwargs: dict[str, Any] = {"product_id": product_id, "output_format": output_format}
    if project_id:
        kwargs["project_id"] = project_id
    if agent_name:
        kwargs["agent_name"] = agent_name
    if job_id:
        kwargs["job_id"] = job_id
    if categories is not None:
        kwargs["categories"] = categories
    if depth_config is not None:
        kwargs["depth_config"] = depth_config
    return await _call_tool(ctx, "get_context", kwargs)


@mcp.tool(
    title="Search Memory",
    description=(
        "Search the 360 memory (closeouts/handovers) by keyword to answer 'have we solved X "
        "before?'. Matches summary, key_outcomes, decisions_made, project_name, tags, and "
        "git_commits (a closeout's commit messages -- e.g. 'when did we fix the redirect bug'); "
        "optional tag narrows to one controlled-vocabulary value. Tenant-scoped (never pass "
        "tenant_key); defaults to your default product, pass product_id to search a specific "
        "product instead. Returns relevance-ranked headlines, capped at limit. Distinct "
        "from get_context(memory_360) (recency, not search) and list_threads(query=...) (Hub chat, "
        "not memory)."
    ),
    annotations=_tool_hints("search_memory"),
)
async def search_memory(
    query: Annotated[
        str,
        Field(
            max_length=MCP_SHORT_TEXT_MAX,
            description="Case-insensitive keyword/substring to search the 360 memory for.",
        ),
    ],
    tag: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description="Optional exact tag to filter by (controlled vocabulary, e.g. 'bug-fix', 'backend'). Empty = no tag filter.",
        ),
    ] = "",
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=SEARCH_MEMORY_LIMIT_MAX,
            description=f"Max headlines to return (default {SEARCH_MEMORY_LIMIT_DEFAULT}, max {SEARCH_MEMORY_LIMIT_MAX}).",
        ),
    ] = SEARCH_MEMORY_LIMIT_DEFAULT,
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=READ_PRODUCT_ID_DESC.format(what="search"),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"query": query, "limit": limit}
    if tag:
        kwargs["tag"] = tag
    if product_id:
        kwargs["product_id"] = product_id
    return await _call_tool(ctx, "search_memory", kwargs)


@mcp.tool(
    name="create_product",
    title="Create Product",
    description=(
        "Create a new product for the user (agent-side bootstrap — the MCP twin of the "
        "dashboard's product-create form). Establishes the product row only, INACTIVE; "
        "populate details afterwards via update_product_context and create_vision_document."
    ),
    annotations=_tool_hints("create_product"),
)
async def create_product(
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MCP_NAME_MAX,
            description="Product name (required). Create fails if a product with this name already exists.",
        ),
    ],
    description: Annotated[
        str, Field(max_length=MCP_DESCRIPTION_MAX, description="What the product is and who it is for, in plain prose.")
    ] = "",
    project_path: Annotated[
        str,
        Field(
            max_length=MCP_DESCRIPTION_MAX,
            description=(
                "Absolute path of the user's local codebase folder you are operating from; OMIT "
                "if you have no filesystem access inside the user's repository — never guess."
            ),
        ),
    ] = "",
    core_features: Annotated[
        str,
        Field(max_length=MCP_DESCRIPTION_MAX, description="What the product does: its main features, in plain prose."),
    ] = "",
    brand_guidelines: Annotated[
        str, Field(max_length=MCP_DESCRIPTION_MAX, description="Brand voice, naming and visual rules for the product.")
    ] = "",
    target_platforms: Annotated[
        list[str] | None,
        Field(description="Subset of: windows, linux, macos, android, ios, web, all."),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"name": name}
    kwargs.update(
        {
            key: value
            for key, value in (
                ("description", description),
                ("project_path", project_path),
                ("core_features", core_features),
                ("brand_guidelines", brand_guidelines),
            )
            if value
        }
    )
    if target_platforms is not None:
        kwargs["target_platforms"] = target_platforms
    return await _call_tool(ctx, "create_product", kwargs)


@mcp.tool(
    name="create_vision_document",
    title="Create Vision Document",
    description=(
        "Write an agent-authored markdown vision document onto an EXISTING product — the MCP "
        "twin of the dashboard's vision-document upload; it appears in the UI exactly like an "
        "uploaded file and feeds the same ingest and staleness machinery."
    ),
    annotations=_tool_hints("create_vision_document"),
)
async def create_vision_document(
    product_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Product id.")],
    content: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Full markdown vision document text (same size cap as the UI upload). After "
                "creating, call get_vision_document then update_product_context (vision_summaries + "
                "consolidated_vision) to populate the product card."
            ),
        ),
    ],
    document_name: Annotated[
        str,
        Field(
            max_length=MCP_NAME_MAX,
            description="Optional filename shown in the UI (e.g. 'Product Vision.md'). Defaults to 'Agent Vision.md'.",
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"product_id": product_id, "content": content}
    if document_name:
        kwargs["document_name"] = document_name
    return await _call_tool(ctx, "create_vision_document", kwargs)


@mcp.tool(
    name="get_vision_document",
    title="Get Vision Document",
    description=(
        "Retrieve a product's vision document with extraction instructions. "
        "Call WITHOUT chunk to get metadata (total_chunks, extraction_instructions). "
        "Then fetch chunk=1 through chunk=total_chunks -- these reads are independent "
        "and side-effect free, so request them in PARALLEL, in any order. Read ALL "
        "chunks before calling update_product_context."
    ),
    annotations=_tool_hints("get_vision_document"),
)
async def get_vision_document(
    product_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Product id.")],
    chunk: Annotated[
        int | None,
        Field(description="Which chunk of a long vision document to return. Omit for the first or only chunk."),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"product_id": product_id}
    if chunk is not None:
        kwargs["chunk"] = chunk
    return await _call_tool(ctx, "get_vision_doc", kwargs)


@mcp.tool(
    name="update_product_context",
    title="Update Product Context",
    description=(
        "Write structured product fields extracted from vision-document analysis. Merge-write: only the "
        "fields you pass change, so it is safe to call in stages; set emit_completion=true on the last "
        "call. Every response reports vision_analysis_complete, missing_for_completion and "
        "fields_skipped."
    ),
    annotations=_tool_hints("update_product_context", destructive=True),
)
async def update_product_context(
    product_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Product id.")],
    product_name: Annotated[
        str, Field(max_length=MCP_NAME_MAX, description="New product name. Empty keeps the current one.")
    ] = "",
    product_description: Annotated[
        str, Field(max_length=MCP_DESCRIPTION_MAX, description="New product description. Empty keeps the current one.")
    ] = "",
    core_features: Annotated[
        str, Field(max_length=MCP_DESCRIPTION_MAX, description="New core features text. Empty keeps the current one.")
    ] = "",
    project_path: Annotated[
        str,
        Field(
            max_length=MCP_DESCRIPTION_MAX,
            description=(
                "Absolute path of the local codebase you operate from; omit if you have no filesystem access to "
                "the user's repository. User-owned: skipped when already set."
            ),
        ),
    ] = "",
    extraction_custom_instructions: Annotated[
        str,
        Field(
            max_length=MCP_DESCRIPTION_MAX,
            description=(
                "Instructions steering future vision-document extraction for this product (e.g. 'focus on backend"
                " architecture')."
            ),
        ),
    ] = "",
    tech_stack: Annotated[
        _TechStackContext | None,
        Field(
            description=(
                "Tech-stack group: programming_languages, frontend_frameworks, "
                "backend_frameworks, databases, infrastructure, target_platforms."
            )
        ),
    ] = None,
    architecture: Annotated[
        _ArchitectureContext | None,
        Field(
            description=(
                "Architecture group: architecture_pattern, design_patterns, api_style, "
                "architecture_notes, coding_conventions, brand_guidelines."
            )
        ),
    ] = None,
    quality: Annotated[
        _QualityContext | None,
        Field(description="Quality group: quality_standards."),
    ] = None,
    testing: Annotated[
        _TestingContext | None,
        Field(description="Testing group: testing_strategy, testing_frameworks, test_coverage_target."),
    ] = None,
    force: Annotated[
        bool,
        Field(
            description=(
                "force=true is required to overwrite a product field that is already populated (otherwise refused"
                " with 'Fields already populated'). Reviewing an existing product is the common case, so most "
                "tech_stack, architecture or quality updates need it."
            )
        ),
    ] = False,
    emit_completion: Annotated[
        bool,
        Field(
            description=(
                "Set true on your final staged call: re-checks completion and signals the dashboard even if "
                "nothing new was written."
            )
        ),
    ] = False,
    vision_summaries: Annotated[
        list[dict] | None,
        Field(description="Per-document summaries: [{doc_id, light, medium}, ...]."),
    ] = None,
    consolidated_vision: Annotated[
        dict | None,
        Field(description="Product-level aggregate summary: {light, medium}."),
    ] = None,
    is_active: Annotated[
        bool | None,
        Field(
            description=(
                "Show (true) or hide (false) this product's tab, like the dashboard's show/hide button; omit to "
                "leave it. Several products can be shown at once, and this never changes which product an "
                "unscoped read resolves to (the default product, set in the dashboard)."
            )
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"product_id": product_id}
    if is_active is not None:
        kwargs["is_active"] = is_active
    kwargs.update(
        {
            name: value
            for name, value in (
                ("product_name", product_name),
                ("product_description", product_description),
                ("core_features", core_features),
                ("project_path", project_path),
                ("extraction_custom_instructions", extraction_custom_instructions),
            )
            if value
        }
    )
    _merge_group(kwargs, tech_stack)
    _merge_group(kwargs, architecture)
    _merge_group(kwargs, quality)
    _merge_group(kwargs, testing)
    if vision_summaries is not None:
        kwargs["vision_summaries"] = vision_summaries
    if consolidated_vision is not None:
        kwargs["consolidated_vision"] = consolidated_vision
    if force:
        kwargs["force"] = True
    if emit_completion:
        kwargs["emit_completion"] = True
    return await _call_tool(ctx, "update_product_context", kwargs)
