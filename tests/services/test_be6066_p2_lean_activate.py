# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-6066 P2 regression tests — leaner product ACTIVATE (behavior-preserving
query-collapse of ``POST /api/v1/products/{id}/activate``).

P2 removes redundant re-hydration from the activate path without changing any
behavior or response bytes:

* the service ``activate_product`` no longer issues a post-commit ``refresh``
  (an extra SELECT + four relation selectin loads whose result the only HTTP
  caller discarded);
* the endpoint fetches the previously-active product LEAN (``eager_load=False``)
  since only its id is read — skipping four wasted selectin loads;
* the response stats route through P1's batched
  ``get_product_statistics_bulk`` path (identical numbers, drops a per-product
  re-SELECT).

These tests gate the load-bearing correctness properties the collapse must
preserve:

1. **Several products may be shown at once, no cascade** — FE-9524/D1 dropped
   the one-active-per-tenant invariant and its project/job pause cascade.
   Activating (showing) a product no longer touches any other product, or
   that product's own projects/jobs. This is a rewrite of the old
   "≤1 active + cascade" pin, which asserted exactly the enforcement D1
   retires.
2. **Byte-identical response shape** — the endpoint's ``ProductActivationResponse``
   carries the same fields/values (identity, previous-active id, stats counts,
   fully-hydrated detail graph) it did before the collapse, asserted against a
   fixture with two products.
3. **Fewer queries** — the lean previously-active fetch issues materially fewer
   SQL statements than the eager one (the four selectin loads are gone).

Parallel-safe: ``TransactionalTestContext`` (via the ``db_session`` fixture,
rollback at teardown), a unique tenant_key per test, no module-level mutable
state.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import and_, event, select

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project, Task, VisionDocument
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.products import ProductTechStack
from giljo_mcp.services.product_service import ProductService
from tests.fixtures.base_fixtures import TestData


def _add_product(session, tenant_key: str, name: str, *, is_active: bool) -> Product:
    product = Product(
        id=str(uuid.uuid4()),
        name=name,
        description=f"{name} description",
        tenant_key=tenant_key,
        is_active=is_active,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    return product


def _add_project(session, tenant_key: str, product_id: str, status: str, series_number: int) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name=f"Project {series_number}",
        description="desc",
        mission="mission",
        status=status,
        product_id=product_id,
        tenant_key=tenant_key,
        series_number=series_number,
    )
    session.add(project)
    return project


def _add_task(session, tenant_key: str, product_id: str, status: str) -> None:
    session.add(
        Task(
            id=str(uuid.uuid4()),
            title="Task",
            description="desc",
            tenant_key=tenant_key,
            product_id=product_id,
            status=status,
            priority="medium",
        )
    )


def _add_vision(session, tenant_key: str, product_id: str, name: str = "Vision") -> None:
    session.add(
        VisionDocument(
            id=str(uuid.uuid4()),
            product_id=product_id,
            tenant_key=tenant_key,
            document_name=name,
            document_type="vision",
            vision_document="vision content",
            storage_type="inline",
        )
    )


