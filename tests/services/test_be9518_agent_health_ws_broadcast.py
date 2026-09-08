# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9518 — direct unit tests for the extracted agent-health WS emitter module.

``broadcast_health_alert`` / ``broadcast_agent_auto_failed`` moved off
``WebSocketManager`` to module-level functions here (mirroring the existing
``closeout_ws_broadcast.py`` / ``orchestrator_prompt_ws_broadcast.py``
extractions) purely for ``api/websocket.py`` file-size compliance -- no
behavior change. This file is the dedicated test surface for the new module;
the wiring into ``monitoring/agent_health_monitor.py`` is covered separately
by ``tests/unit/test_be9101_health_monitor_abandon.py`` and
``tests/unit/test_be6004c_background_bypass.py``.

Pure in-memory (spy WebSocket manager) -- no DB, no module-level mutable
state. Edition Scope: Both.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from giljo_mcp.monitoring.health_config import AgentHealthStatus
from giljo_mcp.services.agent_health_ws_broadcast import (
    broadcast_agent_auto_failed,
    broadcast_health_alert,
)


pytestmark = pytest.mark.asyncio


class _SpyManager:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def broadcast_event_to_tenant(self, tenant_key: str, event: dict) -> None:
        self.calls.append({"tenant_key": tenant_key, "event": event})


def _health_status(**overrides) -> AgentHealthStatus:
    base = {
        "execution_id": "exec-1",
        "job_id": "job-1",
        "agent_id": "agent-1",
        "agent_display_name": "implementer",
        "current_status": "working",
        "health_state": "critical",
        "last_update": datetime.now(UTC),
        "minutes_since_update": 20.0,
        "issue_description": "No progress",
        "recommended_action": "Check agent",
        "project_id": "proj-1",
        "project_name": "Project One",
        "product_id": "prod-1",
    }
    base.update(overrides)
    return AgentHealthStatus(**base)


async def test_broadcast_health_alert_emits_correct_event_type_and_data():
    spy = _SpyManager()
    await broadcast_health_alert(
        spy,
        tenant_key="tenant-a",
        job_id="job-1",
        agent_display_name="implementer",
        health_status=_health_status(),
    )

    assert len(spy.calls) == 1
    event = spy.calls[0]["event"]
    assert event["type"] == "agent:health_alert"
    assert event["data"]["product_id"] == "prod-1"
    assert event["data"]["project_id"] == "proj-1"
    assert event["data"]["job_id"] == "job-1"


async def test_broadcast_health_alert_product_id_defaults_empty_string():
    """Matches AgentHealthStatus's own default -- "" not None, for a job with
    no owning project (mirrors the pre-existing project_id/project_name
    convention on this dataclass)."""
    spy = _SpyManager()
    await broadcast_health_alert(
        spy,
        tenant_key="tenant-a",
        job_id="job-1",
        agent_display_name="implementer",
        health_status=_health_status(project_id="", project_name="", product_id=""),
    )

    assert spy.calls[0]["event"]["data"]["product_id"] == ""


async def test_broadcast_agent_auto_failed_emits_correct_event_type_and_data():
    spy = _SpyManager()
    await broadcast_agent_auto_failed(
        spy,
        tenant_key="tenant-a",
        job_id="job-1",
        agent_display_name="implementer",
        reason="Abandoned",
        product_id="prod-1",
    )

    assert len(spy.calls) == 1
    event = spy.calls[0]["event"]
    assert event["type"] == "agent:auto_failed"
    assert event["data"]["product_id"] == "prod-1"
    assert event["data"]["reason"] == "Abandoned"
    assert event["data"]["auto_failed"] is True


async def test_broadcast_agent_auto_failed_omits_product_id_when_none():
    """Additive contract: unlike health_alert (which always carries the field
    via the AgentHealthStatus object), auto_failed takes product_id as a bare
    optional kwarg and must OMIT it, not send null, when the caller has none."""
    spy = _SpyManager()
    await broadcast_agent_auto_failed(
        spy,
        tenant_key="tenant-a",
        job_id="job-1",
        agent_display_name="implementer",
        reason="Abandoned",
    )

    assert "product_id" not in spy.calls[0]["event"]["data"]
