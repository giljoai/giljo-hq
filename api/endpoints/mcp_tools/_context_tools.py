# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Context & Product Tools -- @mcp.tool wrappers (BE-6042d split of mcp_sdk_server.py).

Mechanically extracted verbatim from the pre-split ``mcp_sdk_server.py``. Each
wrapper registers against the shared ``mcp`` instance from ``_base`` as a decorator
side effect at import time. Behavior, signatures, names, and descriptions unchanged.
"""

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field

from api.endpoints.mcp_tools._base import (
    MCP_DESCRIPTION_MAX,
    MCP_ID_MAX,
    MCP_NAME_MAX,
    MCP_SHORT_TEXT_MAX,
    _call_tool,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.services.product_memory_service import (
    SEARCH_MEMORY_LIMIT_DEFAULT,
    SEARCH_MEMORY_LIMIT_MAX,
)


# BE-3006d: the update_product_context free-text params flow to unbounded Postgres
# ``Text`` columns through ProductService (which caps nothing but the
# target_platforms membership), so cap them here at the boundary. Short labels use
# the name cap; long-form prose uses the description cap. Bounded well above any
# realistic value, but enough to stop a runaway agent ballooning a row.
_PRODUCT_LABEL = Field(max_length=MCP_NAME_MAX)
_PRODUCT_PROSE = Field(max_length=MCP_DESCRIPTION_MAX)


# BE-9118 (Option B): the 17 flat prose params update_product_context used to take
# are regrouped into four typed dicts. Each model is a MCP-boundary INPUT grouping
# only -- the wrapper unpacks it verbatim to the SAME flat ProductService kwargs, so
# the DB/service/columns are untouched. Typing each group as a Pydantic model keeps
# the per-field length caps at the FastMCP arg-validation boundary (a clean 422-style
# ToolError, never a service-layer 500 / DB constraint) exactly as the flat
# Field(max_length=...) params did before -- caps live INSIDE the dicts now.
# ``extra="forbid"`` rejects an unknown sub-key at the boundary with agent-facing
# guidance (mirrors FastMCP's rejection of an unknown flat kwarg pre-regroup).
class _TechStackContext(BaseModel):
    """Grouped tech-stack fields (BE-9118). Unpacked to flat ProductService kwargs."""

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
    """Grouped architecture/design fields (BE-9118). Unpacked to flat kwargs."""

    model_config = {"extra": "forbid"}

    architecture_pattern: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    design_patterns: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    api_style: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    architecture_notes: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    coding_conventions: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    brand_guidelines: str = Field("", max_length=MCP_DESCRIPTION_MAX)


class _QualityContext(BaseModel):
    """Grouped quality field(s) (BE-9118). Unpacked to flat kwargs."""

    model_config = {"extra": "forbid"}

    quality_standards: str = Field("", max_length=MCP_DESCRIPTION_MAX)


class _TestingContext(BaseModel):
    """Grouped testing fields (BE-9118). Unpacked to flat kwargs."""

    model_config = {"extra": "forbid"}

    testing_strategy: str = Field(
        "",
        max_length=MCP_DESCRIPTION_MAX,
        description="One of: TDD, BDD, Integration-First, E2E-First, Manual, Hybrid.",
    )
    testing_frameworks: str = Field("", max_length=MCP_DESCRIPTION_MAX)
    test_coverage_target: int | None = Field(None, description="Integer 0-100.")


def _merge_group(kwargs: dict[str, Any], group: BaseModel | None) -> None:
    """Unpack a grouped context model into flat ProductService kwargs (BE-9118).

    Byte-identical to the pre-regroup flat merge-write: skip unset (``None``) and
    empty-string fields, forward everything else. The grouped field names ARE the
    same flat kwargs ProductService.update_product() already consumes, so the
    service/DB path is unchanged.
    """
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
        "Unified context fetcher: retrieves product/project context by category, with depth "
        "control. Pass one or more categories in a single call. For one project's "
        "description/mission use categories=['project']. Never pass tenant_key. See the "
        "categories param for the full category list + token costs, and get_giljo_guide for "
        "read-vs-write routing."
    ),
    annotations=_tool_hints("get_context"),
)
async def get_context(
    product_id: Annotated[
        str,
        Field(
            description="Product UUID. Optional when project_id is supplied — the server resolves the product from the project (tenant-scoped)."
        ),
    ] = "",
    project_id: str = "",
    agent_name: Annotated[
        str, Field(description="Agent template name (e.g. 'implementer-backend') for self_identity category. Optional.")
    ] = "",
    job_id: Annotated[
        str,
        Field(
            description="Agent job UUID. REQUIRED for the 'todos' category (read-back of an agent's TODO list — sequence + content + status). Ignored by other categories."
        ),
    ] = "",
    categories: Annotated[
        list[str] | None,
        Field(
            description=(
                "List of categories to fetch (required, must be a list, e.g. ['tech_stack', "
                "'architecture']): product_core (~100 tokens), vision_documents (0-24K), "
                "tech_stack (200-400), architecture (300-1.5K), testing (0-400), memory_360 "
                "(500-5K, most recent N closeouts by sequence DESC, default N=3; tune via "
                "depth_config={'memory_360': <int>} or {'memory_360': {'last_n_projects': N, "
                "'shape': 'full'|'headlines'}}), git_history (500-5K), agent_templates (400-2.4K), "
                "project (~300), self_identity (agent template content), tasks (open task list), "
                "todos (TODO content for a job — pass job_id, used for force-recovery), "
                "chain (the caller's active chain run: run_id, chain_mission, resolved_order — "
                "requires project_id; empty + error='no_active_chain_run' outside a chain), "
                "threads (the tenant's Hub threads, read-only, up to 25 most recent; not "
                "depth-tunable)."
            )
        ),
    ] = None,
    depth_config: Annotated[
        dict | None,
        Field(
            description=(
                "Optional depth overrides, keyed by CATEGORY name, e.g. {'vision_documents': 'full', "
                "'git_history': 'summary'}. Keys must be category names (as in `categories`), NOT user "
                "depth-setting names -- 'memory_360' not 'memory_last_n_projects', 'tech_stack' not "
                "'tech_stack_sections'. An unrecognized key is rejected with the accepted list; it is "
                "never silently ignored. Omit entirely to use the user's saved depth settings."
            )
        ),
    ] = None,
    output_format: Annotated[str, Field(description="Output format: 'structured' (default) or 'flat'.")] = "structured",
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
        "optional tag narrows to one controlled-vocabulary value. Tenant + active-product scoped "
        "(never pass tenant_key). Returns relevance-ranked headlines, capped at limit. Distinct "
        "from get_context(memory_360) (recency, not search) and search_threads (Hub chat, not "
        "memory)."
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
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"query": query, "limit": limit}
    if tag:
        kwargs["tag"] = tag
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
    description: Annotated[str, _PRODUCT_PROSE] = "",
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
    core_features: Annotated[str, _PRODUCT_PROSE] = "",
    brand_guidelines: Annotated[str, _PRODUCT_PROSE] = "",
    target_platforms: Annotated[
        list[str] | None,
        Field(description="Subset of: windows, linux, macos, android, ios, web, all."),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    # Merge-write style: forward only provided, non-empty optional values so the
    # service receives None (not "") for anything the agent omitted.
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
    product_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    content: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Full markdown vision document text (same size cap as the UI upload). After "
                "creating, call get_vision_doc then update_product_context (vision_summaries + "
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
    name="get_vision_doc",
    title="Get Vision Document",
    description=(
        "Retrieve a product's vision document with extraction instructions. "
        "Call WITHOUT chunk to get metadata (total_chunks, extraction_instructions). "
        "Then fetch chunk=1 through chunk=total_chunks -- these reads are independent "
        "and side-effect free, so request them in PARALLEL, in any order. Read ALL "
        "chunks before calling update_product_context."
    ),
    annotations=_tool_hints("get_vision_doc"),
)
async def get_vision_doc(
    product_id: str,
    chunk: int | None = None,
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
        "Write structured product fields extracted from vision document analysis. Merge-write: "
        "only provided fields are updated, and it is SAFE TO CALL IN STAGES -- split a large "
        "analysis across several calls and set emit_completion=true on the last one. Every "
        "response reports vision_analysis_complete, missing_for_completion, and fields_skipped, "
        "so you never have to infer what landed. See the tech_stack/architecture/quality/testing "
        "param groups, project_path, and vision_summaries/consolidated_vision for field detail."
    ),
    annotations=_tool_hints("update_product_context"),
)
async def update_product_context(
    product_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    product_name: Annotated[str, _PRODUCT_LABEL] = "",
    product_description: Annotated[str, _PRODUCT_PROSE] = "",
    core_features: Annotated[str, _PRODUCT_PROSE] = "",
    project_path: Annotated[
        str,
        Field(
            max_length=MCP_DESCRIPTION_MAX,
            description=(
                "Absolute path of the user's local codebase folder you are operating from (your "
                "working directory); OMIT if you have no filesystem access inside the user's "
                "repository — never guess. Like product_name, it is user-owned and skipped when "
                "already set."
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
    force: bool = False,
    emit_completion: Annotated[
        bool,
        Field(
            description=(
                "Set true on your FINAL staged call. Re-checks the completion state and signals "
                "the dashboard even when this call writes no new fields."
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
    ctx: Context = None,
) -> dict[str, Any]:
    # Merge-write: forward only provided, non-empty values. The grouped dicts unpack
    # to the SAME flat kwargs ProductService.update_product() consumes (BE-9118).
    kwargs: dict[str, Any] = {"product_id": product_id}
    kwargs.update(
        {
            name: value
            for name, value in (
                ("product_name", product_name),
                ("product_description", product_description),
                ("core_features", core_features),
                ("project_path", project_path),
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
