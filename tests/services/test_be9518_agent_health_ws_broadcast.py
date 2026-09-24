# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    spy = _SpyManager()
    await broadcast_agent_auto_failed(
        spy,
        tenant_key="tenant-a",
        job_id="job-1",
        agent_display_name="implementer",
        reason="Abandoned",
    )

    assert "product_id" not in spy.calls[0]["event"]["data"]


async def test_broadcast_agent_auto_failed_logs_designed_cleanup_below_error(caplog):
    spy = _SpyManager()
    module = "giljo_mcp.services.agent_health_ws_broadcast"

    with caplog.at_level("DEBUG", logger=module):
        await broadcast_agent_auto_failed(
            spy,
            tenant_key="tenant-a",
            job_id="job-1",
            agent_display_name="implementer",
            reason="Abandoned 1445m — auto-decommissioned",
        )

    records = [r for r in caplog.records if r.name == module]
    assert records, "the broadcast must still log the auto-fail — silence is the opposite failure"
    assert not [r for r in records if r.levelno >= 40], (
        "designed auto-cleanup must not log at ERROR: "
        f"{[(r.levelname, r.getMessage()) for r in records if r.levelno >= 40]!r}"
    )
    assert any("broadcast_auto_failed" in r.getMessage() for r in records), (
        f"the auto-fail line must still be logged, got: {[r.getMessage() for r in records]!r}"
    )
