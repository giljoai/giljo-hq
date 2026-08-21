# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Pytest configuration for API endpoint tests.

Provides fixtures specific to API integration testing including:
- Async API client with authentication support
- Database session with proper isolation
- Authentication headers for protected endpoints
- Automatic database cleanup between tests to prevent pollution
"""

import secrets
from unittest.mock import MagicMock

import bcrypt
import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient


# Shared CSRF token for test fixtures (double-submit cookie pattern)
_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


# Override parent conftest autouse fixtures that open db_session transactions.
# API tests use db_manager directly via their own fixtures (api_client, auth_headers)
# and don't need the agent_coordination/project_tools/context module injections.
# These open transactions cause deadlocks with the cleanup fixture (Handover 0495).
@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_agent_coordination():
    """No-op override for API tests (parent conftest opens db_session transactions)."""
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_context_module():
    """No-op override for API tests (parent conftest opens db_session transactions)."""
    yield


@pytest_asyncio.fixture(scope="function")
async def api_client(db_manager):
    """
    Create AsyncClient for API testing with proper dependency overrides and auth setup.

    This fixture:
    - Uses httpx.AsyncClient for async API testing
    - Mocks authentication dependencies for testing
    - Provides proper database session isolation
    - Sets up AuthManager in app state
    - Cleans up dependency overrides after tests
    - CRITICAL: Each test gets a fresh client to prevent cookie persistence
    - CRITICAL: Cleans up database tables after each test to prevent pollution

    Usage:
        async def test_endpoint(api_client: AsyncClient):
            response = await api_client.get("/api/v1/endpoint")
            assert response.status_code == 200
    """
    from api.app import app
    from api.app_state import state
    from giljo_mcp.auth import AuthManager
    from giljo_mcp.auth.dependencies import get_db_session
    from giljo_mcp.tenant import TenantManager

    async def mock_get_db_session():
        """Provide test database session."""
        async with db_manager.get_session_async() as session:
            yield session

    # Override database session dependency
    app.dependency_overrides[get_db_session] = mock_get_db_session

    # Ensure global state has db_manager and tenant_manager for services like TemplateService
    state.db_manager = db_manager
    app.state.db_manager = db_manager
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    # Set up tool_accessor for message endpoints
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    app.state.tool_accessor = state.tool_accessor

    # Create mock config for AuthManager and state.config
    mock_config = MagicMock()
    mock_config.jwt.secret_key = "test_secret_key"
    mock_config.jwt.algorithm = "HS256"
    mock_config.jwt.expiration_minutes = 30
    mock_config.get = MagicMock(
        side_effect=lambda key, default=None: {
            "security.auth_enabled": True,
            "security.api_keys_required": False,
        }.get(key, default)
    )

    # Set up config in state (for endpoints that use state.config)
    state.config = mock_config
    app.state.config = mock_config

    # Set up auth manager in both app.state and module-level state used by middleware
    app.state.auth = AuthManager(mock_config, db=None)
    state.auth = app.state.auth

    # Create async client with ASGI transport
    # CRITICAL FIX: Use follow_redirects=True to prevent cookie persistence issues
    # Each test gets a completely isolated client instance
    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(
        transport=transport,
        base_url="http://test",
        cookies=None,  # Explicitly no cookies to start
        follow_redirects=True,
    ) as client:
        # Clear any cookies before yielding to test
        client.cookies.clear()
        yield client
        # Clear cookies after test completes to ensure no leakage
        client.cookies.clear()

    # Clear overrides after test
    app.dependency_overrides.clear()
    if hasattr(app.state, "auth"):
        del app.state.auth


@pytest_asyncio.fixture(scope="function")
async def auth_headers(db_manager, api_client) -> dict:
    """
    Create authentication headers for API tests.

    This fixture:
    - Creates a test user in the database
    - Generates a valid JWT token
    - Returns Authorization header dict for authenticated requests

    Usage:
        async def test_endpoint(api_client: AsyncClient, auth_headers: dict):
            response = await api_client.post(
                "/api/download/generate-token",
                headers=auth_headers,
                json={"content_type": "slash_commands"}
            )
            assert response.status_code == 201

    Returns:
        dict: {"Cookie": "access_token=<token>; csrf_token=<csrf>", "X-CSRF-Token": "<csrf>"}
    """

    # Create a unique test user for each test run (prevents fixture collisions)
    from uuid import uuid4

    from giljo_mcp.auth.jwt_manager import JWTManager
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    async with db_manager.get_session_async() as session:
        # Create test user with unique username to avoid conflicts
        unique_suffix = uuid4().hex[:8]
        username = f"test_user_{unique_suffix}"

        # Generate valid tenant key (tk_ + 32 chars)
        tenant_key = TenantManager.generate_tenant_key()

        # Create test user with password hash (models.User uses password_hash + role)
        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")

        # Create org first (0424m: org_id is NOT NULL, tenant_key required)
        org = Organization(
            name=f"Test Org {unique_suffix}",
            slug=f"test-org-{unique_suffix}",
            tenant_key=tenant_key,  # 0424m: Required NOT NULL
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=username,
            email=f"test_{unique_suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.commit()

        # Generate token for the user
        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=user.tenant_key,
        )

        # Use Cookie header because dependencies expect JWT in cookie 'access_token'
        # Include CSRF token in both cookie and header for double-submit pattern (0765f)
        return {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
