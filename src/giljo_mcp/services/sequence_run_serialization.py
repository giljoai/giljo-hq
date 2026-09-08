# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SequenceRun serialization helper (extracted from sequence_run_service.py).

Pure mapping from a ``SequenceRun`` ORM row to its wire dict. Extracted to keep
``sequence_run_service.py`` under the 800-line CI guardrail (BE-6184). Internal;
not part of the public API surface; the owning service re-exports it.

Edition Scope: CE.
"""

from __future__ import annotations

from typing import Any

from giljo_mcp.models.sequence_runs import SequenceRun


def serialize_sequence_run(run: SequenceRun) -> dict[str, Any]:
    """Return the wire dict for a SequenceRun row."""
    return {
        "id": run.id,
        "tenant_key": run.tenant_key,
        "project_ids": run.project_ids,
        "resolved_order": run.resolved_order,
        "current_index": run.current_index,
        "execution_mode": run.execution_mode,
        "status": run.status,
        "review_policy": run.review_policy,
        "locked": run.locked,
        "project_statuses": run.project_statuses,
        # BE-9098: durable per-member review acknowledgment (drives the FE badge
        # persistence). Defaults to [] so pre-column rows serialize cleanly.
        "reviewed_project_ids": run.reviewed_project_ids or [],
        # BE-9540: per-member review provenance ({project_id -> "ui" | "harness"}).
        # Defaults to {} so pre-column rows serialize cleanly.
        "reviewed_via": run.reviewed_via or {},
        "chain_mission": run.chain_mission,
        "conductor_agent_id": run.conductor_agent_id,
        "conductor_project_id": run.conductor_project_id,
        "conductor_label": run.conductor_label,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
