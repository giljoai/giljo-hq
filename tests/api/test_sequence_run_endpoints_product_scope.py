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

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed_tenant(db_manager) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()

        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        product = Product(
            id=str(uuid.uuid4()),
            name=f"Product {suffix}",
            description="sequence-run scope test product",
            tenant_key=tenant_key,
            is_active=True,
            is_default=True,
        )
        session.add(product)
        await session.flush()

        project = Project(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"Project {suffix}",
            description="desc",
            mission="mission",
        )
        session.add(project)
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id, username=user.username, role="developer", tenant_key=tenant_key
        )
        headers = {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
        return {
            "tenant_key": tenant_key,
            "product_id": product.id,
            "project_id": project.id,
            "headers": headers,
        }


async def _add_product_with_project(db_manager, tenant_key: str) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        product = Product(
            id=str(uuid.uuid4()),
            name=f"Product {suffix}",
            description="sequence-run scope test second product",
            tenant_key=tenant_key,
            is_active=True,
            is_default=False,
        )
        session.add(product)
        await session.flush()
        project = Project(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"Project {suffix}",
            description="desc",
            mission="mission",
        )
        session.add(project)
        await session.commit()
        return {"product_id": product.id, "project_id": project.id}


async def _add_run(db_manager, tenant_key: str, project_id: str) -> str:
    run_id = str(uuid.uuid4())
    async with db_manager.get_session_async() as session:
        session.add(
            SequenceRun(
                id=run_id,
                tenant_key=tenant_key,
                project_ids=[project_id],
                resolved_order=[project_id],
                current_index=0,
                execution_mode="subagent",
                status="running",
                project_statuses={project_id: "pending"},
            )
        )
        await session.commit()
    return run_id


async def _seed_two_products_each_with_a_run(db_manager) -> dict:
    a = await _seed_tenant(db_manager)
    b = await _add_product_with_project(db_manager, a["tenant_key"])
    a_run = await _add_run(db_manager, a["tenant_key"], a["project_id"])
    b_run = await _add_run(db_manager, a["tenant_key"], b["project_id"])
    return {"a": a, "b": b, "a_run": a_run, "b_run": b_run}


@pytest.mark.asyncio
async def test_list_scoped_to_product_returns_only_that_products_run(api_client: AsyncClient, db_manager) -> None:
    seeded = await _seed_two_products_each_with_a_run(db_manager)

    resp = await api_client.get(
        "/api/v1/sequence-runs",
        headers=seeded["a"]["headers"],
        params={"product_id": seeded["a"]["product_id"]},
    )
    assert resp.status_code == 200, resp.text
    ids = {r["id"] for r in resp.json()}
    assert ids == {seeded["a_run"]}


@pytest.mark.asyncio
async def test_list_scoped_to_other_product_returns_only_its_run(api_client: AsyncClient, db_manager) -> None:
    seeded = await _seed_two_products_each_with_a_run(db_manager)

    resp = await api_client.get(
        "/api/v1/sequence-runs",
        headers=seeded["a"]["headers"],
        params={"product_id": seeded["b"]["product_id"]},
    )
    assert resp.status_code == 200, resp.text
    ids = {r["id"] for r in resp.json()}
    assert ids == {seeded["b_run"]}


@pytest.mark.asyncio
async def test_list_omitted_product_id_stays_tenant_wide(api_client: AsyncClient, db_manager) -> None:
    seeded = await _seed_two_products_each_with_a_run(db_manager)

    resp = await api_client.get("/api/v1/sequence-runs", headers=seeded["a"]["headers"])
    assert resp.status_code == 200, resp.text
    ids = {r["id"] for r in resp.json()}
    assert ids == {seeded["a_run"], seeded["b_run"]}


@pytest.mark.asyncio
async def test_list_foreign_product_id_is_refused_not_defaulted(api_client: AsyncClient, db_manager) -> None:
    seeded = await _seed_two_products_each_with_a_run(db_manager)
    other = await _seed_tenant(db_manager)

    resp = await api_client.get(
        "/api/v1/sequence-runs",
        headers=seeded["a"]["headers"],
        params={"product_id": other["product_id"]},
    )
    assert resp.status_code == 422, resp.text
