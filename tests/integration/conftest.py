# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import User
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    from giljo_mcp.models.organizations import Organization

    unique_suffix = uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()

    org = Organization(
        name=f"Test User Org {unique_suffix}",
        slug=f"test-user-org-{unique_suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        username=f"testuser_{unique_suffix}",
        email=f"test_{uuid4().hex[:8]}@example.com",
        tenant_key=tenant_key,
        role="developer",
        password_hash="hashed_password",
        org_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture(autouse=True)
def set_tenant_context(test_user: User):
    TenantManager.set_current_tenant(test_user.tenant_key)
    return test_user.tenant_key


@pytest_asyncio.fixture
async def mcp_client(db_manager):
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
