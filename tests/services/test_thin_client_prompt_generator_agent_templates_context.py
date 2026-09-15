# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentTemplate, Product, Project, User
from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator
from tests.services.conftest import create_test_org


@pytest.mark.asyncio
async def test_thin_prompt_token_estimation(db_session: AsyncSession):
    unique_id = str(uuid4())[:8]
    tenant_key = f"test_tenant_tokens_{unique_id}"

    org = await create_test_org(db_session, tenant_key, unique_id)

    product = Product(
        id=str(uuid4()),
        name=f"Token Test Product {unique_id}",
        tenant_key=tenant_key,
    )
    db_session.add(product)

    user = User(
        id=str(uuid4()),
        username=f"tokenuser_{unique_id}",
        tenant_key=tenant_key,
        org_id=org.id,
    )
    db_session.add(user)

    project = Project(
        id=str(uuid4()),
        name=f"Token Test Project {unique_id}",
        product_id=product.id,
        tenant_key=tenant_key,
        description="Token test description",
        mission="Token test mission",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)

    template = AgentTemplate(
        tenant_key=tenant_key,
        product_id=product.id,
        name="implementer",
        role="Backend implementation specialist",
        category="role",
        description="Template for token accounting test",
        system_instructions="Detailed system instructions for token accounting",
        meta_data={
            "capabilities": ["Python", "FastAPI", "SQLAlchemy", "PostgreSQL"],
            "expertise": ["API design", "database schema", "service layer architecture"],
            "typical_tasks": ["Implement features", "write service methods", "create endpoints"],
        },
    )
    db_session.add(template)
    await db_session.commit()

    generator = ThinClientPromptGenerator(db=db_session, tenant_key=tenant_key)

    result = await generator.generate(project_id=project.id, user_id=user.id, field_toggles={"agent_templates": True})

    assert "estimated_prompt_tokens" in result, "Response should include estimated_prompt_tokens"
    tokens = result["estimated_prompt_tokens"]

    assert 200 < tokens < 1500, f"Thin prompt should be ~600 tokens, got {tokens}"

    assert "thin_prompt" in result, "Response should include thin_prompt"
    assert len(result["thin_prompt"]) > 0, "thin_prompt should not be empty"


@pytest.mark.asyncio
async def test_thin_prompt_includes_project_context(db_session: AsyncSession):
    unique_id_a = str(uuid4())[:8]
    unique_id_b = str(uuid4())[:8]

    tenant_a_key = f"tenant_a_{unique_id_a}"

    org_a = await create_test_org(db_session, tenant_a_key, unique_id_a)

    product_a = Product(
        id=str(uuid4()),
        name=f"Tenant A Product {unique_id_a}",
        tenant_key=tenant_a_key,
    )
    db_session.add(product_a)

    user_a = User(
        id=str(uuid4()),
        username=f"tenant_a_user_{unique_id_a}",
        tenant_key=tenant_a_key,
        org_id=org_a.id,
    )
    db_session.add(user_a)

    project_a = Project(
        id=str(uuid4()),
        name=f"Tenant A Project {unique_id_a}",
        product_id=product_a.id,
        tenant_key=tenant_a_key,
        description="Tenant A description",
        mission="Tenant A mission",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_a)

    template_a = AgentTemplate(
        tenant_key=tenant_a_key,
        product_id=product_a.id,
        name=f"tenant_a_agent_{unique_id_a}",
        role="Tenant A Specialist",
        category="role",
        description="Tenant A exclusive agent",
        system_instructions="Tenant A system instructions",
        meta_data={"capabilities": ["Tenant A Skill"]},
    )
    db_session.add(template_a)

    tenant_b_key = f"tenant_b_{unique_id_b}"
    product_b = Product(
        id=str(uuid4()),
        name=f"Tenant B Product {unique_id_b}",
        tenant_key=tenant_b_key,
    )
    db_session.add(product_b)

    template_b = AgentTemplate(
        tenant_key=tenant_b_key,
        product_id=product_b.id,
        name=f"tenant_b_agent_{unique_id_b}",
        role="Tenant B Specialist",
        category="role",
        description="Tenant B exclusive agent",
        system_instructions="Tenant B system instructions",
        meta_data={"capabilities": ["Tenant B Skill"]},
    )
    db_session.add(template_b)

    await db_session.commit()

    generator_a = ThinClientPromptGenerator(db=db_session, tenant_key=tenant_a_key)
    result_a = await generator_a.generate(
        project_id=project_a.id, user_id=user_a.id, field_toggles={"agent_templates": True}
    )
    thin_prompt = result_a["thin_prompt"]

    assert f"Tenant A Project {unique_id_a}" in thin_prompt, "Thin prompt should contain project name"

    assert f"Tenant B Project {unique_id_b}" not in thin_prompt, (
        "Tenant B's project should NOT appear in Tenant A's thin prompt"
    )
    assert f"Tenant B Product {unique_id_b}" not in thin_prompt, (
        "Tenant B's product should NOT appear in Tenant A's thin prompt"
    )



