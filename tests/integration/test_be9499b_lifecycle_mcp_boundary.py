# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


@pytest_asyncio.fixture
async def be9499b_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed_product(db_manager, tenant_key: str, session) -> str:
    product_id = str(uuid4())
    session.add(
        Product(
            id=product_id,
            name=f"BE9499b Product {uuid4().hex[:6]}",
            description="BE-9499b lifecycle boundary test",
            tenant_key=tenant_key,
            is_active=True,
            product_memory={},
        )
    )
    return product_id


def _project(project_id: str, tenant_key: str, product_id: str, *, name: str, status: str, **kwargs) -> Project:
    return Project(
        id=project_id,
        tenant_key=tenant_key,
        product_id=product_id,
        name=name,
        description="BE-9499b lifecycle boundary test project",
        mission=kwargs.pop("mission", "test mission"),
        status=status,
        series_number=random.randint(1, 9999),
        **kwargs,
    )


async def _cleanup(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tenant_key))
        await session.execute(delete(AgentJob).where(AgentJob.tenant_key == tenant_key))
        await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.commit()


class TestActivateBypassMcpBoundary:

    async def test_activating_inactive_project_leaves_sibling_active_and_mints_fixture(
        self, be9499b_client, db_manager
    ):
        client, tenant_key = be9499b_client
        active_id, inactive_id = str(uuid4()), str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(db_manager, tenant_key, session)
            session.add(_project(active_id, tenant_key, product_id, name="Already active", status="active"))
            session.add(_project(inactive_id, tenant_key, product_id, name="To activate", status="inactive"))
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("update_project", {"project_id": inactive_id, "status": "active"})

            assert not result.is_error, f"activation must succeed: {result.content!r}"
            payload = _payload(result)
            assert payload.get("status") == "active"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                active = (await verify.execute(select(Project).where(Project.id == active_id))).scalar_one()
                target = (await verify.execute(select(Project).where(Project.id == inactive_id))).scalar_one()
                fixtures = (
                    (await verify.execute(select(AgentJob).where(AgentJob.project_id == inactive_id))).scalars().all()
                )

            assert active.status == "active", "ruling 5 amended: the sibling must stay active, not be deactivated"
            assert target.status == "active"
            assert len(fixtures) == 1, "activation via update_project must mint the orchestrator fixture"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_activating_already_active_project_is_a_harmless_noop(self, be9499b_client, db_manager):
        client, tenant_key = be9499b_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(db_manager, tenant_key, session)
            session.add(_project(project_id, tenant_key, product_id, name="Already active", status="active"))
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("update_project", {"project_id": project_id, "status": "active"})
            assert not result.is_error, f"re-activating an already-active project must not raise: {result.content!r}"
        finally:
            await _cleanup(db_manager, tenant_key)


class TestReverseGearMcpBoundary:

    async def test_unstage_reverts_staged_to_ready(self, be9499b_client, db_manager):
        client, tenant_key = be9499b_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(db_manager, tenant_key, session)
            session.add(
                _project(
                    project_id,
                    tenant_key,
                    product_id,
                    name="Staged project",
                    status="inactive",
                    staging_status="staged",
                    mission="a generated staging mission",
                )
            )
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("stage_project", {"project_id": project_id, "action": "unstage"})
            assert not result.is_error, f"unstage must succeed: {result.content!r}"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
            assert project.staging_status is None
            assert project.mission == ""
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_restage_resets_staging_and_mints_fresh_orchestrator(self, be9499b_client, db_manager):
        client, tenant_key = be9499b_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(db_manager, tenant_key, session)
            session.add(
                _project(
                    project_id,
                    tenant_key,
                    product_id,
                    name="Mid-staging project",
                    status="inactive",
                    staging_status="staging",
                    mission="an in-progress staging mission",
                )
            )
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("stage_project", {"project_id": project_id, "action": "restage"})
            assert not result.is_error, f"restage must succeed: {result.content!r}"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
                fixtures = (
                    (await verify.execute(select(AgentJob).where(AgentJob.project_id == project_id))).scalars().all()
                )
            assert project.staging_status is None
            assert project.mission == ""
            assert len(fixtures) == 1, "restage must mint a fresh orchestrator fixture"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_cancel_staging_cancels_the_project(self, be9499b_client, db_manager):
        client, tenant_key = be9499b_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(db_manager, tenant_key, session)
            session.add(
                _project(
                    project_id,
                    tenant_key,
                    product_id,
                    name="Mid-staging project",
                    status="inactive",
                    staging_status="staging",
                    mission="an in-progress staging mission",
                )
            )
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "stage_project", {"project_id": project_id, "action": "cancel_staging"}
                )
            assert not result.is_error, f"cancel_staging must succeed: {result.content!r}"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
            assert project.status == "cancelled"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_invalid_action_is_refused(self, be9499b_client, db_manager):
        client, tenant_key = be9499b_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(db_manager, tenant_key, session)
            session.add(_project(project_id, tenant_key, product_id, name="Any project", status="inactive"))
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("stage_project", {"project_id": project_id, "action": "purge"})
            assert not result.is_error and "VALIDATION_ERROR" in _payload(result).get("error", "")
        finally:
            await _cleanup(db_manager, tenant_key)


class TestReviveCompletedProjectMcpBoundary:

    async def test_reviving_completed_project_via_update_project(self, be9499b_client, db_manager):
        client, tenant_key = be9499b_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(db_manager, tenant_key, session)
            session.add(
                _project(
                    project_id,
                    tenant_key,
                    product_id,
                    name="Finished project",
                    status="completed",
                )
            )
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("update_project", {"project_id": project_id, "status": "inactive"})
            assert not result.is_error, f"revival must succeed: {result.content!r}"
            payload = _payload(result)
            assert payload.get("status") == "inactive"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
            assert project.status == "inactive"
            assert project.completed_at is None
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_reviving_completed_project_directly_to_active(self, be9499b_client, db_manager):
        client, tenant_key = be9499b_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(db_manager, tenant_key, session)
            session.add(
                _project(
                    project_id,
                    tenant_key,
                    product_id,
                    name="Finished project",
                    status="completed",
                )
            )
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("update_project", {"project_id": project_id, "status": "active"})
            assert not result.is_error, f"revive+activate must succeed: {result.content!r}"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
                fixtures = (
                    (await verify.execute(select(AgentJob).where(AgentJob.project_id == project_id))).scalars().all()
                )
            assert project.status == "active"
            assert len(fixtures) == 1
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_update_project_on_cancelled_project_still_refused(self, be9499b_client, db_manager):
        client, tenant_key = be9499b_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(db_manager, tenant_key, session)
            session.add(_project(project_id, tenant_key, product_id, name="Cancelled project", status="cancelled"))
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("update_project", {"project_id": project_id, "status": "inactive"})
            assert result.is_error, "a cancelled project must still be refused (no revival door for it)"
        finally:
            await _cleanup(db_manager, tenant_key)
