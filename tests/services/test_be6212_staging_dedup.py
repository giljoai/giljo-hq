# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.services.sequence_chain_context import ChainContext


def _ctx(*, chain_ctx: ChainContext | None) -> dict:
    return {
        "execution": SimpleNamespace(project_phase="staging", agent_id="a1", status="waiting"),
        "agent_job": SimpleNamespace(mission="project mission"),
        "project": SimpleNamespace(
            id="p2",
            name="P2",
            description="desc",
            execution_mode="claude_code_cli",
            auto_checkin_enabled=False,
            auto_checkin_interval=10,
        ),
        "product": SimpleNamespace(id="prod-1", project_path="/repo"),
        "metadata": {},
        "field_toggles": {},
        "depth_config": {},
        "templates": [SimpleNamespace(name="implementer", role="implementer", description="impl")],
        "category_metadata": {},
        "integrations": {},
        "orchestrator_prompt_override": None,
        "chain_ctx": chain_ctx,
        "conductor_agent_id": None,
    }


def _suborch_ctx() -> ChainContext:
    return ChainContext(
        run_id="run-1",
        role="sub_orchestrator",
        current_index=0,
        resolved_order=["p1", "p2"],
        is_staging=True,
        conductor_agent_id="c1",
        execution_mode="claude_code_cli",
    )


def _resp(chain_ctx: ChainContext | None) -> dict:
    svc = MissionOrchestrationService.__new__(MissionOrchestrationService)
    return svc._build_orchestrator_response(_ctx(chain_ctx=chain_ctx), "job-sub", "tk")


def test_chain_suborch_staging_omits_protocol_and_identity() -> None:
    resp = _resp(_suborch_ctx())

    assert "orchestrator_protocol" not in resp, "chain sub-orch must not re-ship the full protocol"
    assert "orchestrator_identity" not in resp, "chain sub-orch must not re-ship the orchestrator identity"

    assert resp["protocol_unchanged"] is True
    assert resp["protocol_source"] == "get_job_mission"
    assert "get_job_mission" in resp["protocol_note"]

    assert resp["agent_templates"], "agent_templates (the real reason to call this) must remain"
    assert resp["identity"]["job_id"] == "job-sub"
    assert resp["identity"]["project_id"] == "p2"


def test_solo_staging_keeps_protocol_and_identity() -> None:
    resp = _resp(None)

    assert "orchestrator_protocol" in resp, "solo must keep the full protocol (byte-identical path)"
    assert "orchestrator_identity" in resp, "solo must keep the orchestrator identity"
    assert "protocol_unchanged" not in resp, "the sub-orch pointer must never leak onto the solo path"
    assert resp["agent_templates"], "solo keeps its agent_templates too"
