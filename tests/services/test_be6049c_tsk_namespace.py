# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Project, Task, User
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.task_conversion_service import TaskConversionService
from giljo_mcp.services.taxonomy_ops import RESERVED_TASK_TYPE_ABBR
from giljo_mcp.services.taxonomy_service import TaxonomyService
from giljo_mcp.tenant import TenantManager, current_tenant


pytestmark = pytest.mark.asyncio




async def test_tsk_in_default_seed_for_new_tenants(db_session, db_manager):
    from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded, list_taxonomy_types

    tenant_key = TenantManager.generate_tenant_key()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
        abbrs = {t.abbreviation for t in await list_taxonomy_types(db_session, tenant_key)}
    assert RESERVED_TASK_TYPE_ABBR in abbrs


async def test_ensure_reserved_task_type_is_idempotent_and_race_safe(db_session, db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    svc = TaxonomyService(db_manager=db_manager, session=db_session)

    first = await svc.ensure_reserved_task_type(tenant_key)
    second = await svc.ensure_reserved_task_type(tenant_key)

    assert first.abbreviation == RESERVED_TASK_TYPE_ABBR
    assert first.id == second.id
    assert first.color == "#8b5cf6"

    with tenant_session_context(db_session, tenant_key):
        rows = (
            (
                await db_session.execute(
                    select(TaxonomyType).where(
                        TaxonomyType.tenant_key == tenant_key,
                        TaxonomyType.abbreviation == RESERVED_TASK_TYPE_ABBR,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1, "ensure must never create a duplicate TSK row"


async def test_existing_tenant_without_tsk_gets_it_lazily_on_create(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    svc = TaxonomyService(db_manager=db_manager, session=db_session)
    for abbr, label in (("BE", "Backend"), ("FE", "Frontend")):
        await svc.create_type(tenant_key=tenant_a, abbreviation=abbr, label=label)
    await db_session.commit()

    before = {t.abbreviation for t in await svc.list_types(tenant_a)}
    assert RESERVED_TASK_TYPE_ABBR not in before

    response = await task_service_a.create_task_for_mcp(
        title="first task ever",
        description="should lazily mint TSK",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    assert response["task_type"] == RESERVED_TASK_TYPE_ABBR

    after = {t.abbreviation for t in await svc.list_types(tenant_a)}
    assert RESERVED_TASK_TYPE_ABBR in after




async def test_new_task_renders_tsk_serial(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.create_task_for_mcp(
        title="serial render",
        description="",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    assert response["task_type"] == RESERVED_TASK_TYPE_ABBR
    assert response["taxonomy_alias"].startswith("TSK-")
    suffix = response["taxonomy_alias"].split("-", 1)[1]
    assert suffix.isdigit() and len(suffix) >= 4




async def test_task_type_id_excluded_from_update_allowlist():
    from giljo_mcp.services.task_service import _ALLOWED_TASK_UPDATE_FIELDS

    assert "task_type_id" not in _ALLOWED_TASK_UPDATE_FIELDS


async def test_update_cannot_change_task_type(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    svc = TaxonomyService(db_manager=db_manager, session=db_session)
    await svc.create_type(tenant_key=tenant_a, abbreviation="BE", label="Backend")
    await db_session.commit()

    created = await task_service_a.create_task_for_mcp(
        title="immutable type",
        description="",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    task_id = created["task_id"]

    result = await task_service_a.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
        task_type="BE",
    )
    assert "task_type_id" not in result["updated_fields"]

    listing = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary")
    row = next(r for r in listing["tasks"] if r["task_id"] == task_id)
    assert row["task_type"]["abbreviation"] == RESERVED_TASK_TYPE_ABBR




async def test_tsk_excluded_from_project_valid_types(db_session, two_tenant_service_setup):
    from contextlib import asynccontextmanager

    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    project_service_a = two_tenant_service_setup["project_service_a"]
    tm = two_tenant_service_setup["tenant_manager"]

    @asynccontextmanager
    async def _on_test_session():
        yield db_session

    orig = db_manager.get_session_async
    db_manager.get_session_async = _on_test_session
    token = tm.set_current_tenant(tenant_a)
    try:
        valid = await project_service_a._get_valid_project_types(tenant_a)
    finally:
        current_tenant.reset(token)
        db_manager.get_session_async = orig

    abbrs = {t["abbreviation"] for t in valid}
    assert RESERVED_TASK_TYPE_ABBR not in abbrs
    assert "BE" in abbrs


async def test_taxonomy_service_validate_rejects_tsk(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]

    svc = TaxonomyService(db_manager=db_manager, session=db_session)
    await svc.ensure_reserved_task_type(tenant_a)

    with pytest.raises(ValidationError) as excinfo:
        await svc.validate(RESERVED_TASK_TYPE_ABBR, tenant_a)
    assert excinfo.value.context.get("reserved") is True


async def test_cannot_create_project_as_tsk(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    project_service_a = two_tenant_service_setup["project_service_a"]

    svc = TaxonomyService(db_manager=db_manager, session=db_session)
    await svc.ensure_reserved_task_type(tenant_a)
    await svc.create_type(tenant_key=tenant_a, abbreviation="BE", label="Backend")
    await db_session.commit()

    assert await project_service_a.get_project_type_by_label(RESERVED_TASK_TYPE_ABBR, tenant_a) is None
    resolved_be = await project_service_a.get_project_type_by_label("BE", tenant_a)
    assert resolved_be is not None
    assert resolved_be.abbreviation == "BE"


async def test_cannot_create_project_as_tsk_via_case_or_label_bypass(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    project_service_a = two_tenant_service_setup["project_service_a"]

    svc = TaxonomyService(db_manager=db_manager, session=db_session)
    await svc.ensure_reserved_task_type(tenant_a)
    await db_session.commit()

    for spelling in ("tsk", "Tsk", "TsK", "Task", "task", " TSK "):
        assert await project_service_a.get_project_type_by_label(spelling, tenant_a) is None, (
            f"TSK bypass via {spelling!r} — a project could be created/retagged as TSK"
        )




@pytest_asyncio.fixture
async def conversion_service(db_manager, db_session, test_tenant_key):
    from giljo_mcp.tenant import TenantManager

    tm = TenantManager()
    tm.set_current_tenant(test_tenant_key)
    return TaskConversionService(db_manager=db_manager, tenant_manager=tm, session=db_session)


async def _admin(db_session, tenant_key: str) -> User:
    u = User(
        id=str(uuid4()),
        tenant_key=tenant_key,
        username=f"u_{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@test.local",
        role="admin",
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


async def _active_product(db_session, tenant_key: str) -> Product:
    p = Product(
        id=str(uuid4()),
        name=f"P {uuid4().hex[:6]}",
        description="conv test product",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def test_tsk_task_conversion_preserves_serial_and_strips_type(
    conversion_service, db_session, db_manager, test_tenant_key
):
    user = await _admin(db_session, test_tenant_key)
    product = await _active_product(db_session, test_tenant_key)

    tsk = await TaxonomyService(db_manager=db_manager, session=db_session).ensure_reserved_task_type(test_tenant_key)

    task = Task(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        title="promote me",
        description="a real piece of work",
        status="pending",
        priority="medium",
        created_by_user_id=user.id,
        task_type_id=tsk.id,
        series_number=42,
    )
    db_session.add(task)
    await db_session.commit()

    result = await conversion_service.convert_to_project(
        task_id=task.id,
        project_name=None,
        strategy="single",
        include_subtasks=False,
        user_id=user.id,
    )

    project = (await db_session.execute(select(Project).where(Project.id == result.project_id))).scalar_one()
    assert project.series_number == 42
    assert project.project_type_id is None


async def test_untyped_legacy_task_conversion_still_works(conversion_service, db_session, test_tenant_key):
    user = await _admin(db_session, test_tenant_key)
    product = await _active_product(db_session, test_tenant_key)

    task = Task(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        title="legacy untyped",
        description="no task_type_id",
        status="pending",
        priority="medium",
        created_by_user_id=user.id,
    )
    db_session.add(task)
    await db_session.commit()

    result = await conversion_service.convert_to_project(
        task_id=task.id,
        project_name=None,
        strategy="single",
        include_subtasks=False,
        user_id=user.id,
    )
    project = (await db_session.execute(select(Project).where(Project.id == result.project_id))).scalar_one()
    assert project.project_type_id is None
    assert project.series_number is not None




async def test_legacy_be_typed_task_still_renders(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    be = await TaxonomyService(db_manager=db_manager, session=db_session).create_type(
        tenant_key=tenant_a, abbreviation="BE", label="Backend"
    )
    legacy = Task(
        id=str(uuid4()),
        tenant_key=tenant_a,
        product_id=product_a.id,
        title="grandfathered BE task",
        description="created before TSK-only",
        status="pending",
        priority="medium",
        task_type_id=be.id,
        series_number=7,
    )
    db_session.add(legacy)
    await db_session.commit()

    listing = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary")
    row = next(r for r in listing["tasks"] if r["task_id"] == str(legacy.id))
    assert row["task_type"]["abbreviation"] == "BE"
    assert row["taxonomy_alias"] == "BE-0007"
