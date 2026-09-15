# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from types import SimpleNamespace

import pytest

from giljo_mcp.services.progress_service import ProgressService


class _CapturingWebSocketManager:

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def broadcast_to_tenant(self, tenant_key: str, event_type: str, data: dict) -> None:
        self.calls.append({"tenant_key": tenant_key, "event_type": event_type, "data": data})


def _make_progress_service() -> tuple[ProgressService, _CapturingWebSocketManager]:
    ws = _CapturingWebSocketManager()
    svc = ProgressService(
        db_manager=None,
        tenant_manager=None,
        websocket_manager=ws,
    )
    return svc, ws


def _make_job(*, chain_conductor: bool):
    metadata = {"chain_conductor": True, "run_id": "run-1"} if chain_conductor else {}
    return SimpleNamespace(project_id="proj-member-1", job_metadata=metadata)


def _make_execution():
    return SimpleNamespace(
        agent_id="exec-1",
        agent_display_name="conductor",
        agent_name="conductor",
        progress=50,
        current_task="driving the chain",
        last_progress_at=None,
        duration_seconds=0.0,
        working_started_at=None,
    )


async def _emit_and_collect(chain_conductor: bool) -> dict[str, dict]:
    svc, ws = _make_progress_service()
    job = _make_job(chain_conductor=chain_conductor)
    execution = _make_execution()

    await svc._broadcast_progress_update(
        tenant_key="tenant-test",
        job_id="job-1",
        job=job,
        execution=execution,
        progress={"todo_items": [{"content": "step", "status": "completed"}]},
        blocked_to_working=True,
        old_resting_status="blocked",
        todo_items_payload=[{"content": "step", "status": "completed"}],
    )

    return {call["event_type"]: call["data"] for call in ws.calls}


@pytest.mark.asyncio
async def test_conductor_ws_events_carry_chain_conductor_true():
    by_type = await _emit_and_collect(chain_conductor=True)

    assert "job:progress_update" in by_type
    assert "agent:status_changed" in by_type
    assert by_type["job:progress_update"]["chain_conductor"] is True
    assert by_type["agent:status_changed"]["chain_conductor"] is True


@pytest.mark.asyncio
async def test_normal_agent_ws_events_carry_chain_conductor_false():
    by_type = await _emit_and_collect(chain_conductor=False)

    assert by_type["job:progress_update"]["chain_conductor"] is False
    assert by_type["agent:status_changed"]["chain_conductor"] is False
