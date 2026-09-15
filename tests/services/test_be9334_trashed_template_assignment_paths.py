# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import AgentExecution, AgentJob, Product, Project
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.job_statistics_repository import JobStatisticsRepository
from giljo_mcp.repositories.product_agent_assignment_repository import (
    ProductAgentAssignmentRepository,
)
from giljo_mcp.services.product_agent_assignment_service import (
    ProductAgentAssignmentService,
)
from giljo_mcp.tenant import TenantManager
from tests.helpers.product_crew_helper import adopt_all_templates




@pytest_asyncio.fixture
async def tenant_key():
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def product(db_session, tenant_key):
    row = Product(
        id=str(uuid4()),
        name=f"BE-9334 Product {uuid4().hex[:6]}",
        description="product for the trashed-template assignment tests",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.flush()
    await adopt_all_templates(db_session, tenant_key, row.id)
    return row


def _template(tenant_key, name, *, deleted: bool) -> AgentTemplate:
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"{name}-{uuid4().hex[:4]}",
        role=name,
        description=f"BE-9334 {name} template",
        system_instructions=f"You are a {name} agent.",
        is_active=True,
        deleted_at=datetime.now(UTC) if deleted else None,
    )


@pytest_asyncio.fixture
async def trashed_template(db_session, tenant_key):
    row = _template(tenant_key, "trashed", deleted=True)
    db_session.add(row)
    await db_session.flush()
    return row


@pytest_asyncio.fixture
async def live_template(db_session, tenant_key):
    row = _template(tenant_key, "live", deleted=False)
    db_session.add(row)
    await db_session.flush()
    return row


@pytest_asyncio.fixture
def service(db_manager, tenant_key, db_session):
    return ProductAgentAssignmentService(
        db_manager=db_manager,
        tenant_key=tenant_key,
        test_session=db_session,
    )




@pytest.mark.asyncio
async def test_toggle_assignment_404s_on_trashed_template(service, product, trashed_template):
    with pytest.raises(ResourceNotFoundError):
        await service.toggle_assignment(product.id, trashed_template.id, True)


@pytest.mark.asyncio
async def test_toggle_assignment_writes_no_row_for_a_trashed_template(
    db_session, service, product, trashed_template, tenant_key
):
    with pytest.raises(ResourceNotFoundError):
        await service.toggle_assignment(product.id, trashed_template.id, True)

    repo = ProductAgentAssignmentRepository()
    assignment = await repo.get_assignment(db_session, product.id, trashed_template.id, tenant_key)
    assert assignment is None


@pytest.mark.asyncio
async def test_toggle_assignment_still_accepts_a_live_template(service, product, live_template):
    result = await service.toggle_assignment(product.id, live_template.id, True)

    assert result["template_id"] == live_template.id
    assert result["product_id"] == product.id
    assert result["is_active"] is True




@pytest.mark.asyncio
async def test_bulk_enable_skips_trashed_templates(db_session, product, tenant_key, trashed_template, live_template):
    repo = ProductAgentAssignmentRepository()
    new_assignments = await repo.enable_templates_for_product(
        db_session, product.id, tenant_key, [live_template.id, trashed_template.id]
    )
    await db_session.flush()

    assigned_template_ids = {a.template_id for a in new_assignments}
    assert live_template.id in assigned_template_ids

    active_ids = await repo.get_active_template_ids_for_product(db_session, product.id, tenant_key)
    assert trashed_template.id not in active_ids
    assert live_template.id in active_ids


@pytest.mark.asyncio
async def test_bulk_enable_does_not_serve_a_trashed_template(
    db_session, product, tenant_key, trashed_template, live_template
):
    repo = ProductAgentAssignmentRepository()
    await repo.enable_templates_for_product(db_session, product.id, tenant_key, [live_template.id, trashed_template.id])
    await db_session.flush()

    stored = await repo.get_assignments_for_product(db_session, product.id, tenant_key)
    stored_template_ids = {a.template_id for a in stored}
    assert live_template.id in stored_template_ids
    assert trashed_template.id not in stored_template_ids, (
        "the READ path joins deleted_at IS NULL, so a trashed agent is never reported as assigned"
    )


@pytest.mark.asyncio
async def test_bulk_enable_leaves_an_existing_assignment_alone(db_session, product, tenant_key, live_template):
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=live_template.id,
            tenant_key=tenant_key,
            is_active=False,
        )
    )
    await db_session.flush()

    repo = ProductAgentAssignmentRepository()
    new_assignments = await repo.enable_templates_for_product(db_session, product.id, tenant_key, [live_template.id])

    assert live_template.id not in {a.template_id for a in new_assignments}
    existing = await repo.get_assignment(db_session, product.id, live_template.id, tenant_key)
    assert existing.is_active is False




async def _assign_then_trash(db_session, product, tenant_key, template):
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=template.id,
            tenant_key=tenant_key,
            is_active=True,
        )
    )
    await db_session.flush()

    template.deleted_at = datetime.now(UTC)
    await db_session.flush()


