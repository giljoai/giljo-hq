# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.models.templates import AgentTemplate, TemplateArchive




@pytest.mark.asyncio
async def test_get_template_by_id_success(db_session, template_service, test_tenant_key, sample_template):
    result = await template_service.get_template_by_id(db_session, sample_template.id, test_tenant_key)

    assert result is not None
    assert result.id == sample_template.id
    assert result.name == "test-analyzer"


@pytest.mark.asyncio
async def test_get_template_by_id_wrong_tenant(db_session, template_service, other_tenant_key, sample_template):
    result = await template_service.get_template_by_id(db_session, sample_template.id, other_tenant_key)

    assert result is None


@pytest.mark.asyncio
async def test_list_templates_with_filters_no_filters(
    db_session, template_service, test_tenant_key, test_product, sample_template
):
    results = await template_service.list_templates_with_filters(db_session, test_tenant_key)

    assert len(results) >= 1
    template_ids = [t.id for t in results]
    assert sample_template.id in template_ids


@pytest.mark.asyncio
async def test_list_templates_with_filters_role_filter(
    db_session, template_service, test_tenant_key, sample_template, test_product
):
    other_template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="test-reviewer",
        role="reviewer",
        category="custom",
        system_instructions="You are a reviewer.",
    )
    db_session.add(other_template)
    await db_session.commit()

    results = await template_service.list_templates_with_filters(db_session, test_tenant_key, role="analyzer")

    assert len(results) >= 1
    assert all(t.role == "analyzer" for t in results)


@pytest.mark.asyncio
async def test_list_templates_with_filters_is_active_filter(
    db_session, template_service, test_tenant_key, sample_template, test_product
):
    inactive_template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="test-inactive",
        role="analyzer",
        category="custom",
        system_instructions="Inactive template",
        is_active=False,
    )
    db_session.add(inactive_template)
    await db_session.commit()

    results = await template_service.list_templates_with_filters(db_session, test_tenant_key, is_active=True)

    assert all(t.is_active is True for t in results)


@pytest.mark.asyncio
async def test_check_template_name_exists_true(db_session, template_service, test_tenant_key, sample_template):
    exists = await template_service.check_template_name_exists(db_session, test_tenant_key, "test-analyzer")

    assert exists is True


@pytest.mark.asyncio
async def test_check_template_name_exists_false(db_session, template_service, test_tenant_key):
    exists = await template_service.check_template_name_exists(db_session, test_tenant_key, "nonexistent-template")

    assert exists is False


@pytest.mark.asyncio
async def test_get_default_templates_by_role(db_session, template_service, test_tenant_key, test_product):
    default_template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="default-orchestrator",
        role="orchestrator",
        category="system",
        system_instructions="Default orchestrator",
        is_default=True,
    )
    db_session.add(default_template)
    await db_session.commit()

    results = await template_service.get_default_templates_by_role(db_session, test_tenant_key, "orchestrator")

    assert len(results) >= 1
    assert all(t.is_default is True for t in results)
    assert all(t.role == "orchestrator" for t in results)


@pytest.mark.asyncio
async def test_get_enabled_role_count(db_session, template_service, test_tenant_key, test_product, sample_template):
    from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment

    assert await template_service.get_enabled_role_count(db_session, test_tenant_key, test_product.id) == 0

    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=test_product.id,
            template_id=sample_template.id,
            tenant_key=test_tenant_key,
            is_active=True,
        )
    )
    await db_session.commit()

    assert await template_service.get_enabled_role_count(db_session, test_tenant_key, test_product.id) == 1


@pytest.mark.asyncio
async def test_get_enabled_role_count_excludes_system_roles(
    db_session, template_service, test_tenant_key, test_product
):
    from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment

    initial_count = await template_service.get_enabled_role_count(db_session, test_tenant_key, test_product.id)

    orchestrator_template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="orchestrator-for-count-test",
        role="orchestrator",
        category="system",
        system_instructions="Orchestrator",
        is_active=True,
    )
    db_session.add(orchestrator_template)
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=test_product.id,
            template_id=orchestrator_template.id,
            tenant_key=test_tenant_key,
            is_active=True,
        )
    )
    await db_session.commit()

    count = await template_service.get_enabled_role_count(db_session, test_tenant_key, test_product.id)

    assert count == initial_count


@pytest.mark.asyncio
async def test_enabled_role_count_folds_copies_of_one_role(db_session, template_service, test_tenant_key, test_product):
    from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment

    for i in range(3):
        template = AgentTemplate(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            product_id=test_product.id,
            name=f"implementer-copy-{i}-{uuid4().hex[:4]}",
            role="implementer",
            category="role",
            system_instructions="copy",
            is_active=True,
        )
        db_session.add(template)
        db_session.add(
            ProductAgentAssignment(
                id=str(uuid4()),
                product_id=test_product.id,
                template_id=template.id,
                tenant_key=test_tenant_key,
                is_active=True,
            )
        )
    await db_session.commit()

    assert await template_service.get_enabled_role_count(db_session, test_tenant_key, test_product.id) == 1






@pytest.mark.asyncio
async def test_tenant_isolation_list_templates(
    db_session, template_service, test_tenant_key, other_tenant_key, sample_template, test_product
):
    other_template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=other_tenant_key,
        product_id=test_product.id,
        name="other-template",
        role="analyzer",
        category="custom",
        system_instructions="Other tenant template",
    )
    db_session.add(other_template)
    await db_session.commit()

    results = await template_service.list_templates_with_filters(db_session, test_tenant_key)

    assert all(t.tenant_key == test_tenant_key for t in results)


@pytest.mark.asyncio
async def test_tenant_isolation_get_template_history(
    db_session, template_service, test_tenant_key, other_tenant_key, sample_template
):
    archive1 = TemplateArchive(
        tenant_key=test_tenant_key,
        template_id=sample_template.id,
        product_id=sample_template.product_id,
        name=sample_template.name,
        category=sample_template.category,
        role=sample_template.role,
        system_instructions="Version 1",
        version="1.0.0",
        archive_reason="Test",
        archive_type="auto",
        archived_by="system",
    )
    db_session.add(archive1)

    archive2 = TemplateArchive(
        tenant_key=other_tenant_key,
        template_id=sample_template.id,
        product_id=sample_template.product_id,
        name=sample_template.name,
        category=sample_template.category,
        role=sample_template.role,
        system_instructions="Version 2",
        version="2.0.0",
        archive_reason="Test",
        archive_type="auto",
        archived_by="system",
    )
    db_session.add(archive2)

    await db_session.commit()

    history = await template_service.get_template_history(db_session, sample_template.id, test_tenant_key)

    assert len(history) == 1
    assert history[0].tenant_key == test_tenant_key
