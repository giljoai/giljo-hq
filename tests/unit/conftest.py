# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Shared pytest fixtures for unit tests (Handover 0605-0608)

Provides correctly configured mocks for async database operations.
Also provides synchronous DB fixtures for template validation tests.
"""

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.orm import Session

from giljo_mcp.models import AgentTemplate, Product
from giljo_mcp.models.products import ProductArchitecture, ProductTechStack, ProductTestConfig


@pytest.fixture
def mock_db_manager():
    """
    Create properly configured mock database manager.

    Returns tuple of (db_manager, session) where session is an async
    context manager that can be used with 'async with' statements.

    Example:
        db_manager, session = mock_db_manager
        service = MyService(db_manager, tenant_manager)
        # session is automatically configured as async context manager
    """
    db_manager = Mock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = Mock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    db_manager.get_session_async = Mock(return_value=session)
    db_manager.get_tenant_session_async = Mock(return_value=session)
    return db_manager, session


@pytest.fixture
def mock_tenant_manager():
    """
    Create mock tenant manager with default test tenant.

    Returns a tenant manager that returns "test-tenant" by default.
    Override in tests by setting:
        tenant_manager.get_current_tenant = Mock(return_value="other-tenant")
    """
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value="test-tenant")
    return tenant_manager


def create_test_template(
    db: Session,
    tenant_key: str,
    name: str = "test-agent",
    role: str = "implementer",
    is_active: bool = False,
    system_prompt: str = "Test system prompt with enough characters to be valid",
) -> AgentTemplate:
    """Create test agent template in database."""
    # Create template with only fields that exist in current DB schema
    template = AgentTemplate(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=name,
        role=role,
        category="role",
        system_instructions=system_prompt,
        is_active=is_active,
        variables=[],
        behavioral_rules=[],
        success_criteria=[],
        tool="claude",  # Default tool
    )

    # Don't set new 0103 fields if they don't exist in DB yet
    # (cli_tool, background_color, model, tools columns may not be migrated)

    db.add(template)
    db.commit()
    db.refresh(template)
    return template


# --- Context manager test fixtures (split from test_context_manager.py) ---


@pytest.fixture
def sample_product():
    """Create sample product with normalized config relations (0840c)"""
    product = Product(
        id="test-product-1",
        tenant_key="test-tenant",
        name="Test Product",
    )
    product.core_features = "Multi-tenant, Agent coordination"
    product.tech_stack = ProductTechStack(
        product_id="test-product-1",
        tenant_key="test-tenant",
        programming_languages="Python 3.11",
        frontend_frameworks="Vue 3",
        backend_frameworks="FastAPI",
        databases_storage="PostgreSQL 18",
    )
    product.architecture = ProductArchitecture(
        product_id="test-product-1",
        tenant_key="test-tenant",
        primary_pattern="FastAPI + PostgreSQL",
        design_patterns="Repository, Service",
        api_style="REST",
        architecture_notes="Multi-tenant orchestration system",
    )
    product.test_config = ProductTestConfig(
        product_id="test-product-1",
        tenant_key="test-tenant",
        quality_standards="80% coverage",
        test_strategy="TDD",
        coverage_target=80,
        testing_frameworks="pytest",
    )
    return product


# --- Template service shared helpers (split from test_template_service.py) ---


def make_mock_session(**overrides):
    """Create a properly configured mock async session.

    The session is configured as an async context manager that returns itself
    when used with ``async with``. All standard session methods (execute,
    commit, refresh, add, delete) are set up with sensible defaults.

    ``overrides`` can supply replacement mocks for any session attribute
    (e.g. ``execute=AsyncMock(return_value=my_result)``).
    """
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = Mock()
    session.info = {}  # tenant_session_context save/restore target

    for key, value in overrides.items():
        setattr(session, key, value)
    return session


def make_mock_db_manager(session):
    """Create a mock database manager that returns *session* from get_session_async."""
    db_manager = Mock()
    # get_session_async must be a plain Mock (NOT AsyncMock) so the caller
    # receives the context-manager directly rather than a coroutine wrapper.
    db_manager.get_session_async = Mock(return_value=session)
    return db_manager
