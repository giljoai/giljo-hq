# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from giljo_mcp.config.defaults import DEFAULT_DEPTH_CONFIG as _RAW_DEPTH_CONFIG
from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.tenant_guard import TenantIsolationError
from giljo_mcp.tools._unknown_keys import split_known
from giljo_mcp.tools.context_tools._response_assembly import assemble_fetch_context_response
from giljo_mcp.tools.context_tools.get_360_memory import get_360_memory
from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates
from giljo_mcp.tools.context_tools.get_architecture import get_architecture
from giljo_mcp.tools.context_tools.get_chain_context import get_chain_context
from giljo_mcp.tools.context_tools.get_git_history import get_git_history, parse_git_history_depth

from giljo_mcp.tools.context_tools.get_product_context import get_product_context
from giljo_mcp.tools.context_tools.get_products import get_products
from giljo_mcp.tools.context_tools.get_project import get_project
from giljo_mcp.tools.context_tools.get_self_identity import get_self_identity
from giljo_mcp.tools.context_tools.get_tasks import get_tasks
from giljo_mcp.tools.context_tools.get_tech_stack import get_tech_stack
from giljo_mcp.tools.context_tools.get_testing import get_testing
from giljo_mcp.tools.context_tools.get_threads import get_threads
from giljo_mcp.tools.context_tools.get_todos import get_todos
from giljo_mcp.tools.context_tools.get_vision_document import get_vision_document


logger = logging.getLogger(__name__)

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
    "products": get_products,
}

_CANONICAL_DEPTHS = _RAW_DEPTH_CONFIG
DEFAULT_DEPTHS = {
    "product_core": None,
    "vision_documents": _CANONICAL_DEPTHS.get("vision_documents", "medium"),
    "tech_stack": _CANONICAL_DEPTHS.get("tech_stack_sections", "all"),
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
    "products": None,
}

ALL_CATEGORIES = list(CATEGORY_TOOLS.keys())

_CATEGORIES_NOT_REQUIRING_PRODUCT_ID = {"project", "chain", "self_identity", "threads", "todos", "products"}


_DEPTH_KEY_MAPPING: dict[str, str] = {
    "memory_last_n_projects": "memory_360",
    "git_commits": "git_history",
    "agent_templates": "agent_templates",
    "vision_documents": "vision_documents",
    "tech_stack_sections": "tech_stack",
}


async def _is_category_enabled(
    category: str,
    tenant_key: str,
    db_manager: DatabaseManager,
) -> bool:
    always_on = {
        "product_core",
        "project",
        "self_identity",
        "agent_templates",
        "tasks",
        "todos",
        "chain",
        "threads",
        "products",
    }
    if category in always_on:
        return True

    from sqlalchemy import and_, select

    from giljo_mcp.models.auth import User, UserFieldPriority

    try:
        async with db_manager.get_session_async() as session:
            user_result = await session.execute(
                select(User.id).where(and_(User.tenant_key == tenant_key, User.is_active)).limit(1)
            )
            user_id = user_result.scalar_one_or_none()
            if not user_id:
                return True

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
            return enabled if enabled is not None else True
    except Exception as _exc:
        logger.error("category_toggle_check_failed category=%s tenant_key=%s", category, tenant_key, exc_info=True)
        return True


async def _build_last_modified_map(
    product_id: str,
    tenant_key: str,
    db_manager: DatabaseManager,
) -> dict[str, str]:
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
    except Exception:
        logger.exception("last_modified_map_failed product_id=%s tenant_key=%s", product_id, tenant_key)

    return last_modified


async def _load_user_depth_config(
    tenant_key: str,
    db_manager: DatabaseManager,
) -> dict[str, Any] | None:
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

            if normalized.get("vision_documents") == "optional":
                normalized["vision_documents"] = "light"
                logger.debug("depth_config_vision_normalized tenant_key=%s", tenant_key)

            logger.info("depth_config_loaded_from_db tenant_key=%s depth_keys=%s", tenant_key, list(normalized.keys()))
            return normalized

    except Exception as _exc:
        logger.error("depth_config_load_failed tenant_key=%s", tenant_key, exc_info=True)
        return None


async def _resolve_product_id_from_project(
    project_id: str,
    tenant_key: str,
    db_manager: DatabaseManager,
) -> str:
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


async def _resolve_default_product_id(tenant_key: str, db_manager: DatabaseManager) -> str:
    from giljo_mcp.services.product_service import ProductService

    product_service = ProductService(db_manager=db_manager, tenant_key=tenant_key)
    default_product = await product_service.get_default_product(eager_load=False)
    if default_product is None:
        raise ValidationError(
            "No default product set. Please set a default product first.",
            context={"tenant_key": tenant_key, "operation": "accessor.fetch_context"},
        )
    return str(default_product.id)


