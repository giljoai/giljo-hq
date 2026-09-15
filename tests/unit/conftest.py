# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.orm import Session

from giljo_mcp.models import AgentTemplate, Product
from giljo_mcp.models.products import ProductArchitecture, ProductTechStack, ProductTestConfig


@pytest.fixture
def mock_db_manager():
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
    session.info = {}
    db_manager.get_session_async = Mock(return_value=session)
    db_manager.get_tenant_session_async = Mock(return_value=session)
    return db_manager, session


@pytest.fixture
def mock_tenant_manager():
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
        tool="claude",
    )


    db.add(template)
    db.commit()
    db.refresh(template)
    return template




@pytest.fixture
def sample_product():
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




def make_mock_session(**overrides):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = Mock()
    session.info = {}

    for key, value in overrides.items():
        setattr(session, key, value)
    return session


def make_mock_db_manager(session):
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    return db_manager
