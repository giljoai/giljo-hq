# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest

from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.models.products import Product
from giljo_mcp.tenant import TenantManager


def _extract_tenant_key(auth_headers: dict) -> str:
    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


async def _seed_project(db_manager, tenant_key: str, agents: tuple[str, ...]) -> tuple[str, set[str]]:
    project_id = str(uuid4())
    product_id = str(uuid4())
    job_ids: set[str] = set()
    async with db_manager.get_session_async() as session:
        session.add(
            Product(
                id=product_id,
                tenant_key=tenant_key,
                name=f"BE-9797 product {uuid4().hex[:8]}",
                description="seeded",
                is_active=False,
            )
        )
        session.add(
            Project(
                id=project_id,
                product_id=product_id,
                name=f"BE-9797 project {uuid4().hex[:8]}",
                description="board batch read",
                mission="board batch read mission",
                status="active",
                tenant_key=tenant_key,
                execution_mode="multi_terminal",
            )
        )
        await session.flush()
        for display_name in agents:
            job_id = str(uuid4())
            session.add(
                AgentJob(
                    job_id=job_id,
                    tenant_key=tenant_key,
                    project_id=project_id,
                    job_type=display_name,
                    mission=f"mission {display_name}",
                    status="active",
                )
            )
            session.add(
                AgentExecution(
                    job_id=job_id,
                    tenant_key=tenant_key,
                    agent_display_name=display_name,
                    status="working",
                    messages_sent_count=0,
                    messages_waiting_count=0,
                    messages_read_count=0,
                )
            )
            job_ids.add(job_id)
        await session.commit()
    return project_id, job_ids


@pytest.mark.asyncio
async def test_project_ids_returns_the_union_in_one_response(api_client, auth_headers, db_manager):
    tenant_key = _extract_tenant_key(auth_headers)
    p1, p1_jobs = await _seed_project(db_manager, tenant_key, ("orchestrator", "implementer"))
    p2, p2_jobs = await _seed_project(db_manager, tenant_key, ("orchestrator",))
    p_empty, _ = await _seed_project(db_manager, tenant_key, ())
    _unnamed, unnamed_jobs = await _seed_project(db_manager, tenant_key, ("analyzer",))

    resp = await api_client.get(
        "/api/agent-jobs/", params={"project_ids": f"{p1},{p2},{p_empty}", "limit": 500}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {job["job_id"] for job in body["jobs"]} == p1_jobs | p2_jobs
    assert not {job["job_id"] for job in body["jobs"]} & unnamed_jobs, "an unnamed project must not leak in"
    assert {job["project_id"] for job in body["jobs"]} == {p1, p2}
    assert body["total"] == len(p1_jobs | p2_jobs)
    assert set(body) == {"jobs", "total", "limit", "offset"}


@pytest.mark.asyncio
async def test_a_foreign_tenants_project_id_contributes_nothing(api_client, auth_headers, db_manager):
    tenant_key = _extract_tenant_key(auth_headers)
    mine, my_jobs = await _seed_project(db_manager, tenant_key, ("orchestrator",))
    foreign, foreign_jobs = await _seed_project(
        db_manager, TenantManager.generate_tenant_key(), ("orchestrator", "tester")
    )
    await _seed_project(db_manager, tenant_key, ("analyzer",))

    resp = await api_client.get("/api/agent-jobs/", params={"project_ids": f"{mine},{foreign}"}, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    got = {job["job_id"] for job in resp.json()["jobs"]}
    assert got == my_jobs
    assert not got & foreign_jobs


@pytest.mark.asyncio
async def test_project_id_and_project_ids_together_is_422(api_client, auth_headers, db_manager):
    tenant_key = _extract_tenant_key(auth_headers)
    p1, _ = await _seed_project(db_manager, tenant_key, ("orchestrator",))

    resp = await api_client.get("/api/agent-jobs/", params={"project_id": p1, "project_ids": p1}, headers=auth_headers)

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_more_than_200_project_ids_is_422(api_client, auth_headers):
    ids = ",".join(str(uuid4()) for _ in range(201))

    resp = await api_client.get("/api/agent-jobs/", params={"project_ids": ids}, headers=auth_headers)

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_an_overlong_id_in_the_list_is_422(api_client, auth_headers):
    resp = await api_client.get(
        "/api/agent-jobs/", params={"project_ids": f"{uuid4()},{'x' * 65}"}, headers=auth_headers
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_an_empty_project_ids_is_422_never_tenant_wide(api_client, auth_headers):
    resp = await api_client.get("/api/agent-jobs/", params={"project_ids": " , "}, headers=auth_headers)

    assert resp.status_code == 422, resp.text
