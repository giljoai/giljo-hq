# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
import uuid

import bcrypt
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import ProjectStatus
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio

_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed_staged_project(db_manager, status: ProjectStatus) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        session.info["tenant_key"] = tenant_key

        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        user = User(
            username=f"u_{suffix}",
            email=f"u_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        product = Product(
            id=str(uuid.uuid4()),
            name=f"Product {suffix}",
            description="Test product",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add_all([user, product])
        await session.flush()
        project = Project(
            id=str(uuid.uuid4()),
            name=f"Solo {suffix}",
            description="Launch reply parity probe",
            mission="Stand alone.",
            tenant_key=tenant_key,
            product_id=product.id,
            status=status,
            series_number=next_series_number(),
            execution_mode="claude_code_cli",
            staging_status="staging_complete",
        )
        session.add(project)
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id, username=user.username, role="developer", tenant_key=tenant_key
        )
        return {
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
            "tenant_key": tenant_key,
            "project_id": project.id,
        }


async def _stored_status(db_manager, seed: dict) -> ProjectStatus:
    async with db_manager.get_session_async(tenant_key=seed["tenant_key"]) as session:
        return (
            await session.execute(
                select(Project.status).where(Project.id == seed["project_id"], Project.tenant_key == seed["tenant_key"])
            )
        ).scalar_one()


async def test_rest_launch_on_an_inactive_project_reports_it_active(api_client: AsyncClient, db_manager):
    seed = await _seed_staged_project(db_manager, ProjectStatus.INACTIVE)

    resp = await api_client.patch(
        f"/api/agent-jobs/projects/{seed['project_id']}/launch-implementation", headers=seed["headers"]
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["implementation_launched_at"]
    assert body.get("project_active") is True, f"the dashboard door dropped the activation report: {body!r}"
    assert not body.get("next_action")
    assert await _stored_status(db_manager, seed) == ProjectStatus.ACTIVE


async def test_rest_launch_on_a_parked_project_names_the_step_still_required(api_client: AsyncClient, db_manager):
    seed = await _seed_staged_project(db_manager, ProjectStatus.PARKED)

    resp = await api_client.patch(
        f"/api/agent-jobs/projects/{seed['project_id']}/launch-implementation", headers=seed["headers"]
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("project_active") is False, f"the dashboard door dropped the activation report: {body!r}"
    assert "activ" in str(body.get("next_action") or "").lower()
    assert await _stored_status(db_manager, seed) == ProjectStatus.PARKED


async def test_rest_repeat_launch_keeps_the_report(api_client: AsyncClient, db_manager):
    seed = await _seed_staged_project(db_manager, ProjectStatus.PARKED)
    url = f"/api/agent-jobs/projects/{seed['project_id']}/launch-implementation"
    await api_client.patch(url, headers=seed["headers"])

    resp = await api_client.patch(url, headers=seed["headers"])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["already_launched"] is True
    assert body.get("project_active") is False
    assert "activ" in str(body.get("next_action") or "").lower()
