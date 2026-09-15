# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any


RESPONSE_CHAR_CEILING = 30_000
PROTECTED_ENTRY_FIELDS = frozenset({"id", "sequence", "project_name", "type", "timestamp"})


def _serialized_size(obj: Any) -> int:
    import json

    return len(json.dumps(obj))


def _apply_response_ceiling(response: dict[str, Any]) -> dict[str, Any]:
    if _serialized_size(response) <= RESPONSE_CHAR_CEILING:
        return response

    data = response.get("data")
    if not isinstance(data, dict):
        return response

    truncation_applied = False
    for _ in range(2000):
        if _serialized_size(response) <= RESPONSE_CHAR_CEILING:
            break

        target_category = None
        target_size = -1
        for cat, cat_data in data.items():
            size = _serialized_size(cat_data)
            if size > target_size:
                target_size = size
                target_category = cat

        if target_category is None:
            break

        cat_data = data[target_category]
        if not (isinstance(cat_data, list) and cat_data):
            break

        largest_idx = max(range(len(cat_data)), key=lambda i: _serialized_size(cat_data[i]))
        entry = cat_data[largest_idx]
        if not isinstance(entry, dict):
            break

        droppable = [
            (k, _serialized_size(v))
            for k, v in entry.items()
            if k not in PROTECTED_ENTRY_FIELDS and k not in ("truncated", "has_full_body")
        ]
        if not droppable:
            break

        droppable.sort(key=lambda kv: kv[1], reverse=True)
        field_to_drop, _ = droppable[0]
        entry.pop(field_to_drop, None)
        entry["truncated"] = True
        truncation_applied = True

    if truncation_applied:
        meta = response.setdefault("metadata", {})
        meta["truncation_applied"] = True
        meta["truncation_reason"] = "30K char ceiling"

    return response
