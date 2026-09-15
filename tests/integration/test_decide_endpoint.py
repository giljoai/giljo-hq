# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.endpoints.approvals import get_user_approval_service
from api.endpoints.approvals import router as approvals_router
from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import User
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.services.user_approval_service import UserApprovalService
from giljo_mcp.tenant import TenantManager
from tests.helpers.route_surface import iter_effective_routes


pytestmark = pytest.mark.asyncio


def _build_app(
    db_manager,
    db_session: AsyncSession,
    user: User | None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(approvals_router, prefix="/api/approvals")

    if user is not None:

        async def _override_user() -> User:
            return user

        app.dependency_overrides[get_current_active_user] = _override_user

    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()

    async def _override_service() -> AsyncIterator[UserApprovalService]:
        yield UserApprovalService(
            db_manager=db_manager,
            tenant_manager=TenantManager(),
            websocket_manager=ws,
            test_session=db_session,
        )

    app.dependency_overrides[get_user_approval_service] = _override_service
    return app


async def _seed_full(db_session: AsyncSession, tenant_key: str) -> dict:
    suffix = uuid4().hex[:8]
    org = Organization(
        name=f"Org {suffix}",
        slug=f"org-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="x",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="x",
        mission="x",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(execution)
    return {"product": product, "project": project, "job": job, "execution": execution}


@pytest_asyncio.fixture
async def pending_approval(db_manager, db_session, test_user):
    seed = await _seed_full(db_session, test_user.tenant_key)
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    service = UserApprovalService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        websocket_manager=ws,
        test_session=db_session,
    )
    approval = await service.create_pending(
        tenant_key=test_user.tenant_key,
        job_id=seed["job"].job_id,
        project_id=seed["project"].id,
        reason="Closeout: awaiting user review",
        options=[
            {"id": "approve", "label": "Approve and close"},
            {"id": "rework", "label": "Send back for rework"},
        ],
        context={"deferred_findings": ["x"]},
    )
    return {"approval": approval, "seed": seed}


async def test_decide_requires_auth_dependency(db_manager, db_session, pending_approval):
    app = _build_app(db_manager, db_session, user=None)
    decide_route = next(
        (route for route in iter_effective_routes(app.routes) if route.path == "/api/approvals/{approval_id}/decide"),
        None,
    )
    assert decide_route is not None, "decide route missing from app router"

    def _depends_on_auth(dependant) -> bool:
        if dependant.call is get_current_active_user:
            return True
        return any(_depends_on_auth(child) for child in (dependant.dependencies or []))

    assert _depends_on_auth(decide_route.dependant), (
        "AUTH GATE MISSING: decide endpoint does not inject get_current_active_user"
    )


async def test_decide_round_trip_flips_status_and_resumes_agent(db_manager, db_session, test_user, pending_approval):
    app = _build_app(db_manager, db_session, user=test_user)
    approval_id = pending_approval["approval"].id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"option_id": "approve"},
        )

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["approval_id"] == approval_id
    assert body["status"] == "decided"
    assert body["decided_option_id"] == "approve"

    row = (await db_session.execute(select(UserApproval).where(UserApproval.id == approval_id))).scalar_one()
    assert row.status == "decided"
    assert row.decided_option_id == "approve"
    assert row.decided_by_user_id == str(test_user.id)
    assert row.decided_via == "ui", "BE-9514: the REST /decide door must record decided_via='ui'"
    assert row.decided_at is not None

    execution = (
        await db_session.execute(
            select(AgentExecution).where(AgentExecution.id == pending_approval["seed"]["execution"].id)
        )
    ).scalar_one()
    assert execution.status == "working", "agent must auto-resume from awaiting_user"


async def test_decide_invalid_option_returns_422(db_manager, db_session, test_user, pending_approval):
    app = _build_app(db_manager, db_session, user=test_user)
    approval_id = pending_approval["approval"].id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"option_id": "not-a-real-option"},
        )

    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"


async def test_decide_already_decided_returns_409(db_manager, db_session, test_user, pending_approval):
    app = _build_app(db_manager, db_session, user=test_user)
    approval_id = pending_approval["approval"].id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"option_id": "approve"},
        )
        assert first.status_code == 200

        second = await client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"option_id": "approve"},
        )

    assert second.status_code == 409, f"expected 409, got {second.status_code}: {second.text}"


async def test_decide_cross_tenant_returns_404(db_manager, db_session, test_user, pending_approval):
    other_tenant_key = TenantManager.generate_tenant_key()
    org_b = Organization(
        name=f"Other Org {uuid4().hex[:6]}",
        slug=f"other-org-{uuid4().hex[:6]}",
        tenant_key=other_tenant_key,
        is_active=True,
    )
    db_session.add(org_b)
    await db_session.flush()
    user_b = User(
        username=f"other_user_{uuid4().hex[:6]}",
        email=f"other_{uuid4().hex[:6]}@example.com",
        tenant_key=other_tenant_key,
        role="developer",
        password_hash="hashed_password",
        org_id=org_b.id,
    )
    db_session.add(user_b)
    await db_session.commit()
    await db_session.refresh(user_b)

    app = _build_app(db_manager, db_session, user=user_b)
    approval_id = pending_approval["approval"].id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"option_id": "approve"},
        )

    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"

    with tenant_session_context(db_session, test_user.tenant_key):
        row = (await db_session.execute(select(UserApproval).where(UserApproval.id == approval_id))).scalar_one()
    assert row.status == "pending", "cross-tenant attempt must not mutate"
    assert row.decided_option_id is None




