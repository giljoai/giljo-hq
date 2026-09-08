# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6187 — sub-orchestrator chain-member chapter (CH_SUB_ORCHESTRATOR).

After BE-6184 every project's own orchestrator is a symmetric ``sub_orchestrator``
(the conductor is dedicated + project-less). BE-6187 gives that sub-orchestrator a
chain-context chapter at BOTH staging (via ``_build_orchestrator_protocol``) and
runtime (via ``conductor_chain_injector``): its chain position, the Hub-thread
discovery path (list_threads on run_id), and the close-out advance signal.

This file covers the two non-injector unit contracts:

  * test_solo_runtime_byte_identical — a solo project (chain_ctx=None) renders no
    chain chapter; the staging render stays byte-identical (Deletion Test).
  * test_sub_orch_staging_gets_ch_sub_orchestrator — a sub_orchestrator chain_ctx in
    the STAGING phase produces the CH_SUB_ORCHESTRATOR chapter (and never the
    conductor chapters).

The runtime injector branch + the conductor staging Hub-thread tools/prose live in
test_be6177_conductor_chain_injector.py and test_be6186_conductor_staging_builder.py.

Pure unit tests (no DB). Edition Scope: CE.
"""

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
    """A solo project (chain_ctx=None) renders no chain chapter and is byte-identical
    to the explicit-None render (Deletion Test holds)."""
    baseline = _build_orchestrator_protocol(**_COMMON)
    explicit_none = _build_orchestrator_protocol(**_COMMON, chain_ctx=None)

    assert baseline == explicit_none, "chain_ctx=None must be byte-identical to the no-chain render"
    for key in ("ch_capability", "ch_chain_staging", "ch_chain_drive", "ch_sub_orchestrator"):
        assert key not in baseline, f"{key} must NOT render for a solo project"


def test_sub_orch_staging_gets_ch_sub_orchestrator() -> None:
    """A sub_orchestrator chain_ctx in the staging phase produces CH_SUB_ORCHESTRATOR
    (its chain position + Hub discovery), and never the conductor chapters."""
    chapters = _build_orchestrator_protocol(**_COMMON, chain_ctx=_sub_ctx(is_staging=True))

    assert "ch_sub_orchestrator" in chapters, "sub-orch staging render must carry CH_SUB_ORCHESTRATOR"
    body = chapters["ch_sub_orchestrator"]
    assert "CH_SUB_ORCHESTRATOR" in body
    # p2 is index 1 → position 2 of 2.
    assert "project 2 of 2" in body
    # BE-9291 DELIBERATELY CHANGED the discovery probe. This asserted `list_threads`,
    # which after BE-9291 is satisfied ONLY by the ToolSearch BOOTSTRAP line (a tool-loading
    # hint), so it kept passing while proving nothing about discovery. Discovery now runs on
    # the comm_threads.sequence_run_id FK. Same intent, current truth.
    assert "run-187" in body, "the chain-member render must carry its run context"
    assert "hub_thread_id" in body, "Hub-thread discovery path must be present"
    assert "list_threads(query=" not in body, "the retired substring-discovery path must not be re-introduced"

    # The conductor-only chapters must NOT render for a sub-orchestrator.
    for key in ("ch_capability", "ch_chain_staging", "ch_chain_drive"):
        assert key not in chapters, f"{key} must NOT render for a sub_orchestrator"