async def _resolve_missing_product_id(
    categories: list[str | None],
    project_id: str | None,
    tenant_key: str,
    db_manager: DatabaseManager | None,
) -> str:
    if project_id and db_manager:
        product_id = await _resolve_product_id_from_project(project_id, tenant_key, db_manager)
        logger.info(
            "fetch_context_resolved_product_id project_id=%s product_id=%s tenant_key=%s",
            project_id,
            product_id,
            tenant_key,
        )
        return product_id

    if not db_manager:
        raise ValidationError("product_id is required (or pass project_id so it can be resolved).")

    if set(categories) <= _CATEGORIES_NOT_REQUIRING_PRODUCT_ID:
        return ""

    product_id = await _resolve_default_product_id(tenant_key, db_manager)
    logger.info("fetch_context_resolved_default_product product_id=%s tenant_key=%s", product_id, tenant_key)
    return product_id


def _reject_unknown_depth_keys(depth_config: dict[str, Any] | None) -> None:
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
    logger.info(
        "fetch_context_started product_id=%s tenant_key=%s project_id=%s categories=%s format=%s agent_name=%s",
        product_id,
        tenant_key,
        project_id,
        categories,
        output_format,
        agent_name,
    )

    if categories is None:
        logger.warning("fetch_context_missing_category tenant_key=%s", tenant_key)
        return {
            "error": "CATEGORIES_REQUIRED",
            "message": "categories parameter is required. Pass one or more category names.",
            "valid_categories": ALL_CATEGORIES,
            "example": "get_context(categories=['product_core', 'tech_stack'], ...)",
            "metadata": {},
        }

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

    invalid = [c for c in categories if c not in CATEGORY_TOOLS]
    if invalid:
        logger.warning("invalid_categories invalid=%s valid=%s", invalid, ALL_CATEGORIES)
        raise ValidationError(f"Invalid categories: {invalid}. Valid categories: {ALL_CATEGORIES}")

    _reject_unknown_depth_keys(depth_config)

    if not product_id:
        product_id = await _resolve_missing_product_id(
            categories=categories,
            project_id=project_id,
            tenant_key=tenant_key,
            db_manager=db_manager,
        )

    effective_depths = DEFAULT_DEPTHS.copy()

    if depth_config:
        effective_depths.update(depth_config)
    elif db_manager:
        user_depths = await _load_user_depth_config(tenant_key, db_manager)
        if user_depths:
            effective_depths.update(user_depths)

    all_data: dict[str, Any] = {}
    all_directives: dict[str, Any] = {}
    all_errors: list[dict[str, str]] = []
    categories_returned: list[str] = []
    categories_empty: list[str] = []
    all_category_metadata: dict[str, Any] = {}

    for category in categories:
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
            cat_data = result.get("data", {})
            directive = result.get("directive")
            cat_metadata = result.get("metadata")

            categories_returned.append(category)

            if cat_metadata:
                all_category_metadata[category] = {k: v for k, v in cat_metadata.items() if k != "tenant_key"}

            if directive:
                all_directives[category] = directive
                all_data[category] = {"directive": True}
            elif cat_data:
                all_data[category] = cat_data
            else:
                empty_value: Any = [] if isinstance(cat_data, list) else {}
                all_data[category] = empty_value
                categories_empty.append(category)
        except TenantIsolationError:
            raise
        except Exception as e:
            logger.error("category_fetch_error category=%s error=%s", category, e, exc_info=True)
            all_errors.append({"category": category, "error": "CATEGORY_FETCH_FAILED"})

    last_modified: dict[str, str] = {}
    if db_manager:
        full_map = await _build_last_modified_map(product_id, tenant_key, db_manager)
        last_modified = {c: ts for c, ts in full_map.items() if c in categories_returned}

    response = assemble_fetch_context_response(
        categories=categories,
        all_data=all_data,
        all_directives=all_directives,
        all_errors=all_errors,
        categories_returned=categories_returned,
        categories_empty=categories_empty,
        all_category_metadata=all_category_metadata,
        effective_depths=effective_depths,
        output_format=output_format,
        last_modified=last_modified,
    )

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
    tool_func = CATEGORY_TOOLS[category]

    kwargs = {"db_manager": db_manager}

    if category in ("project", "chain"):
        if not project_id:
            logger.warning("%s_category_missing_project_id", category)
            return {"data": {}, "metadata": {"error": f"project_id required for '{category}' category"}}
        kwargs["project_id"] = project_id
        kwargs["tenant_key"] = tenant_key

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
        if (commits := parse_git_history_depth(depth)) is not None:
            kwargs["commits"] = commits

    elif category == "tech_stack":
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        if depth:
            kwargs["sections"] = depth

    elif category in ("architecture", "testing"):
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key

    elif category == "tasks":
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key
        if depth and isinstance(depth, int):
            kwargs["limit"] = depth

    elif category in {"threads", "products"}:
        kwargs["tenant_key"] = tenant_key

    elif category == "todos":
        if not job_id:
            logger.warning("todos_category_missing_job_id")
            return {
                "source": "todos",
                "data": {},
                "metadata": {"error": "job_id required for 'todos' category"},
            }
        kwargs["job_id"] = job_id
        kwargs["tenant_key"] = tenant_key

    else:
        kwargs["product_id"] = product_id
        kwargs["tenant_key"] = tenant_key

    return await tool_func(**kwargs)
