# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.domain.task_status import VALID_TASK_STATUSES
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.task_service._mcp_read_layer import (
    LIST_TASKS_LIMIT_DEFAULT,
    LIST_TASKS_LIMIT_MAX,
    open_task_cursor_walk,
)
from giljo_mcp.services.taxonomy_ops import RESERVED_TASK_TYPE_ABBR


def resolve_list_mode(mode: str | None, summary_only: bool | None, valid_modes: Any) -> str:
    if mode is None:
        if summary_only is True:
            mode = "summary"
        elif summary_only is False:
            mode = "full"
        else:
            mode = "summary"
    if mode not in valid_modes:
        raise ValidationError(
            message=f"Unknown mode '{mode}'. Valid modes: {', '.join(valid_modes)}",
            context={"operation": "list_tasks_for_mcp", "mode": mode},
        )
    return mode


def resolve_task_limit(limit: Any) -> int:
    effective_limit = LIST_TASKS_LIMIT_DEFAULT if not limit else int(limit)
    if effective_limit < 1 or effective_limit > LIST_TASKS_LIMIT_MAX:
        raise ValidationError(
            message=(
                f"limit must be between 1 and {LIST_TASKS_LIMIT_MAX} "
                f"(default {LIST_TASKS_LIMIT_DEFAULT}); got {effective_limit}."
            ),
            context={"operation": "list_tasks_for_mcp", "limit": effective_limit},
        )
    return effective_limit


_VALID_TASK_PRIORITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})


def validate_task_status_filter(status: str | None) -> None:
    if status is None or status in VALID_TASK_STATUSES:
        return
    valid = sorted(s.value for s in VALID_TASK_STATUSES)
    raise ValidationError(
        message=f"Unknown task status '{status}'. Valid statuses: {valid}",
        context={"operation": "list_tasks_for_mcp", "valid_statuses": valid},
    )


def validate_task_type_filter(task_type: str | None) -> str | None:
    if task_type is None:
        return None
    normalized = task_type.strip()
    if normalized != RESERVED_TASK_TYPE_ABBR:
        raise ValidationError(
            message=(
                f"Invalid task_type '{normalized}'. Valid types: {RESERVED_TASK_TYPE_ABBR} -- "
                f"every task is tagged '{RESERVED_TASK_TYPE_ABBR}' (BE-6049c); no other value "
                "can ever match a task."
            ),
            context={"operation": "list_tasks_for_mcp", "task_type": normalized},
        )
    return normalized


async def resolve_active_product_for_list_tasks(
    *, db_manager: Any, websocket_manager: Any, session: Any, tenant_key: str, product_id: str | None = None
) -> Any:
    from giljo_mcp.services.product_service import ProductService

    product_service = ProductService(
        db_manager=db_manager,
        tenant_key=tenant_key,
        websocket_manager=websocket_manager,
        test_session=session,
    )
    return await product_service.resolve_binding_product(
        product_id, operation="list_tasks_for_mcp", action="listed", write=False
    )


async def resolve_task_type_id(task_type: str | None, *, db_manager: Any, session: Any, tenant_key: str) -> str | None:
    if not task_type:
        return None
    normalized_task_type = validate_task_type_filter(task_type)
    from giljo_mcp.services.taxonomy_service import TaxonomyService

    taxonomy = TaxonomyService(db_manager=db_manager, session=session)
    resolved = await taxonomy.validate(normalized_task_type, tenant_key, allow_reserved=True)
    return resolved.id


def normalize_task_priority_filter(priority: str | None) -> str | None:
    if priority is None:
        return None
    priority = priority.strip().lower()
    if priority in _VALID_TASK_PRIORITIES:
        return priority
    valid = sorted(_VALID_TASK_PRIORITIES)
    raise ValidationError(
        message=f"Unknown task priority '{priority}'. Valid priorities: {valid}",
        context={"operation": "list_tasks_for_mcp", "valid_priorities": valid},
    )


def resolve_list_tasks_filters_and_cursor(
    *,
    limit: int | None,
    status: str | None,
    priority: str | None,
    task_type_id: str | None,
    due_before: Any,
    hidden: bool | None,
    query: str | None,
    cursor: str | None,
    product_id: str,
) -> tuple[int, str | None, str | None, str | None]:
    effective_limit = resolve_task_limit(limit)

    validate_task_status_filter(status)
    priority = normalize_task_priority_filter(priority)

    cursor_fingerprint, after_key = open_task_cursor_walk(
        cursor,
        product_id=product_id,
        status=status,
        priority=priority,
        task_type_id=task_type_id,
        due_before=due_before,
        hidden=hidden,
        query=query,
    )
    return effective_limit, priority, cursor_fingerprint, after_key
