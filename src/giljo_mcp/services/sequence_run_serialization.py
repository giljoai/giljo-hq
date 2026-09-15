# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.models.sequence_runs import SequenceRun


def serialize_sequence_run(run: SequenceRun) -> dict[str, Any]:
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
        "reviewed_project_ids": run.reviewed_project_ids or [],
        "reviewed_via": run.reviewed_via or {},
        "chain_mission": run.chain_mission,
        "conductor_agent_id": run.conductor_agent_id,
        "conductor_project_id": run.conductor_project_id,
        "conductor_label": run.conductor_label,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
