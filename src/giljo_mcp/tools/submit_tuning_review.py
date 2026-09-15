# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from giljo_mcp.database import DatabaseManager
from giljo_mcp.services.product_tuning_service import ProductTuningService


logger = logging.getLogger(__name__)

VALID_SECTIONS = {
    "description",
    "tech_stack",
    "tech_stack.backend_frameworks",
    "tech_stack.frontend_frameworks",
    "tech_stack.programming_languages",
    "tech_stack.databases_storage",
    "tech_stack.infrastructure",
    "tech_stack.dev_tools",
    "architecture",
    "architecture.primary_pattern",
    "architecture.design_patterns",
    "architecture.api_style",
    "architecture.architecture_notes",
    "architecture.coding_conventions",
    "core_features",
    "brand_guidelines",
    "quality_standards",
    "target_platforms",
}

VALID_CONFIDENCE_LEVELS = {"high", "medium", "low"}


def _validate_proposals(proposals: list[dict[str, Any]]) -> list[str]:
    errors = []

    if not proposals:
        errors.append("proposals array must not be empty")
        return errors

    for i, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            errors.append(f"proposals[{i}]: must be an object")
            continue

        section = proposal.get("section")
        if not section or section not in VALID_SECTIONS:
            errors.append(f"proposals[{i}]: invalid section '{section}', must be one of {sorted(VALID_SECTIONS)}")

        if "drift_detected" not in proposal:
            errors.append(f"proposals[{i}]: missing required field 'drift_detected'")

        confidence = proposal.get("confidence")
        if confidence and confidence not in VALID_CONFIDENCE_LEVELS:
            errors.append(f"proposals[{i}]: invalid confidence '{confidence}', must be high/medium/low")

        proposed_value = proposal.get("proposed_value")
        if proposed_value is not None:
            if not isinstance(proposed_value, (str, dict, list)):
                errors.append(
                    f"proposals[{i}]: proposed_value must be a string, object, or array, "
                    f"got {type(proposed_value).__name__}"
                )
            elif isinstance(proposed_value, str) and len(proposed_value) > 10000:
                errors.append(
                    f"proposals[{i}]: proposed_value string exceeds 10000 character limit ({len(proposed_value)} chars)"
                )
            elif isinstance(proposed_value, list) and section == "target_platforms":
                for j, item in enumerate(proposed_value):
                    if not isinstance(item, str):
                        errors.append(
                            f"proposals[{i}]: proposed_value[{j}] must be a string for "
                            f"target_platforms, got {type(item).__name__}"
                        )

    return errors


async def submit_tuning_review(
    product_id: str,
    tenant_key: str,
    proposals: list[dict[str, Any]],
    overall_summary: str | None = None,
    force: bool = False,
    db_manager: DatabaseManager | None = None,
    websocket_manager: Any = None,
) -> dict[str, Any]:
    if not db_manager:
        raise ValueError("db_manager is required")

    errors = _validate_proposals(proposals)
    if errors:
        raise ValueError(f"Invalid proposals: {'; '.join(errors)}")

    service = ProductTuningService(
        db_manager=db_manager,
        tenant_key=tenant_key,
        websocket_manager=websocket_manager,
    )

    return await service.apply_tuning_updates(
        product_id=product_id,
        proposals=proposals,
        overall_summary=overall_summary,
        force=force,
    )