@pytest.mark.asyncio
async def test_list_assignments_drops_a_template_trashed_after_it_was_assigned(
    db_session, product, tenant_key, live_template
):
    await _assign_then_trash(db_session, product, tenant_key, live_template)

    repo = ProductAgentAssignmentRepository()
    assignments = await repo.get_assignments_for_product(db_session, product.id, tenant_key)

    assert live_template.id not in {a.template_id for a in assignments}


@pytest.mark.asyncio
async def test_list_assignments_still_returns_a_live_assigned_template(db_session, product, tenant_key, live_template):
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=live_template.id,
            tenant_key=tenant_key,
            is_active=True,
        )
    )
    await db_session.flush()

    repo = ProductAgentAssignmentRepository()
    assignments = await repo.get_assignments_for_product(db_session, product.id, tenant_key)

    assert live_template.id in {a.template_id for a in assignments}
    returned = next(a for a in assignments if a.template_id == live_template.id)
    assert returned.template is not None
    assert returned.template.name == live_template.name


@pytest.mark.asyncio
async def test_list_assignments_returns_the_live_one_and_only_the_live_one(
    db_session, product, tenant_key, live_template
):
    survivor = _template(tenant_key, "survivor", deleted=False)
    db_session.add(survivor)
    await db_session.flush()

    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=survivor.id,
            tenant_key=tenant_key,
            is_active=True,
        )
    )
    await _assign_then_trash(db_session, product, tenant_key, live_template)

    repo = ProductAgentAssignmentRepository()
    assignments = await repo.get_assignments_for_product(db_session, product.id, tenant_key)

    assert {a.template_id for a in assignments} == {survivor.id}


@pytest.mark.asyncio
async def test_list_assignments_active_only_still_composes_with_the_join(
    db_session, product, tenant_key, live_template
):
    survivor = _template(tenant_key, "survivor", deleted=False)
    db_session.add(survivor)
    await db_session.flush()

    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            product_id=product.id,
            template_id=survivor.id,
            tenant_key=tenant_key,
            is_active=True,
        )
    )
    await _assign_then_trash(db_session, product, tenant_key, live_template)

    repo = ProductAgentAssignmentRepository()
    assignments = await repo.get_assignments_for_product(db_session, product.id, tenant_key, active_only=True)

    assert {a.template_id for a in assignments} == {survivor.id}


@pytest.mark.asyncio
async def test_service_list_assignments_no_longer_reports_a_trashed_template_as_active(
    db_session, service, product, tenant_key, live_template
):
    await _assign_then_trash(db_session, product, tenant_key, live_template)

    payload = await service.list_assignments(product.id)

    assert live_template.id not in {row["template_id"] for row in payload}




@pytest.mark.asyncio
async def test_role_distribution_deliberately_keeps_trashed_templates_as_fold_targets(db_session):
    tenant = TenantManager.generate_tenant_key()

    with tenant_session_context(db_session, tenant):
        base = AgentTemplate(
            tenant_key=tenant,
            name="implementer",
            background_color="#aabbcc",
            is_active=True,
            deleted_at=datetime.now(UTC),
        )
        never_spawned = AgentTemplate(
            tenant_key=tenant,
            name="retired-analyst",
            background_color="#ddeeff",
            is_active=True,
            deleted_at=datetime.now(UTC),
        )
        db_session.add_all([base, never_spawned])
        await db_session.flush()

        _owning_product_project = Product(
            id=str(uuid4()),
            tenant_key=tenant,
            name=f"Owning Product {uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_project)
        project = Project(
            tenant_key=tenant,
            product_id=_owning_product_project.id,
            name="BE-9334 intent pin",
            description="seeded for the role-distribution intent pin",
            mission="seeded mission",
            status="active",
            series_number=9334,
        )
        db_session.add(project)
        await db_session.flush()

        for agent_name in ("implementer-backend", "implementer-frontend"):
            job = AgentJob(
                job_id=str(uuid4()),
                tenant_key=tenant,
                project_id=project.id,
                mission="m",
                job_type=agent_name,
                status="active",
                created_at=datetime.now(UTC),
            )
            db_session.add(job)
            db_session.add(
                AgentExecution(
                    job_id=job.job_id,
                    agent_id=str(uuid4()),
                    tenant_key=tenant,
                    agent_display_name=agent_name,
                    agent_name=agent_name,
                    status="working",
                    started_at=datetime.now(UTC),
                )
            )
        await db_session.flush()

        dist = await JobStatisticsRepository(None).get_agent_role_distribution(db_session, tenant)

    by_label = {seg["label"]: seg["count"] for seg in dist}

    assert by_label["Implementer"] == 2, (
        "The trashed template stopped acting as a fold target. If a deleted_at filter "
        "was just added to job_statistics_repository.get_agent_role_distribution, that "
        "is the deliberate behaviour documented there being removed -- read the "
        "docstring before changing this assertion."
    )
    assert "Implementer Backend" not in by_label
    assert "Implementer Frontend" not in by_label

    assert by_label["Retired Analyst"] == 0
    await adopt_all_templates(db_session, tenant, _owning_product_project.id)
