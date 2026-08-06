# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9330 (sibling site) -- ``GET /api/v1/prompts/agent/{agent_id}`` must not
500 on an agent whose mission has not been written yet.

Same class as the single-job GET defect: a field that is LEGITIMATELY absent at
this moment is read as though it were always populated. ``AgentJob.mission`` is
``nullable=True`` by design -- "null while staged; written at Phase-2"
(``models/agent_identity.py``) -- but ``prompts.py`` did::

    mission = agent.job.mission if agent.job else ""
    mission_preview = mission[:200] + "..." if len(mission) > 200 else mission

The ``if agent.job else ""`` guard only covers a MISSING JOB, never a job whose
mission column is NULL, so ``len(None)`` raises TypeError -> 500.

Unlike the single-job GET, this route IS user-reachable: the dashboard Play
button calls it (``frontend/src/composables/usePlayButton.js:103`` ->
``api.prompts.agentPrompt``).

HTTP-boundary test: the failing layer is the endpoint's own field handling.

Edition Scope: Both.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.models import AgentExecution, AgentJob, Project


def _extract_tenant_key(auth_headers: dict) -> str:
    """Decode the tenant_key baked into the JWT access_token cookie."""
    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


async def _seed_staged_agent(db_manager, tenant_key: str, *, mission: str | None) -> str:
    """A staged specialist. ``mission=None`` is the real pre-Phase-2 state."""
    project_id = str(uuid4())
    agent_id = str(uuid4())
    async with db_manager.get_session_async() as session:
        session.add(
            Project(
                id=project_id,
                name=f"BE-9330 prompt project {uuid4().hex[:8]}",
                description="unwritten mission prompt render",
                mission="unwritten mission prompt render",
                status="active",
                tenant_key=tenant_key,
                execution_mode="multi_terminal",
                implementation_launched_at=datetime.now(UTC),
            )
        )
        job = AgentJob(
            job_id=str(uuid4()),
            tenant_key=tenant_key,
            project_id=project_id,
            job_type="implementer",
            mission=mission,  # None == staged, mission not yet written
            status="active",
        )
        session.add(job)
        session.add(
            AgentExecution(
                agent_id=agent_id,
                job_id=job.job_id,
                tenant_key=tenant_key,
                agent_display_name="implementer",
                status="staged",
            )
        )
        await session.commit()
    return agent_id


@pytest.mark.asyncio
async def test_agent_prompt_renders_for_staged_agent_with_null_mission(api_client, auth_headers, db_manager):
    """A staged agent has no mission yet. Asking for its launch prompt must
    render (the prompt tells the agent to fetch its mission over MCP anyway),
    not crash on len(None).
    """
    tenant_key = _extract_tenant_key(auth_headers)
    agent_id = await _seed_staged_agent(db_manager, tenant_key, mission=None)

    resp = await api_client.get(f"/api/v1/prompts/agent/{agent_id}", headers=auth_headers)

    assert resp.status_code == 200, f"agent prompt failed for a staged (mission-null) agent: {resp.text}"
    body = resp.json()
    assert body["prompt"], "a staged agent must still get a launch prompt"
    assert body["mission_preview"] == "", "an unwritten mission must preview as empty, never as invented text"


@pytest.mark.asyncio
async def test_agent_prompt_preview_still_carries_the_real_mission(api_client, auth_headers, db_manager):
    """The guard must not flatten a REAL mission to empty -- the value that
    exists still has to reach the response.
    """
    tenant_key = _extract_tenant_key(auth_headers)
    mission = "Implement the widget exporter and add a regression test."
    agent_id = await _seed_staged_agent(db_manager, tenant_key, mission=mission)

    resp = await api_client.get(f"/api/v1/prompts/agent/{agent_id}", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["mission_preview"] == mission
