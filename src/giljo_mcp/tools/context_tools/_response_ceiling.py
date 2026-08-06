# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Response-size ceiling for the unified context fetcher.

BE-9322: moved verbatim out of fetch_context.py, which sat at 799 lines
against the flat 800-line CI cap with no shrink-only budget entry. The block
is a pure post-processing pass over an already-assembled response -- it has
no coupling to category dispatch, the database, or tenancy -- so it is a
genuine module boundary rather than a split made to satisfy a number.
"""

from typing import Any


# INF-WriteShape: 30K-char ceiling -- single safety net when the assembled
# response would otherwise blow an agent's context budget. Strategy:
#   1. Iterate categories largest -> smallest by serialized size.
#   2. Within each, drop the largest droppable field of the largest entry.
#   3. Mark the affected entry with truncated:true.
#   4. Loop until under cap or only protected fields remain.
# Hard floor: NEVER drop required identity fields.
RESPONSE_CHAR_CEILING = 30_000
PROTECTED_ENTRY_FIELDS = frozenset({"id", "sequence", "project_name", "type", "timestamp"})


def _serialized_size(obj: Any) -> int:
    import json

    return len(json.dumps(obj))


def _apply_response_ceiling(response: dict[str, Any]) -> dict[str, Any]:
    """Iteratively drop the largest droppable field until response <= cap."""
    if _serialized_size(response) <= RESPONSE_CHAR_CEILING:
        return response

    data = response.get("data")
    if not isinstance(data, dict):
        return response

    truncation_applied = False
    # Bound the loop so a degenerate payload can't spin forever.
    for _ in range(2000):
        if _serialized_size(response) <= RESPONSE_CHAR_CEILING:
            break

        # Find largest category by serialized size
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
            # Cannot drop fields out of a non-list category structure safely
            break

        # Find largest entry in that category
        largest_idx = max(range(len(cat_data)), key=lambda i: _serialized_size(cat_data[i]))
        entry = cat_data[largest_idx]
        if not isinstance(entry, dict):
            break

        # Find largest droppable field in that entry
        # Skip 'truncated' (legacy field-drop signal we set ourselves below) and
        # 'has_full_body' (BE-5031 headlines-shape flag that survives ceiling).
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
