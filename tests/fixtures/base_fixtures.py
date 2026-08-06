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
from giljo_mcp.models import Project
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
    """Create a test project"""
    tenant_key = TestData.generate_tenant_key()
    project_data = TestData.generate_project_data(tenant_key)

    project = Project(**project_data)
    db_session.add(project)
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_key
    await db_session.refresh(project)

    return project


# Note: Synchronous database fixtures have been removed.
# All tests should use async PostgreSQL fixtures for consistency with production.
# If you have synchronous tests, they should be migrated to async.
