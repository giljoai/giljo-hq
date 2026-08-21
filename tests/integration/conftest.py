# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Integration test fixtures for Handover 0316
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import User
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    """Create test user with tenant"""
    from giljo_mcp.models.organizations import Organization

    unique_suffix = uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()  # 0424m: Generate before org creation

    # Create org first (0424m: org_id is NOT NULL, tenant_key required)
    org = Organization(
        name=f"Test User Org {unique_suffix}",
        slug=f"test-user-org-{unique_suffix}",
        tenant_key=tenant_key,  # 0424m: Required NOT NULL
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        username=f"testuser_{unique_suffix}",
        email=f"test_{uuid4().hex[:8]}@example.com",
        tenant_key=tenant_key,  # 0424m: Use same tenant_key
        role="developer",
        password_hash="hashed_password",
        org_id=org.id,  # Required after 0424j
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture(autouse=True)
def set_tenant_context(test_user: User):
    """Ensure TenantManager is set to the primary test user's tenant."""
    TenantManager.set_current_tenant(test_user.tenant_key)
    return test_user.tenant_key


# In-process MCP transport (avoids TCP port + auth middleware) -- the SDK's
# create_connected_server_and_client_session wires the FastMCP instance to a
# ClientSession via in-memory streams. Fixture yields an async context manager
# (not the session directly) so anyio task-group setup/teardown stays inside
# one coroutine task, sidestepping pytest-asyncio's "exit cancel scope in a
# different task" finalization bug.
@pytest_asyncio.fixture
async def mcp_client(db_manager):
    """Yield an async context manager that produces an initialized MCP ClientSession."""
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import mcp
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    try:
        yield create_connected_server_and_client_session(mcp)
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager
