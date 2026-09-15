# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol
from giljo_mcp.services.sequence_chain_context import ChainContext


_COMMON = {
    "cli_mode": True,
    "project_id": "p2",
    "orchestrator_id": "job-sub",
    "tenant_key": "tk_x",
    "include_implementation_reference": False,
}


def _sub_ctx(*, is_staging: bool) -> ChainContext:
    return ChainContext(
        run_id="run-187",
        role="sub_orchestrator",
        current_index=0,
        resolved_order=["p1", "p2"],
        is_staging=is_staging,
        conductor_agent_id="cond-1",
        execution_mode="claude_code_cli",
    )


def test_solo_runtime_byte_identical() -> None:
    baseline = _build_orchestrator_protocol(**_COMMON)
    explicit_none = _build_orchestrator_protocol(**_COMMON, chain_ctx=None)

    assert baseline == explicit_none, "chain_ctx=None must be byte-identical to the no-chain render"
    for key in ("ch_capability", "ch_chain_staging", "ch_chain_drive", "ch_sub_orchestrator"):
        assert key not in baseline, f"{key} must NOT render for a solo project"


def test_sub_orch_staging_gets_ch_sub_orchestrator() -> None:
    chapters = _build_orchestrator_protocol(**_COMMON, chain_ctx=_sub_ctx(is_staging=True))

    assert "ch_sub_orchestrator" in chapters, "sub-orch staging render must carry CH_SUB_ORCHESTRATOR"
    body = chapters["ch_sub_orchestrator"]
    assert "CH_SUB_ORCHESTRATOR" in body
    assert "project 2 of 2" in body
    assert "run-187" in body, "the chain-member render must carry its run context"
    assert "hub_thread_id" in body, "Hub-thread discovery path must be present"
    assert "list_threads(query=" not in body, "the retired substring-discovery path must not be re-introduced"

    for key in ("ch_capability", "ch_chain_staging", "ch_chain_drive"):
        assert key not in chapters, f"{key} must NOT render for a sub_orchestrator"
