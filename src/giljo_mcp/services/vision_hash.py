# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any


__all__ = [
    "VISION_INPUTS_HASH_EMPTY",
    "build_vision_aggregate",
    "compute_vision_inputs_hash",
    "vision_inputs_hash_matches_consolidated",
]

VISION_INPUTS_HASH_EMPTY = "sha256:empty"
_PREFIX = "sha256:"


def _active_sorted_docs(vision_documents: Iterable[Any] | None) -> list[Any]:
    if not vision_documents:
        return []
    active = [
        doc for doc in vision_documents if getattr(doc, "is_active", True) and getattr(doc, "deleted_at", None) is None
    ]
    return sorted(active, key=lambda d: getattr(d, "display_order", 0))


def build_vision_aggregate(
    vision_documents: Iterable[Any] | None,
) -> tuple[str, list[Any], str]:
    sorted_docs = _active_sorted_docs(vision_documents)
    if not sorted_docs:
        return "", [], ""

    parts: list[str] = []
    source_doc_ids: list[Any] = []
    for doc in sorted_docs:
        name = getattr(doc, "document_name", "") or ""
        body = getattr(doc, "vision_document", "") or ""
        parts.append(f"# {name}\n\n{body}")
        source_doc_ids.append(getattr(doc, "id", None) if hasattr(doc, "id") else name)

    aggregate_text = "\n\n".join(parts)
    raw_hex = hashlib.sha256(aggregate_text.encode("utf-8")).hexdigest()
    return aggregate_text, source_doc_ids, raw_hex


def compute_vision_inputs_hash(vision_documents: Iterable[Any] | None) -> str:
    _aggregate_text, _ids, raw_hex = build_vision_aggregate(vision_documents)
    if not raw_hex:
        return VISION_INPUTS_HASH_EMPTY
    return f"{_PREFIX}{raw_hex}"


def vision_inputs_hash_matches_consolidated(
    vision_inputs_hash: str | None,
    consolidated_vision_hash: str | None,
) -> bool:
    if not vision_inputs_hash or not consolidated_vision_hash:
        return False
    if vision_inputs_hash == VISION_INPUTS_HASH_EMPTY:
        return False
    if not vision_inputs_hash.startswith(_PREFIX):
        return vision_inputs_hash == consolidated_vision_hash
    return vision_inputs_hash[len(_PREFIX) :] == consolidated_vision_hash
