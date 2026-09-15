# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any, NoReturn

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.roadmaps import (
    MAX_BLOCKED_REASON_LEN,
    MAX_ROADMAP_SORT_ORDER,
    VALID_ROADMAP_COMPLEXITIES,
    VALID_ROADMAP_ITEM_TYPES,
    VALID_ROADMAP_RISKS,
)


PATCHABLE_ITEM_FIELDS: tuple[str, ...] = (
    "sort_order",
    "risk",
    "complexity",
    "blocked",
    "blocked_reason",
)

PATCH_FIELDS_KEY: str = "_patch_fields"


MAX_ROADMAP_REF_LEN: int = 64


def format_missing_refusal(
    *,
    noun: str,
    elsewhere: list[str],
    unknown: list[str],
    active_label: str,
) -> str:
    parts: list[str] = []
    if elsewhere:
        parts.append(
            f"{noun}(s) {sorted(elsewhere)} belong to a different product, not the active product "
            f"{active_label} -- a roadmap only holds items of its own product, so activate theirs "
            f"or leave them off this one"
        )
    if unknown:
        parts.append(f"{noun}(s) {sorted(unknown)} do not exist in this workspace")
    return "; ".join(parts)




def _fail(field: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"field": field, "message": message, **extra}


def raise_roadmap_failures(failures: list[dict[str, Any]], *, operation: str) -> NoReturn:
    primary = failures[0]
    message = primary["message"]
    if len(failures) > 1:
        message = " || ".join([message] + [f"ALSO FAILED: {f['message']}" for f in failures[1:]])

    context: dict[str, Any] = {"operation": operation}
    context.update({k: v for k, v in primary.items() if k not in ("field", "message")})
    if len(failures) > 1:
        context["all_failures"] = failures
    raise ValidationError(message=message, context=context)




def _check_sort_order(value: Any, idx: int) -> tuple[int, list[dict[str, Any]]]:
    field = f"items[{idx}].sort_order"
    if isinstance(value, bool) or not isinstance(value, int):
        return 0, [_fail(field, f"{field} must be an integer")]
    if value < 0 or value > MAX_ROADMAP_SORT_ORDER:
        return 0, [
            _fail(
                field,
                f"{field} must be between 0 and {MAX_ROADMAP_SORT_ORDER}",
                max_sort_order=MAX_ROADMAP_SORT_ORDER,
            )
        ]
    return value, []


def validate_sort_order(value: Any, idx: int) -> int:
    sort_order, failures = _check_sort_order(value, idx)
    if failures:
        raise_roadmap_failures(failures, operation="upsert_roadmap_items")
    return sort_order


