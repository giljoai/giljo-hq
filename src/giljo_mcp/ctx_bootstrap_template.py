# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Iterable
from typing import Any


__all__ = ["CTX_BOOTSTRAP_TEMPLATE", "render_ctx_bootstrap"]


CTX_BOOTSTRAP_TEMPLATE = """\
You are running a Context Update (CTX) project for product {{product_name}} (id: {{product_id}}).

Goal: refresh the consolidated vision aggregates so they reflect the current
set of vision documents. The orchestrator may self-close instantly if the
derived vision_inputs_hash already matches the persisted
consolidated_vision_hash -- the platform will signal that via a
staging_directive.action == "SELF_CLOSE" payload on
get_staging_instructions.

Current state:
- product_name: {{product_name}}
- product_id: {{product_id}}
- consolidated_vision_hash (persisted): {{consolidated_vision_hash}}
- vision_inputs_hash (derived at launch): {{vision_inputs_hash}}

New documents in this update:
{{new_documents_block}}

If the platform did NOT self-close this orchestrator, run the consolidation
flow: fetch each active vision document, regenerate the light/medium
aggregates via update_product_context, then close out with a project_closeout
360 memory entry citing the new hash."""


_BULLET = "- "
_NONE = "(none)"


def _format_documents(new_documents: Iterable[dict[str, Any]] | None) -> str:
    if not new_documents:
        return _NONE
    lines: list[str] = []
    for doc in new_documents:
        name = str(doc.get("document_name") or doc.get("name") or "unnamed")
        doc_type = str(doc.get("document_type") or doc.get("type") or "vision")
        lines.append(f"{_BULLET}{name} ({doc_type})")
    if not lines:
        return _NONE
    return "\n".join(lines)


def render_ctx_bootstrap(
    *,
    product_id: str,
    product_name: str,
    consolidated_vision_hash: str | None,
    vision_inputs_hash: str,
    new_documents: Iterable[dict[str, Any]] | None = None,
) -> str:
    substitutions = {
        "{{product_id}}": str(product_id),
        "{{product_name}}": product_name,
        "{{consolidated_vision_hash}}": consolidated_vision_hash or "(unset)",
        "{{vision_inputs_hash}}": vision_inputs_hash,
        "{{new_documents_block}}": _format_documents(new_documents),
    }
    rendered = CTX_BOOTSTRAP_TEMPLATE
    for placeholder, value in substitutions.items():
        rendered = rendered.replace(placeholder, value)
    return rendered
