# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import contextlib
import sys
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import Product, Project
from tests.helpers.test_db_helper import (
    PostgreSQLTestHelper,
    TransactionalTestContext,
)


_worker_schema_ready: set[str] = set()


@contextlib.contextmanager
def restored_app_state():
    from api.app_state import state
    from giljo_mcp.app_registry import service_registry

    registered_ws_manager = service_registry.get_websocket_manager()
    original = dict(vars(state))
    contents = {name: value.copy() for name, value in original.items() if isinstance(value, (dict, list))}
    app_module = sys.modules.get("api.app")
    fastapi_state = dict(app_module.app.state._state) if app_module is not None else None
    try:
        yield state
    finally:
        for name in set(vars(state)) - set(original):
            delattr(state, name)
        for name, value in original.items():
            if name in contents:
                value.clear()
                if isinstance(value, dict):
                    value.update(contents[name])
                else:
                    value.extend(contents[name])
            setattr(state, name, value)
        if fastapi_state is not None:
            app_module.app.state._state.clear()
            app_module.app.state._state.update(fastapi_state)
        service_registry.set_websocket_manager(registered_ws_manager)


@contextlib.contextmanager
def restored_global_wake_relay():
    from giljo_mcp.services.agent_wake_registry import get_wake_registry

    registry = get_wake_registry()
    original = registry._relay
    try:
        yield registry
    finally:
        registry.set_relay(original)


@contextlib.contextmanager
def restored_global_client_resolver():
    from giljo_mcp.services.oauth_service import get_client_resolver, set_client_resolver

    original = get_client_resolver()
    try:
        yield
    finally:
        set_client_resolver(original)


@contextlib.contextmanager
def restored_global_terms_accepted_check():
    import giljo_mcp.auth.dependencies as dependencies_mod

    original = dependencies_mod._terms_accepted_check
    try:
        yield
    finally:
        dependencies_mod._terms_accepted_check = original


class TestData:

    @staticmethod
    def generate_tenant_key() -> str:
        from giljo_mcp.tenant import TenantManager

        return TenantManager.generate_tenant_key()

    @staticmethod
    def generate_project_data(tenant_key: str) -> dict[str, Any]:
        import random

        return {
            "id": str(uuid.uuid4()),
            "name": f"Test Project {uuid.uuid4().hex[:8]}",
            "description": "Test project description for automated testing",
            "mission": "Test mission for automated testing",
            "status": "active",
            "tenant_key": tenant_key,
            "metadata": {"test": True},
            "series_number": random.randint(1, 9000),
        }

    @staticmethod
    def generate_agent_job_data(
        project_id: str, tenant_key: str, agent_display_name: str | None = None
    ) -> dict[str, Any]:
        return {
            "job_id": str(uuid.uuid4()),
            "tenant_key": tenant_key,
            "project_id": project_id,
            "job_type": agent_display_name or "worker",
            "mission": f"Test mission for {agent_display_name or 'worker'} agent",
            "status": "active",
            "created_at": datetime.now(UTC),
            "job_metadata": {},
        }

    @staticmethod
    def generate_agent_execution_data(
        job_id: str, tenant_key: str, agent_display_name: str | None = None
    ) -> dict[str, Any]:
        return {
            "agent_id": str(uuid.uuid4()),
            "job_id": job_id,
            "tenant_key": tenant_key,
            "agent_display_name": agent_display_name or "worker",
            "agent_name": f"Test {agent_display_name or 'worker'} Agent",
            "status": "waiting",
            "progress": 0,
            "messages_sent_count": 0,
            "messages_waiting_count": 0,
            "messages_read_count": 0,
            "health_status": "unknown",
            "tool_type": "universal",
        }

    @staticmethod
    def generate_message_data(from_agent: str, to_agent: str, project_id: str) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "content": "Test message content",
            "project_id": project_id,
            "created_at": datetime.now(UTC),
            "status": "waiting",
        }


@pytest_asyncio.fixture(scope="function")
async def db_manager():
    connection_string = PostgreSQLTestHelper.get_test_db_url()

    if connection_string not in _worker_schema_ready:
        await PostgreSQLTestHelper.ensure_test_database_exists()
        bootstrap = DatabaseManager(connection_string, is_async=True, use_null_pool=True)
        try:
            await PostgreSQLTestHelper.create_test_tables(bootstrap)
        finally:
            await bootstrap.close_async()
        _worker_schema_ready.add(connection_string)

    db_mgr = DatabaseManager(connection_string, is_async=True, use_null_pool=True)

    yield db_mgr

    with contextlib.suppress(Exception):
        if db_mgr and db_mgr.async_engine:
            await db_mgr.close_async()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_manager) -> AsyncGenerator[AsyncSession, None]:
    async with TransactionalTestContext(db_manager) as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def test_project(db_session) -> Project:
    tenant_key = TestData.generate_tenant_key()
    project_data = TestData.generate_project_data(tenant_key)

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Test Product {uuid.uuid4().hex[:8]}",
        description="Owning product for the test project fixture",
        is_active=False,
    )
    db_session.add(product)
    await db_session.flush()
    project_data["product_id"] = product.id

    project = Project(**project_data)
    db_session.add(project)
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_key
    await db_session.refresh(project)

    return project




@contextlib.contextmanager
def restored_global_protected_surface_patterns():
    import giljo_mcp.services.job_completion_closeout_gate as gate

    original = gate._edition_patterns
    try:
        yield
    finally:
        gate._edition_patterns = original
