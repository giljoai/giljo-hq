# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate


def _extract_tenant_key(auth_headers: dict) -> str:
    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


async def _seed_bound_job(db_manager, tenant_key: str, *, bind_template: bool = True) -> tuple[str, str, str | None]:
    product_id = str(uuid4())
    project_id = str(uuid4())
    job_id = str(uuid4())
    template_id = str(uuid4()) if bind_template else None
    async with db_manager.get_session_async() as session:
        session.add(
            Product(
                id=product_id,
                tenant_key=tenant_key,
                name=f"FE-9818 product {uuid4().hex[:8]}",
                description="seeded",
                is_active=False,
            )
        )
        session.add(
            Project(
                id=project_id,
                product_id=product_id,
                name=f"FE-9818 project {uuid4().hex[:8]}",
                description="bound template on job rows",
                mission="bound template on job rows mission",
                status="active",
                tenant_key=tenant_key,
                execution_mode="multi_terminal",
                implementation_launched_at=datetime.now(UTC),
            )
        )
        if template_id:
            session.add(
                AgentTemplate(
                    id=template_id,
                    tenant_key=tenant_key,
                    product_id=product_id,
                    name=f"implementer-{uuid4().hex[:6]}",
                    category="custom",
                    role="implementer",
                    system_instructions="bootstrap",
                    user_instructions="Build it.",
                    tool="claude",
                    cli_tool="claude",
                    is_active=True,
                )
            )
        await session.flush()
        session.add(
            AgentJob(
                job_id=job_id,
                tenant_key=tenant_key,
                project_id=project_id,
                job_type="implementer",
                mission="build it",
                status="active",
                template_id=template_id,
            )
        )
        session.add(
            AgentExecution(
                job_id=job_id,
                tenant_key=tenant_key,
                agent_display_name="implementer",
                agent_name="implementer",
                status="working",
                started_at=datetime.now(UTC) - timedelta(minutes=5),
                messages_sent_count=0,
                messages_waiting_count=0,
                messages_read_count=0,
            )
        )
        await session.commit()
    return project_id, job_id, template_id


@pytest.mark.asyncio
async def test_list_and_detail_rows_carry_the_bound_template_id(api_client, auth_headers, db_manager):
    tenant_key = _extract_tenant_key(auth_headers)
    project_id, job_id, template_id = await _seed_bound_job(db_manager, tenant_key)

    listing = await api_client.get("/api/agent-jobs/", headers=auth_headers, params={"project_id": project_id})
    detail = await api_client.get(f"/api/agent-jobs/{job_id}", headers=auth_headers)

    assert listing.status_code == 200, listing.text
    assert detail.status_code == 200, detail.text
    row = next(job for job in listing.json()["jobs"] if job["job_id"] == job_id)
    assert "template_id" in row, "the list row dropped template_id"
    assert row["template_id"] == template_id
    assert detail.json().get("template_id") == template_id


@pytest.mark.asyncio
async def test_an_unbound_job_serves_template_id_null(api_client, auth_headers, db_manager):
    tenant_key = _extract_tenant_key(auth_headers)
    project_id, job_id, _ = await _seed_bound_job(db_manager, tenant_key, bind_template=False)

    listing = await api_client.get("/api/agent-jobs/", headers=auth_headers, params={"project_id": project_id})

    assert listing.status_code == 200, listing.text
    row = next(job for job in listing.json()["jobs"] if job["job_id"] == job_id)
    assert "template_id" in row
    assert row["template_id"] is None


@pytest.mark.asyncio
async def test_another_tenants_bound_template_id_is_not_readable(api_client, auth_headers, db_manager):
    other_tenant = f"tk_{uuid4().hex}"
    project_id, job_id, template_id = await _seed_bound_job(db_manager, other_tenant)

    detail = await api_client.get(f"/api/agent-jobs/{job_id}", headers=auth_headers)
    listing = await api_client.get("/api/agent-jobs/", headers=auth_headers, params={"project_id": project_id})
    batch = await api_client.get("/api/agent-jobs/", headers=auth_headers, params={"project_ids": project_id})

    assert detail.status_code == 404, f"another tenant's job was reachable: {detail.status_code} {detail.text}"
    for resp in (listing, batch):
        assert resp.status_code == 200, resp.text
        assert all(job["job_id"] != job_id for job in resp.json()["jobs"])
        assert template_id not in resp.text