async def test_list_pending_returns_tenant_rows(db_manager, db_session, test_user, pending_approval):
    app = _build_app(db_manager, db_session, user=test_user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/approvals/?status=pending")

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["count"] >= 1
    assert body["total"] >= 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    ids = [item["id"] for item in body["items"]]
    assert pending_approval["approval"].id in ids
    for item in body["items"]:
        assert item["tenant_key"] == test_user.tenant_key
        assert item["status"] == "pending"


async def test_list_pending_excludes_other_tenants(db_manager, db_session, test_user, pending_approval):
    other_tenant_key = TenantManager.generate_tenant_key()
    org_b = Organization(
        name=f"Other Org {uuid4().hex[:6]}",
        slug=f"other-org-{uuid4().hex[:6]}",
        tenant_key=other_tenant_key,
        is_active=True,
    )
    db_session.add(org_b)
    await db_session.flush()
    user_b = User(
        username=f"other_user_{uuid4().hex[:6]}",
        email=f"other_{uuid4().hex[:6]}@example.com",
        tenant_key=other_tenant_key,
        role="developer",
        password_hash="hashed_password",
        org_id=org_b.id,
    )
    db_session.add(user_b)
    await db_session.commit()
    await db_session.refresh(user_b)

    app = _build_app(db_manager, db_session, user=user_b)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/approvals/?status=pending")

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["count"] == 0
    assert body["total"] == 0
    assert body["items"] == []


async def test_list_rejects_unsupported_status(db_manager, db_session, test_user, pending_approval):
    app = _build_app(db_manager, db_session, user=test_user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/approvals/?status=bogus")

    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"


async def test_list_decided_status_returns_decided_rows_with_channel(
    db_manager, db_session, test_user, pending_approval
):
    app = _build_app(db_manager, db_session, user=test_user)
    approval_id = pending_approval["approval"].id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        decided_resp = await client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"option_id": "approve"},
        )
        assert decided_resp.status_code == 200

        list_resp = await client.get("/api/approvals/?status=decided")

    assert list_resp.status_code == 200, f"expected 200, got {list_resp.status_code}: {list_resp.text}"
    body = list_resp.json()
    items = {item["id"]: item for item in body["items"]}
    assert approval_id in items, "the decided row must be readable via status=decided"
    assert items[approval_id]["status"] == "decided"
    assert items[approval_id]["decided_via"] == "ui", "the REST/dashboard door decided this"
    assert items[approval_id]["decided_by_user_id"] == str(test_user.id)


async def test_list_excludes_decided_rows(db_manager, db_session, test_user, pending_approval):
    app = _build_app(db_manager, db_session, user=test_user)
    approval_id = pending_approval["approval"].id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        decided_resp = await client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"option_id": "approve"},
        )
        assert decided_resp.status_code == 200

        list_resp = await client.get("/api/approvals/?status=pending")

    assert list_resp.status_code == 200
    ids = [item["id"] for item in list_resp.json()["items"]]
    assert approval_id not in ids


async def test_list_requires_auth_dependency(db_manager, db_session, pending_approval):
    app = _build_app(db_manager, db_session, user=None)
    list_route = next(
        (route for route in iter_effective_routes(app.routes) if route.path == "/api/approvals/"),
        None,
    )
    assert list_route is not None, "list route missing from app router"

    def _depends_on_auth(dependant) -> bool:
        if dependant.call is get_current_active_user:
            return True
        return any(_depends_on_auth(child) for child in (dependant.dependencies or []))

    assert _depends_on_auth(list_route.dependant), (
        "AUTH GATE MISSING: list endpoint does not inject get_current_active_user"
    )




async def test_decide_unauthenticated_returns_401_canonical_envelope(db_manager, db_session):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(approvals_router, prefix="/api/approvals")

    async def _override_db_session():
        async with db_manager.get_session_async() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/approvals/{uuid4()}/decide",
            json={"option_id": "approve"},
        )

    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert set(body.keys()) >= {"error_code", "message", "timestamp"}, (
        f"401 envelope missing canonical keys; got keys={sorted(body.keys())}"
    )
    assert body["error_code"] == "HTTP_ERROR"
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["timestamp"], str)


async def test_decide_already_decided_returns_structured_error_envelope(
    db_manager, db_session, test_user, pending_approval
):
    app = _build_app(db_manager, db_session, user=test_user)
    register_exception_handlers(app)
    approval_id = pending_approval["approval"].id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"option_id": "approve"},
        )
        assert first.status_code == 200
        second = await client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"option_id": "approve"},
        )

    assert second.status_code == 409, f"expected 409, got {second.status_code}: {second.text}"
    body = second.json()
    assert body["error_code"] == "APPROVAL_ALREADY_DECIDED", f"expected structured error code, got body={body!r}"
    assert body.get("message")
    assert "timestamp" in body