@pytest.mark.asyncio
async def test_thin_prompt_works_without_field_toggles(db_session: AsyncSession):
    unique_id = str(uuid4())[:8]
    tenant_key = f"test_tenant_default_{unique_id}"

    org = await create_test_org(db_session, tenant_key, unique_id)

    product = Product(
        id=str(uuid4()),
        name=f"Default Priority Product {unique_id}",
        tenant_key=tenant_key,
    )
    db_session.add(product)

    user = User(
        id=str(uuid4()),
        username=f"defaultuser_{unique_id}",
        tenant_key=tenant_key,
        org_id=org.id,
    )
    db_session.add(user)

    project_name = f"Default Priority Project {unique_id}"
    project = Project(
        id=str(uuid4()),
        name=project_name,
        product_id=product.id,
        tenant_key=tenant_key,
        description="Default priority test description",
        mission="Default priority test mission",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)

    template = AgentTemplate(
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"implementer_{unique_id}",
        role="Backend implementation specialist",
        category="role",
        description="Default priority test template",
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
    result = await generator.generate(
        project_id=project.id,
        user_id=user.id,
        field_toggles=None,
    )
    thin_prompt = result["thin_prompt"]

    assert thin_prompt is not None, "Thin prompt should be generated"
    assert len(thin_prompt) > 0, "Thin prompt should not be empty"

    assert "IDENTITY:" in thin_prompt, "IDENTITY section should be present"
    assert "MCP CONNECTION:" in thin_prompt, "MCP CONNECTION section should be present"
    assert "YOUR ROLE:" in thin_prompt, "YOUR ROLE section should be present"

    assert project_name in thin_prompt, "Project name should appear in thin prompt"

    assert "get_staging_instructions" in thin_prompt, (
        "Thin prompt should reference get_staging_instructions for fetching context"
    )


@pytest.mark.asyncio
async def test_project_description_not_notes_in_context_string(db_session: AsyncSession):
    unique_id = str(uuid4())[:8]
    tenant_key = f"test_tenant_notes_bug_{unique_id}"

    org = await create_test_org(db_session, tenant_key, unique_id)

    product = Product(
        id=str(uuid4()),
        name=f"Notes Bug Test Product {unique_id}",
        tenant_key=tenant_key,
    )
    db_session.add(product)

    user = User(
        id=str(uuid4()),
        username=f"notesbuguser_{unique_id}",
        tenant_key=tenant_key,
        org_id=org.id,
    )
    db_session.add(user)

    project_description = "This is the project description field that should appear in context"
    project = Project(
        id=str(uuid4()),
        name=f"Notes Bug Test Project {unique_id}",
        product_id=product.id,
        tenant_key=tenant_key,
        description=project_description,
        mission="Test mission for notes bug",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()

    generator = ThinClientPromptGenerator(db=db_session, tenant_key=tenant_key)
    result = await generator.generate(project_id=project.id, user_id=user.id, field_toggles={})
    thin_prompt = result["thin_prompt"]

    assert thin_prompt is not None, "Thin prompt should be generated without errors"

    assert project_description in thin_prompt or "project description" in thin_prompt.lower(), (
        "Project description should appear in context string"
    )

    assert "PROJECT CONTEXT" in thin_prompt, "Context should contain PROJECT CONTEXT section"
