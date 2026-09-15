# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentTemplate, Product, Project, User
from giljo_mcp.models.auth import UserFieldPriority
from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator
from tests.services.conftest import create_test_org


@pytest.mark.asyncio
async def test_thin_prompt_contains_core_structure(db_session: AsyncSession):
    unique_id = str(uuid4())[:8]
    tenant_key = f"test_tenant_{unique_id}"

    org = await create_test_org(db_session, tenant_key, unique_id)

    product = Product(
        id=str(uuid4()),
        name=f"Test Product {unique_id}",
        tenant_key=tenant_key,
    )
    db_session.add(product)

    user = User(
        id=str(uuid4()),
        username=f"testuser_{unique_id}",
        tenant_key=tenant_key,
        org_id=org.id,
    )
    db_session.add(user)

    for category in ["agent_templates", "tech_stack"]:
        db_session.add(
            UserFieldPriority(
                user_id=user.id,
                tenant_key=tenant_key,
                category=category,
                enabled=True,
            )
        )

    project = Project(
        id=str(uuid4()),
        name=f"Test Project {unique_id}",
        product_id=product.id,
        tenant_key=tenant_key,
        description="Test project description",
        mission="Test project mission",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)

    templates_data = [
        {
            "name": "implementer",
            "role": "Backend implementation specialist",
            "description": "Implements backend features",
            "meta_data": {
                "capabilities": ["Python", "FastAPI", "SQLAlchemy"],
                "expertise": ["API design", "database schema"],
                "typical_tasks": ["Implement features", "write service methods"],
            },
        },
        {
            "name": "tester",
            "role": "Quality assurance specialist",
            "description": "Writes and runs tests",
            "meta_data": {
                "capabilities": ["pytest", "integration testing"],
                "expertise": ["Test suite design", "coverage analysis"],
                "typical_tasks": ["Write unit tests", "create integration tests"],
            },
        },
        {
            "name": "documenter",
            "role": "Documentation specialist",
            "description": "Creates documentation",
            "meta_data": {
                "capabilities": ["Markdown", "technical writing"],
                "expertise": ["User guides", "API documentation"],
                "typical_tasks": ["Write docs", "create tutorials"],
            },
        },
    ]

    for template_data in templates_data:
        template = AgentTemplate(
            tenant_key=tenant_key,
            product_id=product.id,
            name=template_data["name"],
            role=template_data["role"],
            category="role",
            description=template_data["description"],
            system_instructions=f"System instructions for {template_data['name']}",
            meta_data=template_data["meta_data"],
        )
        db_session.add(template)

    await db_session.commit()

    generator = ThinClientPromptGenerator(db=db_session, tenant_key=tenant_key)
    field_toggles = {"agent_templates": True, "tech_stack": True}
    result = await generator.generate(project_id=project.id, user_id=user.id, field_toggles=field_toggles)
    thin_prompt = result["thin_prompt"]

    assert "IDENTITY:" in thin_prompt, "IDENTITY section missing from thin prompt"
    assert "MCP CONNECTION:" in thin_prompt, "MCP CONNECTION section missing from thin prompt"
    assert "YOUR ROLE:" in thin_prompt, "YOUR ROLE section missing from thin prompt"

    assert "get_staging_instructions" in thin_prompt, (
        "Thin prompt should reference get_staging_instructions MCP tool for context fetching"
    )

    identity_index = thin_prompt.find("IDENTITY:")
    mcp_index = thin_prompt.find("MCP CONNECTION:")
    role_index = thin_prompt.find("YOUR ROLE:")

    assert identity_index < mcp_index < role_index, (
        "Sections should be ordered: IDENTITY -> MCP CONNECTION -> YOUR ROLE"
    )


@pytest.mark.asyncio
async def test_thin_prompt_is_concise(db_session: AsyncSession):
    unique_id = str(uuid4())[:8]
    tenant_key = f"test_tenant_priority_{unique_id}"

    org = await create_test_org(db_session, tenant_key, unique_id)

    product = Product(
        id=str(uuid4()),
        name=f"Priority Test Product {unique_id}",
        tenant_key=tenant_key,
    )
    db_session.add(product)

    user = User(
        id=str(uuid4()),
        username=f"priorityuser_{unique_id}",
        tenant_key=tenant_key,
        org_id=org.id,
    )
    db_session.add(user)

    project = Project(
        id=str(uuid4()),
        name=f"Priority Test Project {unique_id}",
        product_id=product.id,
        tenant_key=tenant_key,
        description="Priority test description",
        mission="Priority test mission",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)

    template = AgentTemplate(
        tenant_key=tenant_key,
        product_id=product.id,
        name="implementer",
        role="Backend implementation specialist",
        category="role",
        description="Full metadata template",
        system_instructions="System instructions",
        meta_data={
            "capabilities": ["Python", "FastAPI"],
            "expertise": ["API design", "database schema"],
            "typical_tasks": ["Implement features", "write service methods"],
        },
    )
    db_session.add(template)
    await db_session.commit()

    generator = ThinClientPromptGenerator(db=db_session, tenant_key=tenant_key)

    db_session.add(
        UserFieldPriority(
            user_id=user.id,
            tenant_key=tenant_key,
            category="agent_templates",
            enabled=True,
        )
    )
    await db_session.commit()

    field_toggles_p1 = {"agent_templates": True}
    result_p1 = await generator.generate(project_id=project.id, user_id=user.id, field_toggles=field_toggles_p1)

    thin_prompt = result_p1["thin_prompt"]

    assert len(thin_prompt) < 5000, f"Thin prompt should be concise, got {len(thin_prompt)} chars"

    assert "get_staging_instructions" in thin_prompt, (
        "Thin prompt should reference get_staging_instructions for context fetching"
    )

    assert "API design" not in thin_prompt, "Agent expertise should NOT be embedded in thin prompt"
    assert "Implement features" not in thin_prompt, "Agent typical_tasks should NOT be embedded in thin prompt"
