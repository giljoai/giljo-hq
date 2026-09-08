# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Filter/projection input resolution for ``list_tasks_for_mcp`` (BE-9469/BE-9470).

Split OUT of ``_mcp_read_layer.py`` under BE-9470: that module sits at 838 lines
against the 800-line cap after finding 4's ``resolve_list_mode`` rewrite and
finding 5's new ``validate_task_type_filter`` -- both filter-input concerns, not
bounds/projection concerns. Splitting this way mirrors why ``_mcp_read_layer.py``
itself was split out of ``_mcp_adapter_mixin.py`` in the first place (BE-9468):
grow the surface, split the file, never raise the cap. Nothing here changes
behavior; it is the same functions, moved, plus the genuinely new BE-9470 logic
they were extracted alongside.

Edition Scope: Both.
"""

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
    """Resolve the projection mode from ``mode`` + the legacy ``summary_only`` flag.

    BE-9470: copied verbatim from ``list_projects``'s ``_resolve_projection_mode``
    (``project_service/_mcp_adapter_query_mixin.py``) -- an explicit ``mode`` WINS over
    ``summary_only``, never the reverse. Before this fix ``summary_only`` won
    unconditionally, so ``mode='index', summary_only=True`` silently returned a
    'summary' row (the caller's explicit mode discarded) and ``mode='full',
    memory_limit=40, summary_only=True`` discarded BOTH ``mode`` and ``memory_limit``
    (measured: BE-9470 finding 4 / QA unit U69-F1).

    ``mode is None`` is the caller-omitted-mode case (the @mcp.tool wrapper forwards
    ``None`` when its own ``mode`` parameter is left at its wire default, mirroring
    ``list_projects``'s ``mode or None``) -- ONLY then does ``summary_only`` still
    apply, which is what keeps every caller who passes ONLY ``summary_only``
    byte-identical to the shipped pre-mode behaviour: ``True`` means the summary
    projection, ``False`` means the full one, ``None`` (neither passed) defaults to
    'summary'.
    """
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
    """Resolve the effective row limit, rejecting an out-of-range one. Extracted, unchanged.

    ``0`` means "use the default", matching ``list_projects_for_mcp`` -- the MCP-tool schema
    was widened from ``ge=1`` to ``ge=0`` for the same reason (BE-9468 QA followup).

    Note this REJECTS out-of-range rather than clamping, unlike the project list. The two
    differ deliberately and the difference is shipped behaviour on both surfaces; it is not
    reconciled here, only moved.
    """
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


# BE-9469: no domain SSoT for task priority (models/tasks.py:107 is a bare
# VARCHAR + comment); mirrors the write-side Literal (create_task/update_task).
_VALID_TASK_PRIORITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})


def validate_task_status_filter(status: str | None) -> None:
    """BE-9469: mirror the WRITE-path status check onto the read path -- a
    typo'd status used to return matched:0 beside a nonzero counts.by_status
    for that same status in the same response. Extracted so
    list_tasks_for_mcp stays under the 200-line cap."""
    if status is None or status in VALID_TASK_STATUSES:
        return
    valid = sorted(s.value for s in VALID_TASK_STATUSES)
    raise ValidationError(
        message=f"Unknown task status '{status}'. Valid statuses: {valid}",
        context={"operation": "list_tasks_for_mcp", "valid_statuses": valid},
    )


def validate_task_type_filter(task_type: str | None) -> str | None:
    """BE-9470 (finding 5): ``task_type`` has exactly ONE value that can ever match a
    task -- ``RESERVED_TASK_TYPE_ABBR`` ('TSK', BE-6049c) -- because every task is
    force-assigned it on create and the type is immutable on update
    (``_mutation_mixin.py``). A real project-taxonomy abbreviation (e.g. 'BE') and a
    typo both structurally cannot match a single task row, so both are refused the
    same way: measured (QA U67-F1), all 11 non-reserved types matched zero rows each
    while the reserved value 'TSK' -- the one value that matches all of them -- was
    refused as reserved. That refusal protected task_type on the WRITE path
    (create_type/label-resolution); a READ filter matching every row is harmless, so
    'TSK' is admitted here instead (mirrors the shipped precedent already applied to
    ``list_projects.project_type``, ``_mcp_adapter_query_mixin.py`` -- TSK added to
    ITS valid set for the same reason). The U61 precedent governs everything else: a
    value that structurally cannot match says so instead of answering matched:0 next
    to a nonzero ``counts.by_type`` for a different key in the same response.

    Returns the normalized value (currently always ``RESERVED_TASK_TYPE_ABBR``) or
    ``None`` when the caller passed no filter. Extracted so list_tasks_for_mcp stays
    under the 200-line cap, mirroring ``validate_task_status_filter`` next door.
    """
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
    """The product lookup ``list_tasks_for_mcp`` scopes every query to.

    BE-9470: extracted verbatim out of ``list_tasks_for_mcp`` (behavior unchanged,
    just moved) to keep that function AND ``_mcp_adapter_mixin.py`` under their
    line caps. BE-6077: without this, an agent "on the active product" saw the
    whole tenant's task corpus instead of the active product's, diverging from
    both the UI and ``list_projects_for_mcp`` (Tasks are NOT NULL ``product_id``,
    ``models/tasks.py``).

    BE-9499a: ``product_id`` is optional. Omitted, this resolves the active
    product exactly as before. Supplied, it is validated as belonging to this
    tenant via ``ProductService.resolve_binding_product`` and used regardless
    of which product is active -- never a silent fallback.
    """
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
    """Resolve ``task_type`` to the taxonomy row id the SQL filter needs, or ``None``.

    BE-9470: extracted out of ``list_tasks_for_mcp`` (kept that function, and this
    module, under their line caps) rather than left inline -- the DB lookup is a
    self-contained unit once ``validate_task_type_filter`` has decided the value is
    admissible. ``allow_reserved=True`` skips ONLY the write-path reserved-tag
    refusal inside ``TaxonomyService.validate``; the row lookup that follows still
    resolves the real TSK row, so the filter matches on an actual ``task_type_id``
    rather than being waved through as a no-op.
    """
    if not task_type:
        return None
    normalized_task_type = validate_task_type_filter(task_type)
    from giljo_mcp.services.taxonomy_service import TaxonomyService

    taxonomy = TaxonomyService(db_manager=db_manager, session=session)
    resolved = await taxonomy.validate(normalized_task_type, tenant_key, allow_reserved=True)
    return resolved.id


def normalize_task_priority_filter(priority: str | None) -> str | None:
    """BE-9469: normalize-then-validate -- 'Medium' vs 'medium' measured 86
    tasks apart with no error. Priority is never case-significant here (DB
    only stores the lowercase write-side Literal), so normalizing has zero
    ambiguity cost. Extracted so list_tasks_for_mcp stays under the 200-line
    cap."""
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
    """Resolve list_tasks' row limit, status/priority filters, and cursor state (BE-9499a extraction).

    Split out of ``list_tasks_for_mcp`` (same pattern as its neighbours in
    this module) to keep that function -- and ``_mcp_adapter_mixin.py`` --
    inside their length/size budgets. Behavior unchanged. ``mode`` and
    ``task_type_id`` are resolved by the CALLER via ``resolve_list_mode`` /
    ``resolve_task_type_id`` directly (test_be9060_task_service_split pins
    the mixin importing those two by name), not here.
    """
    effective_limit = resolve_task_limit(limit)

    # BE-9469: see _mcp_read_layer's validators -- a typo'd status/priority
    # used to return matched:0 silently instead of refusing.
    validate_task_status_filter(status)
    priority = normalize_task_priority_filter(priority)

    # BE-9469: fingerprint and incoming position resolved together, BEFORE the fetch
    # so a refused token costs no query. Fingerprinted from RESOLVED values --
    # task_type_id, not the caller's abbreviation -- so two spellings of one type do
    # not refuse each other's cursors. See open_task_cursor_walk.
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
