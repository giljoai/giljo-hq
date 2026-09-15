# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, ProjectStatus
from giljo_mcp.tenant import TenantManager


ENDPOINT = "/api/v1/prompts/master"
CSRF_TOKEN = "test-master-prompt-csrf"


async def _tenant_with_projects(db_manager, count: int = 2):
    async with db_manager.get_session_async() as session:
        suffix = uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(name=f"MP Org {suffix}", slug=f"mp-org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()

        user = User(
            username=f"mp_user_{suffix}",
            email=f"mp_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tenant_key,
            role="admin",
            org_id=org.id,
        )
        session.add(user)

        product = Product(id=str(uuid4()), tenant_key=tenant_key, name=f"MP Product {suffix}")
        session.add(product)
        await session.flush()

        projects, names, missions = [], [], []
        for i in range(count):
            project = Project(
                id=str(uuid4()),
                tenant_key=tenant_key,
                product_id=product.id,
                name=f"Project {i} {suffix}",
                description=f"Project {i} description",
                series_number=i + 1,
                status=ProjectStatus.ACTIVE,
                staging_status="staging_complete",
                mission=f"Mission number {i} for {suffix}",
            )
            session.add(project)
            projects.append(project)
            names.append(project.name)
            missions.append(project.mission)
        await session.commit()
        project_ids = [p.id for p in projects]

    token = JWTManager.create_access_token(user_id=user.id, username=user.username, role="admin", tenant_key=tenant_key)
    headers = {
        "Cookie": f"access_token={token}; csrf_token={CSRF_TOKEN}",
        "X-CSRF-Token": CSRF_TOKEN,
    }
    return headers, tenant_key, project_ids, names, missions


@pytest.mark.asyncio
async def test_returns_the_prompt_and_the_missions_it_was_built_from(api_client, db_manager):
    headers, _tk, ids, names, _missions = await _tenant_with_projects(db_manager)

    response = await api_client.post(ENDPOINT, headers=headers, json={"project_ids": ids, "execution_mode": "subagent"})

    assert response.status_code == 200, response.text
    body = response.json()

    assert [p["project_id"] for p in body["projects"]] == ids
    for name in names:
        assert name in body["prompt"]
    assert "subagent" in body["prompt"]


@pytest.mark.asyncio
async def test_the_order_asked_for_is_the_order_returned(api_client, db_manager):
    headers, _tk, ids, _names, _missions = await _tenant_with_projects(db_manager)
    reversed_ids = list(reversed(ids))

    response = await api_client.post(
        ENDPOINT, headers=headers, json={"project_ids": reversed_ids, "execution_mode": "multi_terminal"}
    )

    assert response.status_code == 200, response.text
    assert [p["project_id"] for p in response.json()["projects"]] == reversed_ids


@pytest.mark.asyncio
async def test_another_tenants_project_id_is_not_found_not_rendered(api_client, db_manager):
    headers_a, _tk_a, _ids_a, _names_a, _missions_a = await _tenant_with_projects(db_manager)
    _headers_b, _tk_b, ids_b, names_b, missions_b = await _tenant_with_projects(db_manager)

    response = await api_client.post(
        ENDPOINT, headers=headers_a, json={"project_ids": ids_b, "execution_mode": "subagent"}
    )

    assert response.status_code == 404, response.text
    for leaked in names_b + missions_b:
        assert leaked not in response.text


@pytest.mark.asyncio
async def test_a_mix_of_own_and_foreign_ids_is_refused_whole(api_client, db_manager):
    headers_a, _tk_a, ids_a, _names_a, _missions_a = await _tenant_with_projects(db_manager, count=1)
    _headers_b, _tk_b, ids_b, names_b, missions_b = await _tenant_with_projects(db_manager, count=1)

    response = await api_client.post(
        ENDPOINT, headers=headers_a, json={"project_ids": ids_a + ids_b, "execution_mode": "subagent"}
    )

    assert response.status_code == 404, response.text
    assert names_b[0] not in response.text
    assert missions_b[0] not in response.text


@pytest.mark.asyncio
async def test_an_empty_selection_is_refused(api_client, db_manager):
    headers, _tk, _ids, _names, _missions = await _tenant_with_projects(db_manager)

    response = await api_client.post(ENDPOINT, headers=headers, json={"project_ids": [], "execution_mode": "subagent"})

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_the_execution_mode_must_be_answered(api_client, db_manager):
    headers, _tk, ids, _names, _missions = await _tenant_with_projects(db_manager)

    omitted = await api_client.post(ENDPOINT, headers=headers, json={"project_ids": ids})
    junk = await api_client.post(ENDPOINT, headers=headers, json={"project_ids": ids, "execution_mode": "terminals"})

    assert omitted.status_code == 422, omitted.text
    assert junk.status_code == 422, junk.text


@pytest.mark.asyncio
async def test_it_requires_authentication(api_client, db_manager):
    _headers, _tk, ids, _names, _missions = await _tenant_with_projects(db_manager)

    response = await api_client.post(ENDPOINT, json={"project_ids": ids, "execution_mode": "subagent"})

    assert response.status_code in (401, 403), response.text
