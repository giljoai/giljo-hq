# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Base test fixtures for Giljo HQ test suite.
Provides reusable fixtures for database, models, and common test data.

All tests now use PostgreSQL for consistency with production.
Test isolation is achieved through transaction rollback.
"""

import contextlib
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


# Per-worker schema bootstrap guard. Under pytest-xdist each worker is a
# separate process with its OWN database (giljo_mcp_test_gwN), so the schema is
# built exactly once per worker — before its first test — and never raced
# against by sibling workers. Keyed by connection string so it is correct even
# if a worker ever sees more than one test DB URL. A set (mutated in place)
# avoids a module-level ``global`` statement.
_worker_schema_ready: set[str] = set()


@contextlib.contextmanager
def restored_global_wake_relay():
    """Snapshot the process-global agent-wake relay and put it back on exit.

    The relay is process-global state (``agent_wake_registry._registry``), and one
    layer installs it without any way for a caller to inject its own registry:
    ``init_websocket_broker`` calls ``install_wake_relay`` with no ``registry``
    argument, so a startup test exercising the multi-worker path mutates the
    global and has no seam to avoid it. This is the containment.

    Snapshot-and-restore rather than ``registry.reset()``: reset also drops
    waiters, which would clear a parked waiter out from under a test that owns it.

    Lives here (not inline in the autouse fixture) so the fixture and its own
    regression test drive the SAME code, instead of the test re-implementing the
    behaviour it is supposed to be gating.
    """
    from giljo_mcp.services.agent_wake_registry import get_wake_registry

    registry = get_wake_registry()
    original = registry._relay
    try:
        yield registry
    finally:
        registry.set_relay(original)


@contextlib.contextmanager
def restored_global_client_resolver():
    """Pin the CE built-in OAuth client resolver for the test, then put back what it found.

    ``oauth_service`` keeps the active resolver in a module global. SaaS startup
    installs an ASYNC, DB-backed one process-wide (``install_saas_resolver``, reached
    from ``register_saas_routes`` whenever an app is built with GILJO_MODE=saas), and
    that install has no teardown — it is a startup action, correctly so in production.
    A test that builds such an app therefore leaves the async resolver installed for
    every later test in that worker process.

    The victim was ``test_oauth_resolver_seam.py::test_get_client_resolver_returns_callable``,
    which calls the resolver synchronously and reads an attribute off the result::

        AttributeError: 'coroutine' object has no attribute 'client_id'

    Snapshot-and-restore, NOT force-pin-the-builtin. Pinning was the first thing I
    wrote and it is wrong: a module- or class-scoped fixture that installs a resolver
    runs at a HIGHER scope than this function-scoped one, so pinning would clobber a
    deliberate install before each test in that module and break tests that are doing
    nothing wrong. Restoring what was there contains the leak at the test that caused
    it — which is all that is needed — and changes the starting state of nothing.
    """
    from giljo_mcp.services.oauth_service import get_client_resolver, set_client_resolver

    original = get_client_resolver()
    try:
        yield
    finally:
        set_client_resolver(original)


class TestData:
    """Common test data and utilities"""

    @staticmethod
    def generate_tenant_key() -> str:
        """Generate a test tenant key"""
        from giljo_mcp.tenant import TenantManager

        return TenantManager.generate_tenant_key()

    @staticmethod
    def generate_project_data(tenant_key: str) -> dict[str, Any]:
        """Generate test project data"""
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
        """
        Generate test AgentJob data (work order - the WHAT).

        Migration Note (0367d): Replaced MCPAgentJob with AgentJob.
        Returns AgentJob data dictionary.
        """
        return {
            "job_id": str(uuid.uuid4()),
            "tenant_key": tenant_key,
            "project_id": project_id,
            "job_type": agent_display_name or "worker",
            "mission": f"Test mission for {agent_display_name or 'worker'} agent",
            "status": "active",  # AgentJob has 3 statuses: active/completed/cancelled
            "created_at": datetime.now(UTC),
            "job_metadata": {},
        }

    @staticmethod
    def generate_agent_execution_data(
        job_id: str, tenant_key: str, agent_display_name: str | None = None
    ) -> dict[str, Any]:
        """
        Generate test AgentExecution data (executor - the WHO).

        Migration Note (0367d): Extracted from AgentExecution.
        Returns AgentExecution data dictionary.
        """
        return {
            "agent_id": str(uuid.uuid4()),
            "job_id": job_id,
            "tenant_key": tenant_key,
            "agent_display_name": agent_display_name or "worker",
            "agent_name": f"Test {agent_display_name or 'worker'} Agent",
            "status": "waiting",  # AgentExecution has 7 statuses
            "progress": 0,
            "messages_sent_count": 0,
            "messages_waiting_count": 0,
            "messages_read_count": 0,
            "health_status": "unknown",
            "tool_type": "universal",
        }

    @staticmethod
    def generate_message_data(from_agent: str, to_agent: str, project_id: str) -> dict[str, Any]:
        """Generate test message data"""
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
    """
    Function-scoped PostgreSQL database manager (per-worker database).

    The schema is built exactly once per worker process (first test), then each
    test gets a manager backed by a tiny connection pool. Per-test isolation
    comes from TransactionalTestContext (rollback) — tables are NOT recreated
    per test. Uses a fresh manager per test to avoid event-loop issues.
    """
    connection_string = PostgreSQLTestHelper.get_test_db_url()

    if connection_string not in _worker_schema_ready:
        # Create the per-worker DB + required extensions, then build the schema
        # ONCE. Deliberately NOT wrapped in suppress(): a real DDL/connection
        # failure must surface loudly rather than leave every later test in this
        # worker querying a table that was never created (the old shared-DB race
        # hid exactly this behind contextlib.suppress(Exception)).
        await PostgreSQLTestHelper.ensure_test_database_exists()
        bootstrap = DatabaseManager(connection_string, is_async=True, use_null_pool=True)
        try:
            await PostgreSQLTestHelper.create_test_tables(bootstrap)
        finally:
            await bootstrap.close_async()
        _worker_schema_ready.add(connection_string)

    db_mgr = DatabaseManager(connection_string, is_async=True, use_null_pool=True)

    yield db_mgr

    # Cleanup - ensure proper async disposal
    with contextlib.suppress(Exception):
        if db_mgr and db_mgr.async_engine:
            await db_mgr.close_async()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_manager) -> AsyncGenerator[AsyncSession, None]:
    """
    Get database session for testing with transaction isolation.

    Each test runs in a transaction that is rolled back at the end,
    ensuring clean state between tests.
    """
    async with TransactionalTestContext(db_manager) as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def test_project(db_session) -> Project:
    """Create a test project.

    BE-9437: ``projects.product_id`` is NOT NULL, so this seeds an owning product
    first. Its OWN product, because the project is ACTIVE and
    ``idx_project_single_active_per_product`` permits one active project per
    product -- sharing one with another fixture would collide for a reason
    unrelated to whatever the test is checking.
    """
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


# Note: Synchronous database fixtures have been removed.
# All tests should use async PostgreSQL fixtures for consistency with production.
# If you have synchronous tests, they should be migrated to async.
