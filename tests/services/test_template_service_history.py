# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from giljo_mcp.models.templates import TemplateArchive




@pytest.mark.asyncio
async def test_get_template_history(db_session, template_service, test_tenant_key, sample_template):
    archive1 = TemplateArchive(
        tenant_key=test_tenant_key,
        template_id=sample_template.id,
        product_id=sample_template.product_id,
        name=sample_template.name,
        category=sample_template.category,
        role=sample_template.role,
        system_instructions="Version 1",
        version="1.0.0",
        archive_reason="Initial version",
        archive_type="auto",
        archived_by="system",
    )
    db_session.add(archive1)

    archive2 = TemplateArchive(
        tenant_key=test_tenant_key,
        template_id=sample_template.id,
        product_id=sample_template.product_id,
        name=sample_template.name,
        category=sample_template.category,
        role=sample_template.role,
        system_instructions="Version 2",
        version="2.0.0",
        archive_reason="Update",
        archive_type="auto",
        archived_by="user",
    )
    db_session.add(archive2)

    await db_session.commit()

    history = await template_service.get_template_history(db_session, sample_template.id, test_tenant_key)

    assert len(history) == 2
    versions = [h.version for h in history]
    assert "1.0.0" in versions
    assert "2.0.0" in versions


@pytest.mark.asyncio
async def test_get_archive_by_id_success(db_session, template_service, test_tenant_key, sample_template):
    archive = TemplateArchive(
        tenant_key=test_tenant_key,
        template_id=sample_template.id,
        product_id=sample_template.product_id,
        name=sample_template.name,
        category=sample_template.category,
        role=sample_template.role,
        system_instructions="Archived content",
        version="1.0.0",
        archive_reason="Test",
        archive_type="manual",
        archived_by="test-user",
    )
    db_session.add(archive)
    await db_session.commit()
    await db_session.refresh(archive)

    result = await template_service.get_archive_by_id(db_session, archive.id, sample_template.id, test_tenant_key)

    assert result is not None
    assert result.id == archive.id
    assert result.system_instructions == "Archived content"


@pytest.mark.asyncio
async def test_create_template_archive(db_session, template_service, sample_template):
    archive = await template_service.create_template_archive(
        db_session, sample_template, archive_reason="Test archive", archive_type="manual", archived_by="test-user"
    )

    assert archive.template_id == sample_template.id
    assert archive.tenant_key == sample_template.tenant_key
    assert archive.archive_reason == "Test archive"
    assert archive.archived_by == "test-user"


@pytest.mark.asyncio
async def test_restore_template_from_archive(db_session, template_service, sample_template):
    archive = TemplateArchive(
        tenant_key=sample_template.tenant_key,
        template_id=sample_template.id,
        product_id=sample_template.product_id,
        name=sample_template.name,
        category=sample_template.category,
        role=sample_template.role,
        system_instructions="Archived content",
        variables=["var1", "var2"],
        behavioral_rules=["rule1"],
        success_criteria=["criteria1"],
        version="2.0.0",
        archive_reason="Test",
        archive_type="manual",
        archived_by="test-user",
    )
    db_session.add(archive)
    await db_session.commit()

    await template_service.restore_template_from_archive(db_session, sample_template, archive, restored_by="test-user")
    await db_session.commit()
    await db_session.refresh(archive)

    assert sample_template.variables == ["var1", "var2"]
    assert sample_template.behavioral_rules == ["rule1"]
    assert sample_template.success_criteria == ["criteria1"]
    assert sample_template.version == "2.0.0"
    assert archive.restored_by == "test-user"
    assert archive.restored_at is not None


@pytest.mark.asyncio
async def test_restore_template_from_archive_without_user(db_session, template_service, sample_template):
    archive = TemplateArchive(
        tenant_key=sample_template.tenant_key,
        template_id=sample_template.id,
        product_id=sample_template.product_id,
        name=sample_template.name,
        category=sample_template.category,
        role=sample_template.role,
        system_instructions="Archived content",
        variables=[],
        behavioral_rules=[],
        success_criteria=[],
        version="3.0.0",
        archive_reason="Test",
        archive_type="manual",
        archived_by="test-user",
    )
    db_session.add(archive)
    await db_session.commit()

    await template_service.restore_template_from_archive(db_session, sample_template, archive)
    await db_session.commit()
    await db_session.refresh(archive)

    assert archive.restored_at is not None
    assert archive.restored_by is None


@pytest.mark.asyncio
async def test_reset_template_to_defaults(db_session, template_service, sample_template):
    sample_template.user_instructions = "Custom instructions"
    sample_template.behavioral_rules = ["rule1", "rule2"]
    sample_template.success_criteria = ["criteria1"]
    sample_template.tags = ["tag1", "tag2"]
    await db_session.commit()

    await template_service.reset_template_to_defaults(db_session, sample_template)

    assert sample_template.user_instructions is None
    assert sample_template.behavioral_rules == []
    assert sample_template.success_criteria == []
    assert sample_template.tags == []


@pytest.mark.asyncio
async def test_reset_system_instructions(db_session, template_service, sample_template):
    sample_template.system_instructions = "Custom system instructions"
    await db_session.commit()

    await template_service.reset_system_instructions(db_session, sample_template)

    from giljo_mcp.branding import PRODUCT_NAME

    assert f"{PRODUCT_NAME} Agent" in sample_template.system_instructions
    assert "get_job_mission" in sample_template.system_instructions
    assert "health_check" in sample_template.system_instructions
