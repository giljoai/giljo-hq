# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol


def test_worker_protocol_has_etag_cache_note() -> None:
    proto = _generate_agent_protocol(
        job_id="job-6209c",
        tenant_key="tk_6209c",
        agent_name="implementer",
        agent_id="exec-6209c",
        execution_mode="claude-code",
        job_type="agent",
        tool="claude-code",
    )
    assert "PROTOCOL CACHE" in proto
    assert "protocol_etag" in proto
    assert "protocol_unchanged=true" in proto
    assert "reuse the" in proto


def test_orchestrator_protocol_has_etag_cache_note() -> None:
    proto = _generate_orchestrator_protocol(
        job_id="job-6209c",
        tenant_key="tk_6209c",
        executor_id="exec-6209c",
        execution_mode="multi_terminal",
        tool="multi_terminal",
    )
    assert "PROTOCOL CACHE" in proto
    assert "protocol_etag" in proto
    assert "protocol_unchanged=true" in proto
    assert "reuse the copy you" in proto