@pytest.mark.asyncio
async def test_activate_shows_without_touching_siblings_or_cascading(db_session, db_manager):
    """
    FE-9524/D1: showing product B leaves product A shown too (no sibling
    deactivation), and does not pause product A's active project or cancel its
    active job -- "several tabs open is the point". These properties must
    survive the P2 query-collapse the same way the old cascade used to.
    """
    tenant_key = TestData.generate_tenant_key()

    # Product A active, with an active project X carrying an active agent job.
    product_a = _add_product(db_session, tenant_key, "Product A", is_active=True)
    product_b = _add_product(db_session, tenant_key, "Product B", is_active=False)
    await db_session.flush()

    project_x = _add_project(db_session, tenant_key, product_a.id, ProjectStatus.ACTIVE, 1)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        job_type="worker",
        tenant_key=tenant_key,
        project_id=project_x.id,
        mission="seed job",
        status="active",
    )
    db_session.add(job)
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)
    result = await service.activate_product(product_b.id)

    # Return carries the flipped column even though the post-commit refresh is
    # gone (expire_on_commit=False keeps the manually-set value readable).
    assert result.is_active is True

    await db_session.refresh(product_a)
    await db_session.refresh(product_b)
    await db_session.refresh(project_x)
    await db_session.refresh(job)

    # Both shown -- no single-active enforcement left, DB or service.
    active_rows = (
        (
            await db_session.execute(
                select(Product).where(
                    and_(
                        Product.tenant_key == tenant_key,
                        Product.is_active,
                        Product.deleted_at.is_(None),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    assert {str(r.id) for r in active_rows} == {str(product_a.id), str(product_b.id)}
    assert product_a.is_active is True

    # No cascade: showing B never touches A's project or job.
    assert project_x.status == ProjectStatus.ACTIVE
    assert job.status == "active"


@pytest.mark.asyncio
async def test_endpoint_response_byte_identical_shape(db_session, db_manager):
    """
    The activate ENDPOINT response is byte-identical in shape/values to before
    the collapse: identity, previous-active id, stats counts (from the bulk
    path), the fully-hydrated detail graph, and the empty deactivated_projects
    list. Asserted with two products so the previous-active branch is exercised.
    """
    from api.endpoints.products.lifecycle import activate_product as activate_endpoint

    tenant_key = TestData.generate_tenant_key()

    product_a = _add_product(db_session, tenant_key, "Product A", is_active=True)
    product_b = _add_product(db_session, tenant_key, "Product B", is_active=False)
    await db_session.flush()

    # Give B real stats data + a detail relation, so the response numbers are
    # non-trivial and the single full hydration is proven to load relations.
    _add_project(db_session, tenant_key, product_b.id, ProjectStatus.ACTIVE, 10)
    _add_project(db_session, tenant_key, product_b.id, ProjectStatus.COMPLETED, 11)
    _add_task(db_session, tenant_key, product_b.id, "pending")
    _add_task(db_session, tenant_key, product_b.id, "completed")
    _add_vision(db_session, tenant_key, product_b.id, "Vision B")
    db_session.add(
        ProductTechStack(
            product_id=product_b.id,
            tenant_key=tenant_key,
            programming_languages="Python",
            frontend_frameworks="Vue",
            backend_frameworks="FastAPI",
            databases_storage="PostgreSQL",
            infrastructure="Railway",
            dev_tools="pytest",
        )
    )
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    # The numbers the legacy singular stats path would produce.
    legacy = await service.memory.get_product_statistics(str(product_b.id))

    current_user = SimpleNamespace(username="tester", tenant_key=tenant_key)
    response = await activate_endpoint(
        product_id=str(product_b.id),
        current_user=current_user,
        service=service,
    )

    # Identity + previous-active branch.
    assert response.product_id == str(product_b.id)
    assert response.previous_active_product_id == str(product_a.id)
    assert response.message == f"Product '{product_b.name}' activated successfully"
    assert response.deactivated_projects == []

    # Product payload: active override + identity.
    assert response.product.id == str(product_b.id)
    assert response.product.name == product_b.name
    assert response.product.is_active is True

    # Stats counts byte-identical to the legacy singular path.
    assert response.product.project_count == legacy.project_count
    assert response.product.task_count == legacy.task_count
    assert response.product.unresolved_tasks == legacy.unresolved_tasks
    assert response.product.unfinished_projects == legacy.unfinished_projects
    assert response.product.vision_documents_count == legacy.vision_documents_count
    assert response.product.has_vision == legacy.has_vision
    # Spot-check known-correct values so a both-paths bug can't pass silently.
    assert response.product.project_count == 2
    assert response.product.task_count == 2
    assert response.product.unresolved_tasks == 1
    assert response.product.vision_documents_count == 1
    assert response.product.has_vision is True

    # The single full hydration still loads the detail graph.
    assert response.product.tech_stack is not None
    assert response.product.tech_stack.programming_languages == "Python"


@pytest.mark.asyncio
async def test_lean_previous_active_fetch_issues_fewer_statements(db_session, db_manager):
    """
    O(query) guard: reading the previously-active product LEAN
    (``eager_load=False``) issues materially fewer SQL statements than the eager
    fetch — the four relation selectin loads are gone. This is the redundant
    hydration the activate endpoint dropped.
    """
    tenant_key = TestData.generate_tenant_key()

    product = _add_product(db_session, tenant_key, "Active Product", is_active=True)
    # FE-9524: get_default_product now queries is_default (a single explicit
    # row is one SELECT; without it the sole-shown-product fallback issues
    # two more, which would inflate this statement count).
    product.is_default = True
    await db_session.flush()
    # Relations exist, so the eager path actually issues its selectin loads.
    _add_vision(db_session, tenant_key, product.id, "Vision A")
    db_session.add(
        ProductTechStack(
            product_id=product.id,
            tenant_key=tenant_key,
            programming_languages="Python",
        )
    )
    await db_session.commit()

    service = ProductService(db_manager, tenant_key=tenant_key, test_session=db_session)

    sync_engine = db_manager.async_engine.sync_engine
    counter = {"n": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        counter["n"] = 0
        lean = await service.get_default_product(eager_load=False)
        lean_stmts = counter["n"]

        counter["n"] = 0
        eager = await service.get_default_product(eager_load=True)
        eager_stmts = counter["n"]
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    assert lean is not None
    assert eager is not None
    # The lean path is a single SELECT (no relation loads); the eager path adds
    # the four selectin loads on top.
    assert lean_stmts == 1
    assert eager_stmts > lean_stmts
