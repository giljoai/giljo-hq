# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9289b_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _seed_project(db_session, tenant: str) -> str:
    with tenant_session_context(db_session, tenant):
        _owning_product_project = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            name=f"Owning Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_project)
        project = Project(
            id=str(uuid.uuid4()),
            name=f"BE-9289b {uuid.uuid4().hex[:6]}",
            description="thread api test project",
            mission="exercise thread edit",
            status="active",
            tenant_key=tenant,
            product_id=_owning_product_project.id,
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
            implementation_launched_at=datetime.now(UTC),
        )
        db_session.add(project)
        await db_session.flush()
    return project.id


async def _standalone(svc, tenant: str) -> str:
    thread = await svc.create_thread(subject="standalone", creator_id="agent-a", tenant_key=tenant)
    return thread["thread_id"]


async def _project_bound(svc, tenant: str, project_id: str) -> str:
    thread = await svc.create_thread(subject="bound", creator_id="agent-a", project_id=project_id, tenant_key=tenant)
    return thread["thread_id"]




async def test_rename_a_standalone_thread(db_manager, db_session):
    tenant = _tk("rename")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    result = await svc.update_thread(thread_id=tid, subject="  Deploy coordination  ", tenant_key=tenant)

    assert result["subject"] == "Deploy coordination"


async def test_rename_refused_on_a_project_thread(db_manager, db_session):
    tenant = _tk("renameguard")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _project_bound(svc, tenant, project_id)

    with pytest.raises(ValidationError) as exc:
        await svc.update_thread(thread_id=tid, subject="my own name", tenant_key=tenant)

    assert "360 memory" in str(exc.value)


async def test_operator_can_set_status_without_an_agent(db_manager, db_session):
    tenant = _tk("status")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    result = await svc.update_thread(thread_id=tid, status="resolved", tenant_key=tenant)

    assert result["status"] == "resolved"


async def test_rename_and_status_in_one_call(db_manager, db_session):
    tenant = _tk("both")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    result = await svc.update_thread(thread_id=tid, subject="Renamed", status="closed", tenant_key=tenant)

    assert (result["subject"], result["status"]) == ("Renamed", "closed")


async def test_blank_subject_is_refused(db_manager, db_session):
    tenant = _tk("blank")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    with pytest.raises(ValidationError):
        await svc.update_thread(thread_id=tid, subject="   ", tenant_key=tenant)


async def test_empty_update_is_refused(db_manager, db_session):
    tenant = _tk("noop")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    with pytest.raises(ValidationError):
        await svc.update_thread(thread_id=tid, tenant_key=tenant)


async def test_unknown_status_is_refused(db_manager, db_session):
    tenant = _tk("badstatus")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    with pytest.raises(ValidationError):
        await svc.update_thread(thread_id=tid, status="banana", tenant_key=tenant)




async def _seed_product(db_session, tenant: str, *, is_active: bool = True) -> str:
    with tenant_session_context(db_session, tenant):
        product = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            name=f"FE-9530 Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=is_active,
        )
        db_session.add(product)
        await db_session.flush()
    return product.id


async def test_retag_a_pre_existing_untagged_thread_with_a_product(db_manager, db_session):
    tenant = _tk("retag")
    await _seed(db_session, tenant)
    product_id = await _seed_product(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    result = await svc.update_thread(thread_id=tid, product_id=product_id, tenant_key=tenant)

    assert result["product_id"] == product_id
    assert result["project_ids"] == []


async def test_retag_refuses_a_product_from_another_tenant(db_manager, db_session):
    tenant = _tk("retagcross")
    other_tenant = _tk("retagcross_other")
    await _seed(db_session, tenant)
    await _seed(db_session, other_tenant)
    foreign_product_id = await _seed_product(db_session, other_tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    with pytest.raises(ValidationError):
        await svc.update_thread(thread_id=tid, product_id=foreign_product_id, tenant_key=tenant)


async def test_clear_product_nulls_it_back_out(db_manager, db_session):
    tenant = _tk("clearproduct")
    await _seed(db_session, tenant)
    product_id = await _seed_product(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="tagged", creator_id="agent-a", product_id=product_id, tenant_key=tenant)

    result = await svc.update_thread(thread_id=thread["thread_id"], clear_product=True, tenant_key=tenant)

    assert result["product_id"] is None


async def test_product_id_and_clear_product_together_is_refused(db_manager, db_session):
    tenant = _tk("contradiction")
    await _seed(db_session, tenant)
    product_id = await _seed_product(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    with pytest.raises(ValidationError):
        await svc.update_thread(thread_id=tid, product_id=product_id, clear_product=True, tenant_key=tenant)


async def test_project_ids_is_plural_and_full_replace(db_manager, db_session):
    tenant = _tk("plural")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)
    project_a = await _seed_project(db_session, tenant)

    result = await svc.update_thread(thread_id=tid, project_ids=[project_a], tenant_key=tenant)
    assert result["project_ids"] == [project_a]

    result = await svc.update_thread(thread_id=tid, project_ids=[], tenant_key=tenant)
    assert result["project_ids"] == []


async def test_project_ids_refuses_a_project_from_another_tenant(db_manager, db_session):
    tenant = _tk("pcross")
    other_tenant = _tk("pcross2")
    await _seed(db_session, tenant)
    await _seed(db_session, other_tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)
    foreign_project_id = await _seed_project(db_session, other_tenant)

    with pytest.raises(ValidationError):
        await svc.update_thread(thread_id=tid, project_ids=[foreign_project_id], tenant_key=tenant)


async def test_omitted_project_ids_leaves_existing_tags_untouched(db_manager, db_session):
    tenant = _tk("plural_untouched")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)
    project_a = await _seed_project(db_session, tenant)
    await svc.update_thread(thread_id=tid, project_ids=[project_a], tenant_key=tenant)

    result = await svc.update_thread(thread_id=tid, status="active", tenant_key=tenant)

    assert result["project_ids"] == [project_a]
