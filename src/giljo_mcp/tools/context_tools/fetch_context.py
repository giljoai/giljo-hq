# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unified context fetcher for Giljo HQ.

Handover 0350a: Single entry point for all context fetching.
Dispatches to internal get_* tools based on categories parameter.

Handover 0351: Removed depth params for tech_stack, architecture, testing.
Handover 0823b: Reads user depth_config from DB at runtime when not provided.
IMP-2: Batch category support -- multiple categories per call allowed.

Token Budget Savings: 9 tool schemas (~900 tokens) collapsed to 1 (~180 tokens).
"""
# Read-only tool -- uses direct session.execute() for SELECT queries (no writes)

import logging
from typing import Any

from giljo_mcp.config.defaults import DEFAULT_DEPTH_CONFIG as _RAW_DEPTH_CONFIG
from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.tenant_guard import TenantIsolationError
from giljo_mcp.tools._unknown_keys import split_known
from giljo_mcp.tools.context_tools._response_ceiling import _apply_response_ceiling
from giljo_mcp.tools.context_tools.get_360_memory import get_360_memory
from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates
from giljo_mcp.tools.context_tools.get_architecture import get_architecture
from giljo_mcp.tools.context_tools.get_chain_context import get_chain_context
from giljo_mcp.tools.context_tools.get_git_history import get_git_history, parse_git_history_depth

# Internal tools (NOT exposed via MCP)
from giljo_mcp.tools.context_tools.get_product_context import get_product_context
from giljo_mcp.tools.context_tools.get_project import get_project
from giljo_mcp.tools.context_tools.get_self_identity import get_self_identity
from giljo_mcp.tools.context_tools.get_tasks import get_tasks
from giljo_mcp.tools.context_tools.get_tech_stack import get_tech_stack
from giljo_mcp.tools.context_tools.get_testing import get_testing
from giljo_mcp.tools.context_tools.get_threads import get_threads
from giljo_mcp.tools.context_tools.get_todos import get_todos
from giljo_mcp.tools.context_tools.get_vision_document import get_vision_document


logger = logging.getLogger(__name__)

# Category to internal tool mapping
CATEGORY_TOOLS = {
    "product_core": get_product_context,
    "vision_documents": get_vision_document,
    "tech_stack": get_tech_stack,
    "architecture": get_architecture,
    "testing": get_testing,
    "memory_360": get_360_memory,
    "git_history": get_git_history,
    "agent_templates": get_agent_templates,
    "project": get_project,
    "self_identity": get_self_identity,
    "tasks": get_tasks,
    "todos": get_todos,
    "chain": get_chain_context,
    "threads": get_threads,
}

# Derive from canonical source (defaults.py) - single source of truth (Handover 0823)
# Handover 0840d: DEFAULT_DEPTH_CONFIG is now a flat dict (no "depths" wrapper)
_CANONICAL_DEPTHS = _RAW_DEPTH_CONFIG
DEFAULT_DEPTHS = {
    "product_core": None,
    "vision_documents": _CANONICAL_DEPTHS.get("vision_documents", "medium"),
    "tech_stack": _CANONICAL_DEPTHS.get("tech_stack_sections", "all"),  # BE-9322
    "architecture": None,
    "testing": None,
    "memory_360": _CANONICAL_DEPTHS.get("memory_last_n_projects", 3),
    "git_history": _CANONICAL_DEPTHS.get("git_commits", 25),
    "agent_templates": _CANONICAL_DEPTHS.get("agent_templates", "basic"),
    "project": None,
    "self_identity": None,
    "tasks": None,
    "todos": None,
    "chain": None,
    "threads": None,
}

ALL_CATEGORIES = list(CATEGORY_TOOLS.keys())


# DB key -> internal key mapping for depth_config normalization (Handover 0823b).
# Shared with protocol_builder._get_user_config; defined here to avoid cross-imports.
_DEPTH_KEY_MAPPING: dict[str, str] = {
    "memory_last_n_projects": "memory_360",
    "git_commits": "git_history",
    "agent_templates": "agent_templates",
    "vision_documents": "vision_documents",
    "tech_stack_sections": "tech_stack",  # BE-9322
}


async def _is_category_enabled(
    category: str,
    tenant_key: str,
    db_manager: DatabaseManager,
) -> bool:
    """
    Check if a category is enabled in the user's field priority toggles.

    Categories without a toggle row (product_core, project, self_identity,
    agent_templates) are always enabled.

    Returns:
        True if enabled or no toggle exists, False if explicitly disabled.
    """
    # Categories that are always on (no toggle)
    always_on = {"product_core", "project", "self_identity", "agent_templates", "tasks", "todos", "chain", "threads"}
    if category in always_on:
        return True

    from sqlalchemy import and_, select

    from giljo_mcp.models.auth import User, UserFieldPriority

    try:
        async with db_manager.get_session_async() as session:
            # Get user for this tenant
            user_result = await session.execute(
                select(User.id).where(and_(User.tenant_key == tenant_key, User.is_active)).limit(1)
            )
            user_id = user_result.scalar_one_or_none()
            if not user_id:
                return True  # No user found, allow by default

            # Check toggle
            prio_result = await session.execute(
                select(UserFieldPriority.enabled).where(
                    and_(
                        UserFieldPriority.user_id == user_id,
                        UserFieldPriority.tenant_key == tenant_key,
                        UserFieldPriority.category == category,
                    )
                )
            )
            enabled = prio_result.scalar_one_or_none()
            # No row means default enabled
            return enabled if enabled is not None else True
    except Exception as _exc:  # Broad catch: fail-open for category toggle, non-critical path
        logger.error("category_toggle_check_failed category=%s tenant_key=%s", category, tenant_key, exc_info=True)
        return True  # Fail open — don't block context on toggle errors


async def _build_last_modified_map(
    product_id: str,
    tenant_key: str,
    db_manager: DatabaseManager,
) -> dict[str, str]:
    """
    CE-0031 Task 4: build a category -> last_modified timestamp map for the
    fetch_context response. Lets warm orchestrators detect stale caches
    without re-reading the get_staging_instructions catalog.

    Product-level categories (product_core, vision_documents, tech_stack,
    architecture, testing, agent_templates) share product.updated_at.
    memory_360 uses MAX(created_at) over ProductMemoryEntry. git_history
    has no server-side authority (lives on the local disk) — omitted.

    Returns ISO-8601 timestamps truncated to minute precision, matching the
    format threaded into the orchestrator protocol by
    MissionOrchestrationService._build_category_metadata.
    """
    from sqlalchemy import and_, func, select

    from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
    from giljo_mcp.models.products import Product

    last_modified: dict[str, str] = {}

    try:
        async with db_manager.get_session_async() as session:
            product_row = await session.execute(
                select(Product.updated_at).where(and_(Product.id == product_id, Product.tenant_key == tenant_key))
            )
            product_updated = product_row.scalar_one_or_none()
            if product_updated:
                ts = product_updated.strftime("%Y-%m-%dT%H:%M")
                for cat in (
                    "product_core",
                    "vision_documents",
                    "tech_stack",
                    "architecture",
                    "testing",
                    "agent_templates",
                ):
                    last_modified[cat] = ts

            mem_row = await session.execute(
                select(func.max(ProductMemoryEntry.created_at)).where(
                    and_(
                        ProductMemoryEntry.product_id == product_id,
                        ProductMemoryEntry.tenant_key == tenant_key,
                    )
                )
            )
            mem_max = mem_row.scalar_one_or_none()
            if mem_max:
                last_modified["memory_360"] = mem_max.strftime("%Y-%m-%dT%H:%M")
    except Exception:  # Broad catch: best-effort enrichment, never fails the fetch
        logger.exception("last_modified_map_failed product_id=%s tenant_key=%s", product_id, tenant_key)

    return last_modified


async def _load_user_depth_config(
    tenant_key: str,
    db_manager: DatabaseManager,
) -> dict[str, Any] | None:
    """
    Load the user's depth_config from the DB at runtime (Handover 0823b).

    Queries the first active user for the given tenant_key and normalizes
    their depth_config keys from DB format to internal format.

    Args:
        tenant_key: Tenant isolation key
        db_manager: Database manager instance

    Returns:
        Normalized depth config dict, or None if no user or no config found.
    """
    from sqlalchemy import and_, select

    from giljo_mcp.models.auth import User

    try:
        async with db_manager.get_session_async() as session:
            result = await session.execute(
                select(User)
                .where(
                    and_(
                        User.tenant_key == tenant_key,
                        User.is_active,
                    )
                )
                .limit(1)
            )
            user = result.scalar_one_or_none()

            if not user:
                logger.debug("depth_config_not_found tenant_key=%s user_found=False", tenant_key)
                return None

            # Handover 0840d: Read depth from columns, normalize keys to internal format
            raw_depth = {
                "vision_documents": user.depth_vision_documents,
                "memory_last_n_projects": user.depth_memory_last_n,
                "git_commits": user.depth_git_commits,
                "agent_templates": user.depth_agent_templates,
                "tech_stack_sections": user.depth_tech_stack_sections,
                "architecture_depth": user.depth_architecture,
            }

            normalized: dict[str, Any] = {}
            for db_key, value in raw_depth.items():
                internal_key = _DEPTH_KEY_MAPPING.get(db_key, db_key)
                normalized[internal_key] = value

            # Normalize vision_documents "optional" -> "light" (same as protocol_builder)
            if normalized.get("vision_documents") == "optional":
                normalized["vision_documents"] = "light"
                logger.debug("depth_config_vision_normalized tenant_key=%s", tenant_key)

            logger.info("depth_config_loaded_from_db tenant_key=%s depth_keys=%s", tenant_key, list(normalized.keys()))
            return normalized

    except Exception as _exc:  # Broad catch: fail-open for depth config, returns None fallback
        logger.error("depth_config_load_failed tenant_key=%s", tenant_key, exc_info=True)
        return None


async def _resolve_product_id_from_project(
    project_id: str,
    tenant_key: str,
    db_manager: DatabaseManager,
) -> str:
    """Resolve a project's product_id via a tenant-scoped lookup (BE-6208e).

    A combined-chain sub-orchestrator is handed a project_id but no product_id,
    yet its documented startup step calls get_context — which needs product_id.
    Reuse the existing tenant-scoped ``ProjectRepository.get_by_id`` so a
    project_id belonging to another tenant cannot resolve (tenant_key is the
    isolation boundary, ADR-009).

    Raises:
        ResourceNotFoundError: project not found for this tenant, or has no
            associated product.
    """
    from giljo_mcp.repositories.project_repository import ProjectRepository

    repo = ProjectRepository()
    async with db_manager.get_session_async() as session:
        project = await repo.get_by_id(session, tenant_key, project_id)

    if project is None or not project.product_id:
        logger.warning(
            "product_id_resolution_failed project_id=%s tenant_key=%s found=%s",
            project_id,
            tenant_key,
            project is not None,
        )
        raise ResourceNotFoundError(
            message="Project not found for this tenant or has no associated product",
            context={"project_id": project_id, "tenant_key": tenant_key},
        )

    return str(project.product_id)


async def _resolve_active_product_id(tenant_key: str, db_manager: DatabaseManager) -> str:
    """Resolve the tenant's ACTIVE product_id (BE-6211c / C-3.3).

    A PROJECT-LESS chain conductor is handed neither product_id nor project_id, so the
    project->product resolution above cannot help. Reuse the SAME tenant-scoped lookup
    ``list_projects`` uses (``ProductService.get_active_product``); ADR-009 keeps it to
    the caller's own active product. Raises ValidationError when none is set.
    """
    from giljo_mcp.services.product_service import ProductService

    product_service = ProductService(db_manager=db_manager, tenant_key=tenant_key)
    active_product = await product_service.get_active_product(eager_load=False)  # only id needed
    if active_product is None:
        raise ValidationError(
            "No active product set. Please activate a product first.",
            context={"tenant_key": tenant_key, "operation": "fetch_context"},
        )
    return str(active_product.id)


def _reject_unknown_depth_keys(depth_config: dict[str, Any] | None) -> None:
    """Reject depth_config keys that are not category names (BE-9322).

    depth_config is keyed by CATEGORY. A DB column name ("memory_last_n_projects")
    used to apply the default silently while depth_config_applied truthfully
    reported that default -- so nothing in the response named the dropped key.
    The sibling `categories` argument already rejects unknown values; this makes
    depth_config behave the same way.
    """
    if not depth_config:
        return
    _used, unknown = split_known(depth_config, CATEGORY_TOOLS)
    if not unknown:
        return
    logger.warning("invalid_depth_config_keys invalid=%s valid=%s", unknown, ALL_CATEGORIES)
    raise ValidationError(
        f"Invalid depth_config key(s): {unknown}. Valid keys: {ALL_CATEGORIES}. "
        f"Use the CATEGORY name, not the DB column name "
        f"(e.g. 'memory_360' not 'memory_last_n_projects').",
        context={"invalid_keys": unknown, "allowed": ALL_CATEGORIES},
    )


async def fetch_context(
    product_id: str,
    tenant_key: str,
    project_id: str | None = None,
    categories: list[str | None] = None,
    depth_config: dict[str, Any | None] = None,
    output_format: str = "structured",
    agent_name: str | None = None,
    job_id: str | None = None,
    db_manager: DatabaseManager | None = None,
) -> dict[str, Any]:
    """
    Unified context fetcher - dispatches to internal tools.

    Handover 0350a: Single MCP tool that replaces 9 individual tools,
    saving ~720 tokens in MCP schema overhead.

    Handover 0430: Added self_identity category for agent self-awareness.

    Handover 0823b: When depth_config is not provided, reads the user's current
    depth settings from the DB via tenant_key, making depth live-tunable.

    Args:
        product_id: Product UUID
        tenant_key: Tenant isolation key
        project_id: Optional project UUID (required for 'project' category)
        categories: List of categories to fetch, or ["all"] for all categories
                   Valid: product_core, vision_documents, tech_stack, architecture,
                          testing, memory_360, git_history, agent_templates, project,
                          self_identity, chain
        depth_config: Override depth settings, keyed by CATEGORY name. If None, reads
                     from DB. Unknown keys raise ValidationError (BE-9322) -- pass
                     'memory_360', not the DB column name 'memory_last_n_projects'.
                     Example: {"vision_documents": "light", "agent_templates": "full"}
        format: Response format - "structured" (nested by category) or "flat" (merged)
        agent_name: Agent template name (required for 'self_identity' category)
        db_manager: Database manager instance

    Returns:
        Dict with context data organized by category, plus metadata:
        {
            "source": "fetch_context",
            "categories_requested": ["product_core", "tech_stack"],
            "categories_returned": ["product_core", "tech_stack"],
            "data": {
                "product_core": {...},
                "tech_stack": {...}
            },
            "metadata": {
                "estimated_tokens": 300,
                "format": "structured",
                "depth_config_applied": {...}
            }
        }

    Multi-Tenant Isolation:
        All internal tools enforce tenant_key filtering.

    Token Budget Reference:
        - product_core: ~100 tokens; vision_documents: 0-24K tokens (none/light/medium/full)
        - tech_stack: 200-400 tokens (required/all); architecture: ~1K tokens, NOT depth-tunable
          (get_architecture takes no depth parameter -- depth_architecture is stored but never applied)
        - testing: 0-400 tokens (none/basic/full); memory_360: 500-5K tokens (last_n_projects: 1/3/5/10)
        - git_history: 500-5K tokens (commits: 10/25/50/100); agent_templates: 400-2.4K tokens (basic/full)
        - project: ~300 tokens; self_identity: ~1-3K tokens (Handover 0430)
        - chain: ~100-2K tokens (the caller's active chain run: run_id, chain_mission,
          resolved_order; empty + error="no_active_chain_run" outside a chain)

    Example:
        # Fetch all context with defaults (tenant_key auto-injected server-side)
        result = await fetch_context(
            product_id="uuid-123",
        )

        # Fetch specific categories with depth override
        result = await fetch_context(
            product_id="uuid-123",
            categories=["vision_documents", "agent_templates"],
            depth_config={"vision_documents": "light"}
        )
    """
    logger.info(
        "fetch_context_started product_id=%s tenant_key=%s project_id=%s categories=%s format=%s agent_name=%s",
        product_id,
        tenant_key,
        project_id,
        categories,
        output_format,
        agent_name,
    )

    # IMP-2: Categories parameter is required -- agents must be explicit
    if categories is None:
        logger.warning("fetch_context_missing_category tenant_key=%s", tenant_key)
        return {
            "error": "CATEGORIES_REQUIRED",
            "message": "categories parameter is required. Pass one or more category names.",
            "valid_categories": ALL_CATEGORIES,
            "example": "get_context(categories=['product_core', 'tech_stack'], ...)",
            "metadata": {},
        }

    # Reject "all" -- forces agents to be explicit about what they need
    if "all" in categories:
        logger.warning("fetch_context_all_rejected tenant_key=%s", tenant_key)
        return {
            "error": "ALL_NOT_ALLOWED",
            "message": (
                "categories=['all'] is not allowed. List the specific categories you need, "
                "e.g. categories=['product_core', 'tech_stack', 'architecture']."
            ),
            "valid_categories": ALL_CATEGORIES,
            "example": "get_context(categories=['product_core', 'tech_stack'], ...)",
            "metadata": {},
        }

    # Validate all requested categories upfront
    invalid = [c for c in categories if c not in CATEGORY_TOOLS]
    if invalid:
        logger.warning("invalid_categories invalid=%s valid=%s", invalid, ALL_CATEGORIES)
        raise ValidationError(f"Invalid categories: {invalid}. Valid categories: {ALL_CATEGORIES}")

    _reject_unknown_depth_keys(depth_config)

    # BE-6208e: a combined-chain sub-orchestrator gets a project_id but no
    # product_id. When product_id is absent/empty and a project_id is present,
    # resolve it server-side via a tenant-scoped lookup. The explicit-product_id
    # path (solo) is unchanged.
    if not product_id:
        if project_id and db_manager:
            product_id = await _resolve_product_id_from_project(project_id, tenant_key, db_manager)
            logger.info(
                "fetch_context_resolved_product_id project_id=%s product_id=%s tenant_key=%s",
                project_id,
                product_id,
                tenant_key,
            )
        elif db_manager:
            # BE-6211c (C-3.3): a PROJECT-LESS conductor has neither product_id nor
            # project_id, so the resolution above cannot help. Fall back to the
            # session's active product exactly as list_projects does — reusing the
            # existing tenant-scoped ProductService.get_active_product. Strictly
            # additive on the previously-erroring path.
            product_id = await _resolve_active_product_id(tenant_key, db_manager)
            logger.info(
                "fetch_context_resolved_active_product product_id=%s tenant_key=%s",
                product_id,
                tenant_key,
            )
        else:
            raise ValidationError("product_id is required (or pass project_id so it can be resolved).")

    # Resolve effective depth settings (Handover 0823b)
    effective_depths = DEFAULT_DEPTHS.copy()

    if depth_config:
        # Agent explicitly provided depth -- use it (backwards compatibility)
        effective_depths.update(depth_config)
    elif db_manager:
        # No depth from agent -- read user's current settings from DB (Handover 0823b)
        user_depths = await _load_user_depth_config(tenant_key, db_manager)
        if user_depths:
            effective_depths.update(user_depths)

    # IMP-2: Batch fetch -- iterate over all requested categories
    # Wave 1 IMP-0019 Item 2: emit explicit empty entries for every fetched
    # category (including directive-only ones) so the contract
    # `categories_requested == categories_returned union failed_categories` holds.
    all_data: dict[str, Any] = {}
    all_directives: dict[str, Any] = {}
    all_errors: list[dict[str, str]] = []
    categories_returned: list[str] = []
    categories_empty: list[str] = []

    for category in categories:
        # Enforce user field priority toggles -- skip disabled categories silently
        if db_manager:
            enabled = await _is_category_enabled(category, tenant_key, db_manager)
            if not enabled:
                logger.info("fetch_context_category_disabled category=%s tenant_key=%s", category, tenant_key)
                continue

        try:
            result = await _fetch_category(
                category=category,
                product_id=product_id,
                tenant_key=tenant_key,
                project_id=project_id,
                depth=effective_depths.get(category),
                agent_name=agent_name,
                job_id=job_id,
                db_manager=db_manager,
            )
            # Use sentinel to distinguish "key absent" from "key present but empty"
            cat_data = result.get("data", {})
            directive = result.get("directive")

            categories_returned.append(category)

            if directive:
                all_directives[category] = directive
                # Uniform contract: directive-handled categories also appear in
                # data with an explicit marker so callers don't need to inspect
                # the directive block to know the category was processed.
                all_data[category] = {"directive": True}
            elif cat_data:
                all_data[category] = cat_data
            else:
                # Empty payload: preserve list-vs-dict shape so callers get a
                # predictable type. The presence of the key (with empty value)
                # IS the signal — silent omission would force callers to diff
                # categories_requested against categories_returned.
                empty_value: Any = [] if isinstance(cat_data, list) else {}
                all_data[category] = empty_value
                categories_empty.append(category)
        except TenantIsolationError:
            # Flattening this into `errors` below returns a SUCCESS leaking the guard's
            # internal phrasing; it must reach the MCP boundary's not-found contract.
            raise
        except Exception as e:  # Broad catch: tool boundary, logs per-category errors
            logger.error("category_fetch_error category=%s error=%s", category, e, exc_info=True)
            all_errors.append({"category": category, "error": str(e)})

    # Build response
    depth_applied = {c: effective_depths.get(c) for c in categories}

    if output_format == "structured":
        response_data = all_data
    else:
        # Flat format: merge all category data into a single dict
        response_data = {}
        for cat_data in all_data.values():
            if isinstance(cat_data, dict):
                response_data.update(cat_data)
            else:
                response_data[str(type(cat_data))] = cat_data

    # CE-0031 Task 4: per-category last_modified timestamps so warm orchestrators
    # can detect a stale cache without re-pulling the get_staging_instructions
    # catalog. Best-effort; omits a category when no authoritative server-side
    # timestamp exists (e.g. git_history, todos).
    last_modified: dict[str, str] = {}
    if db_manager:
        full_map = await _build_last_modified_map(product_id, tenant_key, db_manager)
        last_modified = {c: ts for c, ts in full_map.items() if c in categories_returned}

    response: dict[str, Any] = {
        "source": "fetch_context",
        "categories_requested": list(categories),
        "categories_returned": categories_returned,
        # Wave 1 IMP-0019 Item 2: surface the empty-payload categories so
        # callers can distinguish "fetched with data" from "fetched but empty".
        "categories_empty": categories_empty,
        "data": response_data,
        "last_modified": last_modified,
        "metadata": {
            "format": output_format,
            "depth_config_applied": depth_applied,
        },
    }

    if all_directives:
        response["directive"] = all_directives

    if all_errors:
        response["errors"] = all_errors

    # INF-WriteShape: 30K-char hard ceiling with graceful field-drop.
    response = _apply_response_ceiling(response)

    logger.info(
        "fetch_context_completed requested=%s returned=%s error_count=%d",
        list(categories),
        categories_returned,
        len(all_errors),
    )

    return response


async def _fetch_category(
    category: str,
    product_id: str,
    tenant_key: str,
    project_id: str | None,
    depth: Any,
    agent_name: str | None,
    db_manager: DatabaseManager,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Dispatch to internal tool based on category.

    Maps category names to internal tool functions and translates
    depth configuration to tool-specific parameters.
    """
    tool_func = CATEGORY_TOOLS[category]

    # Build kwargs based on category and its depth parameter name
    kwargs = {"db_manager": db_manager}

    if category in ("project", "chain"):
        if not project_id:
            logger.warning("%s_category_missing_project_id", category)
            return {"data": {}, "metadata": {"error": f"project_id required for '{category}' category"}}
        kwargs["project_id"] = project_id
        kwargs["tenant_key"] = tenant_key
        # No depth param for project / chain

    elif category == "self_identity":
        if not agent_name:
            logger.warning("self_identity_category_missing_agent_name")
            return {
                "source": "self_identity",
                "data": {},
                "metadata": {"error": "agent_name required for 'self_identity' category"},
            }
        kwargs["agent_name"] = agent_name
        kwargs["tenant_key"] = tenant_key
        # No depth param for self_identity

    elif category == "agent_templates":
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        if depth:
            kwargs["detail"] = depth

    elif category == "vision_documents":
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        if depth:
            kwargs["chunking"] = depth

    elif category == "memory_360":
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        # INF-WriteShape: depth_config["memory_360"] accepts:
        #   * int N -- last_n_projects = N, headlines shape (default)
        #   * "full" -- full bodies, last_n_projects from default
        #   * "headlines" -- explicit headlines (matches default)
        #   * dict {"last_n_projects": N, "shape": "full"|"headlines"}
        if isinstance(depth, dict):
            if "last_n_projects" in depth:
                kwargs["last_n_projects"] = int(depth["last_n_projects"])
            shape = depth.get("shape")
            if shape in ("full", "headlines"):
                kwargs["depth"] = shape
        elif isinstance(depth, str):
            if depth in ("full", "headlines"):
                kwargs["depth"] = depth
        elif depth:
            kwargs["last_n_projects"] = int(depth)

    elif category == "git_history":
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        # TSK-9159: tolerant parse — the boundary advertises string tokens.
        if (commits := parse_git_history_depth(depth)) is not None:
            kwargs["commits"] = commits

    elif category == "tech_stack":
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        if depth:
            kwargs["sections"] = depth  # BE-9322: get_tech_stack's sections kwarg

    elif category in ("architecture", "testing"):
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        # No depth param. BE-9322 leaves architecture_depth unwired on
        # purpose: default "overview" would shrink every user's context.

    elif category == "tasks":
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        if depth and isinstance(depth, int):
            kwargs["limit"] = depth

    elif category == "threads":
        kwargs["tenant_key"] = tenant_key
        # Q-08: tenant-scoped only -- no product_id kwarg (see get_threads.py
        # docstring: 38/419 production threads have product_id=None, so
        # product-scoping would return [] on a tenant holding hundreds of
        # threads). No depth param either -- the cap is fixed in
        # get_threads.THREADS_CATEGORY_CAP, not tunable via depth_config
        # (mirrors the architecture/testing precedent above, BE-9322).

    elif category == "todos":
        # INF-5077: TODO read-back. Requires job_id (the agent job whose
        # TODOs the caller wants to read). product_id is not used.
        if not job_id:
            logger.warning("todos_category_missing_job_id")
            return {
                "source": "todos",
                "data": {},
                "metadata": {"error": "job_id required for 'todos' category"},
            }
        kwargs["job_id"] = job_id
        kwargs["tenant_key"] = tenant_key

    else:  # product_core
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        # No depth param for product_core

    return await tool_func(**kwargs)
