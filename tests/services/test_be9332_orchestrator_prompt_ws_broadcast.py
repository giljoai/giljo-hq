# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9332 — direct unit tests for the shared orchestrator-prompt WS emitter.

The emitter exists because ``orchestrator:prompt_generated`` had two hand-inlined
emission sites that had already drifted apart, and a third path (the MCP
``stage_project`` tool) that emitted nothing at all. Its contract is asserted here at
the unit level; the end-to-end behaviour of each caller is covered by
``tests/integration/test_inf6049b_stage_implement_tools.py``.

Pure in-memory assertions — no DB, no module-level mutable state. Edition Scope: Both.
"""

from __future__ import annotations

import pytest

from giljo_mcp.services.orchestrator_prompt_ws_broadcast import (
    EVENT_TYPE,
    broadcast_orchestrator_prompt_generated,
)


pytestmark = pytest.mark.asyncio


class _SpyManager:
    def __init__(self, raises: bool = False) -> None:
        self.calls: list[dict] = []
        self._raises = raises

    async def broadcast_to_tenant(self, tenant_key: str, event_type: str, data: dict) -> None:
        self.calls.append({"tenant_key": tenant_key, "event_type": event_type, "data": data})
        if self._raises:
            raise RuntimeError("simulated WebSocket failure")


async def test_emits_the_canonical_event_type_scoped_to_the_tenant():
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(spy, tenant_key="tenant-a", project_id="p1", orchestrator_id="o1")

    assert len(spy.calls) == 1
    assert spy.calls[0]["event_type"] == EVENT_TYPE == "orchestrator:prompt_generated"
    # Tenant-scoped by construction — never a broader audience than the caller's tenant.
    assert spy.calls[0]["tenant_key"] == "tenant-a"


async def test_always_present_keys_are_always_present():
    """project_id / orchestrator_id / thin_client are the floor of the payload — the
    frontend route reads the first two to identify the row it must create."""
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(spy, tenant_key="t", project_id="p1", orchestrator_id="o1")

    data = spy.calls[0]["data"]
    assert data["project_id"] == "p1"
    assert data["orchestrator_id"] == "o1"
    assert data["thin_client"] is True


async def test_none_optional_keys_are_omitted_not_sent_as_null():
    """The frontend store merges payload keys onto existing state ({...previous, ...patch}),
    so a stray None would OVERWRITE a good value. Omitting the key leaves it untouched.

    This is also what keeps each caller's wire payload a superset of what it sent before
    the extraction: a caller that never sent `tool` still does not send it.
    """
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(
        spy,
        tenant_key="t",
        project_id="p1",
        orchestrator_id="o1",
        agent_id=None,
        execution_id=None,
        estimated_tokens=None,
        tool=None,
        timestamp=None,
        product_id=None,
    )

    data = spy.calls[0]["data"]
    for omitted in ("agent_id", "execution_id", "estimated_tokens", "tool", "timestamp", "product_id"):
        assert omitted not in data, f"{omitted!r} was None and must be omitted, not sent as null: {data!r}"


async def test_supplied_optional_keys_are_included():
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(
        spy,
        tenant_key="t",
        project_id="p1",
        orchestrator_id="o1",
        agent_id="a1",
        execution_id="e1",
        estimated_tokens=931,
        tool="claude-code",
        timestamp="2026-08-02T00:00:00+00:00",
        product_id="prod-1",
    )

    assert spy.calls[0]["data"] == {
        "project_id": "p1",
        "orchestrator_id": "o1",
        "thin_client": True,
        "agent_id": "a1",
        "execution_id": "e1",
        "estimated_tokens": 931,
        "tool": "claude-code",
        "timestamp": "2026-08-02T00:00:00+00:00",
        "product_id": "prod-1",
    }


async def test_estimated_tokens_zero_is_still_sent():
    """Guard against an `if value` truthiness bug in the omit-None filter: a real 0-token
    estimate must reach the wire, only None is omitted."""
    spy = _SpyManager()
    await broadcast_orchestrator_prompt_generated(
        spy, tenant_key="t", project_id="p1", orchestrator_id="o1", estimated_tokens=0
    )

    assert spy.calls[0]["data"]["estimated_tokens"] == 0


async def test_no_manager_is_a_silent_no_op():
    """websocket_manager=None is a normal state (an accessor built before the WS manager
    exists), not an error — it must not raise."""
    await broadcast_orchestrator_prompt_generated(None, tenant_key="t", project_id="p1", orchestrator_id="o1")


async def test_broadcast_failure_is_swallowed():
    """Best-effort: a notification must never fail the staging it reports on."""
    spy = _SpyManager(raises=True)

    await broadcast_orchestrator_prompt_generated(spy, tenant_key="t", project_id="p1", orchestrator_id="o1")

    assert len(spy.calls) == 1, "the broadcast was attempted before the failure was swallowed"
