# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9038 -- HTTP-boundary test for the "detected: <harness>" chip's read path.

``GET /api/v1/projects/{project_id}/orchestrator`` is the smallest read-only
surface the dashboard chip reads (BE-9035c follow-up). Gates that
``OrchestratorJobResponse.detected_harness`` reflects the project's most
recently touched ``MCPSession.session_data['resolved_harness']`` (BE-9035b) --
a concrete harness, the ``generic`` fail-safe, or ``None`` when no session has
ever been stamped for the project. Tenant-scoped by construction (queried by
``tenant_key`` alongside ``project_id``).

Edition Scope: Both.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest


def _extract_tenant_key(auth_headers: dict) -> str:
    """Decode the tenant_key baked into the JWT access_token cookie."""
    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


async def _seed_project_with_orchestrator(db_manager, tenant_key: str, *, resolved_harness: str | None) -> str:
    """Create a Project + orchestrator AgentJob/AgentExecution, and (if given) an
    MCPSession stamped with resolved_harness. Returns the project_id."""
    from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
    from giljo_mcp.models.auth import MCPSession

    project_id = str(uuid4())
    job_id = str(uuid4())
    agent_id = str(uuid4())

    product_id = str(uuid4())
    async with db_manager.get_session_async() as session:
        # BE-9437: a project belongs to a product.
        session.add(
            Product(
                id=product_id,
                tenant_key=tenant_key,
                name=f"TSK-9038 product {uuid4().hex[:8]}",
                description="fixture",
                is_active=False,
            )
        )
        session.add(
            Project(
                id=project_id,
                product_id=product_id,
                name="TSK-9038 harness chip fixture",
                description="fixture",
                mission="fixture mission",
                status="active",
                tenant_key=tenant_key,
                execution_mode="subagent",
            )
        )
        session.add(
            AgentJob(
                job_id=job_id,
                tenant_key=tenant_key,
                project_id=project_id,
                mission="Orchestrator for TSK-9038 fixture",
                job_type="orchestrator",
                status="active",
            )
        )
        session.add(
            AgentExecution(
                agent_id=agent_id,
                job_id=job_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                agent_name="orchestrator",
                status="working",
                progress=10,
                tool_type="universal",
            )
        )
        if resolved_harness is not None:
            session.add(
                MCPSession(
                    id=str(uuid4()),
                    session_id=str(uuid4()),
                    tenant_key=tenant_key,
                    project_id=project_id,
                    session_data={"resolved_harness": resolved_harness},
                    last_accessed=datetime.now(UTC),
                )
            )
        await session.commit()

    return project_id


@pytest.mark.asyncio
class TestDetectedHarnessOnOrchestratorEndpoint:
    async def test_concrete_harness_is_surfaced(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        project_id = await _seed_project_with_orchestrator(db_manager, tenant_key, resolved_harness="claude-code")

        resp = await api_client.get(f"/api/v1/projects/{project_id}/orchestrator", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["orchestrator"]["detected_harness"] == "claude-code"

    async def test_generic_harness_is_surfaced_raw(self, api_client, auth_headers, db_manager):
        """Backend passes the raw 'generic' token through -- the chip's neutral
        display decision (show nothing) lives in the frontend, not the API."""
        tenant_key = _extract_tenant_key(auth_headers)
        project_id = await _seed_project_with_orchestrator(db_manager, tenant_key, resolved_harness="generic")

        resp = await api_client.get(f"/api/v1/projects/{project_id}/orchestrator", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["orchestrator"]["detected_harness"] == "generic"

    async def test_no_session_yields_null_detected_harness(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        project_id = await _seed_project_with_orchestrator(db_manager, tenant_key, resolved_harness=None)

        resp = await api_client.get(f"/api/v1/projects/{project_id}/orchestrator", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["orchestrator"]["detected_harness"] is None
