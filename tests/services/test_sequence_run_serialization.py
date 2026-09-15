# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_serialization import serialize_sequence_run


def test_serialize_sequence_run_shape() -> None:
    run = SequenceRun(
        id="run-1",
        tenant_key="tk_test",
        project_ids=["p1", "p2"],
        resolved_order=["p1", "p2"],
        current_index=0,
        execution_mode="multi_terminal",
        status="pending",
        review_policy="per_card",
        project_statuses={"p1": "pending", "p2": "pending"},
        chain_mission="cross-project chain plan",
        conductor_agent_id="agent-conductor",
        conductor_project_id=None,
        conductor_label=None,
    )

    out = serialize_sequence_run(run)

    expected_keys = {
        "id",
        "tenant_key",
        "project_ids",
        "resolved_order",
        "current_index",
        "execution_mode",
        "status",
        "review_policy",
        "locked",
        "project_statuses",
        "reviewed_project_ids",
        "reviewed_via",
        "chain_mission",
        "conductor_agent_id",
        "conductor_project_id",
        "conductor_label",
        "created_at",
        "updated_at",
    }
    assert set(out.keys()) == expected_keys

    assert out["id"] == "run-1"
    assert out["project_ids"] == ["p1", "p2"]
    assert out["chain_mission"] == "cross-project chain plan"
    assert out["conductor_agent_id"] == "agent-conductor"
    assert out["conductor_project_id"] is None
    assert out["reviewed_project_ids"] == []
    assert out["reviewed_via"] == {}
    assert out["created_at"] is None
    assert out["updated_at"] is None