def _check_blocked(blocked: Any, blocked_reason: Any, idx: int) -> tuple[bool, str | None, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []

    if blocked is None:
        blocked_bool = False
    elif isinstance(blocked, bool):
        blocked_bool = blocked
    else:
        blocked_bool = False
        failures.append(_fail(f"items[{idx}].blocked", f"items[{idx}].blocked must be a boolean"))

    reason = blocked_reason if blocked_reason not in (None, "") else None
    if reason is not None and not isinstance(reason, str):
        failures.append(_fail(f"items[{idx}].blocked_reason", f"items[{idx}].blocked_reason must be a string"))
        reason = None
    reason = reason.strip() or None if reason is not None else None
    if reason is not None and len(reason) > MAX_BLOCKED_REASON_LEN:
        failures.append(
            _fail(
                f"items[{idx}].blocked_reason",
                f"items[{idx}].blocked_reason exceeds {MAX_BLOCKED_REASON_LEN} characters (got {len(reason)})",
                max_blocked_reason_len=MAX_BLOCKED_REASON_LEN,
                actual_len=len(reason),
            )
        )
        reason = None

    return blocked_bool, (reason if blocked_bool else None), failures


def validate_blocked(blocked: Any, blocked_reason: Any, idx: int) -> tuple[bool, str | None]:
    blocked_bool, reason, failures = _check_blocked(blocked, blocked_reason, idx)
    if failures:
        raise_roadmap_failures(failures, operation="upsert_roadmap_items")
    return blocked_bool, reason


def _check_ref(value: Any, field: str) -> list[dict[str, Any]]:
    coerced = str(value)
    if len(coerced) > MAX_ROADMAP_REF_LEN:
        return [
            _fail(
                field,
                f"{field} exceeds {MAX_ROADMAP_REF_LEN} characters (got {len(coerced)})",
                max_ref_len=MAX_ROADMAP_REF_LEN,
                actual_len=len(coerced),
            )
        ]
    return []




def _check_patch_pairing(raw: dict[str, Any], idx: int) -> list[dict[str, Any]]:
    has_blocked = "blocked" in raw
    has_reason = "blocked_reason" in raw
    if has_blocked == has_reason:
        return []

    supplied, missing = ("blocked_reason", "blocked") if has_reason else ("blocked", "blocked_reason")
    return [
        _fail(
            f"items[{idx}].{supplied}",
            f"items[{idx}].{supplied} needs items[{idx}].{missing} in the same item when patch_fields is on -- "
            f"the block state and its note are patched together (send both, or neither)",
            patch_fields_pair=["blocked", "blocked_reason"],
        )
    ]


def _check_item(
    raw: Any, idx: int, *, patch_fields: bool = False
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        return None, [_fail(f"items[{idx}]", f"items[{idx}] must be an object")]

    failures: list[dict[str, Any]] = []
    if patch_fields:
        failures.extend(_check_patch_pairing(raw, idx))

    item_type = raw.get("item_type")
    if item_type not in VALID_ROADMAP_ITEM_TYPES:
        failures.append(
            _fail(
                f"items[{idx}].item_type",
                f"items[{idx}].item_type '{item_type}' invalid. Valid: {sorted(VALID_ROADMAP_ITEM_TYPES)}",
                valid_item_types=sorted(VALID_ROADMAP_ITEM_TYPES),
            )
        )
        item_type = None

    project_id = raw.get("project_id") or None
    task_id = raw.get("task_id") or None
    if item_type == "project":
        if not project_id:
            failures.append(_fail(f"items[{idx}].project_id", f"items[{idx}] item_type=project requires project_id"))
        else:
            failures.extend(_check_ref(project_id, f"items[{idx}].project_id"))
        task_id = None
    elif item_type == "task":
        if not task_id:
            failures.append(_fail(f"items[{idx}].task_id", f"items[{idx}] item_type=task requires task_id"))
        else:
            failures.extend(_check_ref(task_id, f"items[{idx}].task_id"))
        project_id = None

    sort_order, sort_failures = _check_sort_order(raw.get("sort_order", 0), idx)
    failures.extend(sort_failures)

    risk = raw.get("risk") or None
    if risk is not None and risk not in VALID_ROADMAP_RISKS:
        failures.append(
            _fail(
                f"items[{idx}].risk",
                f"items[{idx}].risk '{risk}' invalid. Valid: {sorted(VALID_ROADMAP_RISKS)}",
                valid_risks=sorted(VALID_ROADMAP_RISKS),
            )
        )

    complexity = raw.get("complexity") or None
    if complexity is not None and complexity not in VALID_ROADMAP_COMPLEXITIES:
        failures.append(
            _fail(
                f"items[{idx}].complexity",
                f"items[{idx}].complexity '{complexity}' invalid. Valid: {sorted(VALID_ROADMAP_COMPLEXITIES)}",
                valid_complexities=sorted(VALID_ROADMAP_COMPLEXITIES),
            )
        )

    blocked, blocked_reason, blocked_failures = _check_blocked(raw.get("blocked"), raw.get("blocked_reason"), idx)
    failures.extend(blocked_failures)

    if failures:
        return None, failures

    row = {
        "item_type": item_type,
        "project_id": str(project_id) if project_id else None,
        "task_id": str(task_id) if task_id else None,
        "sort_order": sort_order,
        "risk": risk,
        "complexity": complexity,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
    }
    if patch_fields:
        row[PATCH_FIELDS_KEY] = frozenset(f for f in PATCHABLE_ITEM_FIELDS if f in raw)
    return row, []


def collect_items(items: Any, *, patch_fields: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(items, list):
        return [], [_fail("items", "items must be a list of roadmap-item objects")]

    normalized: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for idx, raw in enumerate(items):
        row, row_failures = _check_item(raw, idx, patch_fields=patch_fields)
        if row_failures:
            failures.extend(row_failures)
        else:
            normalized.append(row)
    return normalized, failures


def validate_items(items: Any, *, patch_fields: bool = False) -> list[dict[str, Any]]:
    normalized, failures = collect_items(items, patch_fields=patch_fields)
    if failures:
        raise_roadmap_failures(failures, operation="upsert_roadmap_items")
    return normalized




def validate_reorder(updates: Any) -> list[dict[str, Any]]:
    if not isinstance(updates, list):
        raise ValidationError(
            message="items must be a list of {id, sort_order} objects",
            context={"operation": "reorder_roadmap"},
        )
    normalized: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for idx, raw in enumerate(updates):
        if not isinstance(raw, dict) or not raw.get("id"):
            failures.append(_fail(f"items[{idx}]", f"items[{idx}] must be an object with a non-empty id"))
            continue
        sort_order, sort_failures = _check_sort_order(raw.get("sort_order", 0), idx)
        if sort_failures:
            failures.extend(sort_failures)
            continue
        normalized.append({"id": str(raw["id"]), "sort_order": sort_order})
    if failures:
        raise_roadmap_failures(failures, operation="reorder_roadmap")
    return normalized


def _check_remove_ref(raw: Any, idx: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        return None, [_fail(f"remove[{idx}]", f"remove[{idx}] must be an object")]

    failures: list[dict[str, Any]] = []
    item_type = raw.get("item_type")
    if item_type not in VALID_ROADMAP_ITEM_TYPES:
        failures.append(
            _fail(
                f"remove[{idx}].item_type",
                f"remove[{idx}].item_type '{item_type}' invalid. Valid: {sorted(VALID_ROADMAP_ITEM_TYPES)}",
                valid_item_types=sorted(VALID_ROADMAP_ITEM_TYPES),
            )
        )
        item_type = None

    project_id = raw.get("project_id") or None
    task_id = raw.get("task_id") or None
    if item_type == "project":
        if not project_id:
            failures.append(_fail(f"remove[{idx}].project_id", f"remove[{idx}] item_type=project requires project_id"))
        else:
            failures.extend(_check_ref(project_id, f"remove[{idx}].project_id"))
        task_id = None
    elif item_type == "task":
        if not task_id:
            failures.append(_fail(f"remove[{idx}].task_id", f"remove[{idx}] item_type=task requires task_id"))
        else:
            failures.extend(_check_ref(task_id, f"remove[{idx}].task_id"))
        project_id = None

    if failures:
        return None, failures
    return {
        "item_type": item_type,
        "project_id": str(project_id) if project_id else None,
        "task_id": str(task_id) if task_id else None,
    }, []


def collect_remove(remove: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if remove is None:
        return [], []
    if not isinstance(remove, list):
        return [], [_fail("remove", "remove must be a list of {item_type, project_id|task_id} objects")]

    normalized: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for idx, raw in enumerate(remove):
        ref, ref_failures = _check_remove_ref(raw, idx)
        if ref_failures:
            failures.extend(ref_failures)
        else:
            normalized.append(ref)
    return normalized, failures


def validate_remove(remove: Any) -> list[dict[str, Any]]:
    normalized, failures = collect_remove(remove)
    if failures:
        raise_roadmap_failures(failures, operation="remove_roadmap_items")
    return normalized


def validate_upsert_payload(
    items: Any, remove: Any, *, patch_fields: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_items, item_failures = collect_items(items, patch_fields=patch_fields)
    normalized_remove, remove_failures = collect_remove(remove)
    failures = item_failures + remove_failures
    if failures:
        raise_roadmap_failures(failures, operation="upsert_roadmap_items")
    return normalized_items, normalized_remove
