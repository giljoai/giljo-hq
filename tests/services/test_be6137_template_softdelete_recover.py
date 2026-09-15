# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.templates import AgentTemplate, TemplateArchive
from giljo_mcp.services.template_service import TemplateService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio




def _make_template(tenant_key: str, suffix: str | None = None) -> AgentTemplate:
    name = f"be6137-tpl-{suffix or uuid4().hex[:8]}"
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        role="custom",
        category="custom",
        system_instructions="# Test\nSoft-delete regression template.",
        is_active=True,
        version="1.0.0",
    )


def _make_service(db_manager, tenant_key: str, db_session) -> TemplateService:
    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = tenant_key
    return TemplateService(db_manager=db_manager, tenant_manager=mock_tm, session=db_session)


@pytest_asyncio.fixture
async def live_template(db_session, test_tenant_key) -> AgentTemplate:
    tpl = _make_template(test_tenant_key)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl




async def test_delete_template_stamps_deleted_at(db_manager, db_session, test_tenant_key, live_template):
    svc = _make_service(db_manager, test_tenant_key, db_session)

    deleted = await svc.delete_template(db_session, live_template.id, test_tenant_key)
    assert deleted is True

    await db_session.refresh(live_template)
    assert live_template.deleted_at is not None


async def test_deleted_template_absent_from_list_templates(db_manager, db_session, test_tenant_key):
    tpl = _make_template(test_tenant_key)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)

    svc = _make_service(db_manager, test_tenant_key, db_session)

    result = await svc.list_templates_with_filters(db_session, test_tenant_key)
    assert tpl.id in {t.id for t in result}

    await svc.delete_template(db_session, tpl.id, test_tenant_key)

    result = await svc.list_templates_with_filters(db_session, test_tenant_key)
    assert tpl.id not in {t.id for t in result}


async def test_deleted_template_absent_from_get_by_id(db_manager, db_session, test_tenant_key):
    from giljo_mcp.exceptions import TemplateNotFoundError

    tpl = _make_template(test_tenant_key)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)

    svc = _make_service(db_manager, test_tenant_key, db_session)
    await svc.delete_template(db_session, tpl.id, test_tenant_key)

    with pytest.raises(TemplateNotFoundError):
        await svc.get_template(template_id=tpl.id, tenant_key=test_tenant_key)


async def test_deleted_template_absent_from_get_by_name(db_manager, db_session, test_tenant_key):
    from giljo_mcp.exceptions import TemplateNotFoundError

    tpl = _make_template(test_tenant_key)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)

    svc = _make_service(db_manager, test_tenant_key, db_session)
    await svc.delete_template(db_session, tpl.id, test_tenant_key)

    with pytest.raises(TemplateNotFoundError):
        await svc.get_template(template_name=tpl.name, tenant_key=test_tenant_key)


async def test_deleted_template_surfaces_in_list_deleted(db_manager, db_session, test_tenant_key):
    tpl = _make_template(test_tenant_key)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)

    svc = _make_service(db_manager, test_tenant_key, db_session)
    await svc.delete_template(db_session, tpl.id, test_tenant_key)

    trashed = await svc.list_deleted_templates(tenant_key=test_tenant_key)
    assert tpl.id in {t.id for t in trashed}
    row = next(t for t in trashed if t.id == tpl.id)
    assert row.deleted_at is not None




async def test_restore_template_within_window(db_manager, db_session, test_tenant_key):
    tpl = _make_template(test_tenant_key)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)

    svc = _make_service(db_manager, test_tenant_key, db_session)
    await svc.delete_template(db_session, tpl.id, test_tenant_key)

    restored = await svc.restore_template(tpl.id, test_tenant_key)
    assert restored.deleted_at is None
    assert restored.id == tpl.id

    result = await svc.list_templates_with_filters(db_session, test_tenant_key)
    assert tpl.id in {t.id for t in result}

    trashed = await svc.list_deleted_templates(tenant_key=test_tenant_key)
    assert tpl.id not in {t.id for t in trashed}




async def test_restore_window_expired_raises(db_manager, db_session, test_tenant_key):
    tpl = _make_template(test_tenant_key)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)

    svc = _make_service(db_manager, test_tenant_key, db_session)
    await svc.delete_template(db_session, tpl.id, test_tenant_key)

    await db_session.execute(
        update(AgentTemplate)
        .where(AgentTemplate.id == tpl.id)
        .values(deleted_at=datetime.now(UTC) - timedelta(days=31))
    )
    await db_session.flush()

    with pytest.raises(ValidationError):
        await svc.restore_template(tpl.id, test_tenant_key)

    trashed = await svc.list_deleted_templates(tenant_key=test_tenant_key)
    assert tpl.id in {t.id for t in trashed}




async def test_archive_survives_soft_delete_and_restore(db_manager, db_session, test_tenant_key):
    tpl = _make_template(test_tenant_key)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)

    archive = TemplateArchive(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        template_id=tpl.id,
        name=tpl.name,
        category=tpl.category,
        version="0.9.0",
        system_instructions="# old\nPrevious version.",
        archive_reason="pre-delete snapshot",
        archive_type="manual",
    )
    db_session.add(archive)
    await db_session.commit()
    await db_session.refresh(archive)

    svc = _make_service(db_manager, test_tenant_key, db_session)
    await svc.delete_template(db_session, tpl.id, test_tenant_key)

    archive_check = (
        await db_session.execute(select(TemplateArchive).where(TemplateArchive.id == archive.id))
    ).scalar_one_or_none()
    assert archive_check is not None, "Archive must survive soft-delete"

    restored = await svc.restore_template(tpl.id, test_tenant_key)
    assert restored.deleted_at is None

    archive_after = (
        await db_session.execute(select(TemplateArchive).where(TemplateArchive.id == archive.id))
    ).scalar_one_or_none()
    assert archive_after is not None, "Archive must survive restore"




async def test_restore_is_tenant_isolated(db_manager, db_session, test_tenant_key):
    tpl = _make_template(test_tenant_key)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)

    svc_a = _make_service(db_manager, test_tenant_key, db_session)
    await svc_a.delete_template(db_session, tpl.id, test_tenant_key)

    other_tenant = TenantManager.generate_tenant_key()
    svc_b = _make_service(db_manager, other_tenant, db_session)

    trashed_b = await svc_b.list_deleted_templates(tenant_key=other_tenant)
    assert tpl.id not in {t.id for t in trashed_b}

    with pytest.raises(ResourceNotFoundError):
        await svc_b.restore_template(tpl.id, other_tenant)

    restored = await svc_a.restore_template(tpl.id, test_tenant_key)
    assert restored.id == tpl.id
    assert restored.deleted_at is None
