# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9531: the soft-delete reaper died on any template a product had assigned.

The reaper failed on any template a product had assigned, violating
``product_agent_assignments``'s NOT NULL ``template_id``, and the per-item
``except`` reported success regardless.

TSK-6132's own suite covers this reaper three ways per entity and still missed
it, because every template it builds is unassigned. The defect needed a product
to have the template assigned -- the ordinary state of any real tenant.

Two defects, stacked, pinned separately below: fixing only the first would leave
the second waiting for the next unexpected error.

**Defect 1 -- the relationship nulls the child instead of cascading.**
``ProductAgentAssignment.template`` was declared with a bare
``backref="product_assignments"``. With no ``cascade``/``passive_deletes``,
SQLAlchemy's default on parent delete is to load the children and SET THEIR FK
TO NULL -- straight into ``template_id``'s ``nullable=False``. The database FK is
already ``ON DELETE CASCADE``, so the database would have done this correctly if
the ORM had let it.

The sibling relationship on the SAME table, ``Product.agent_assignments``, was
declared with ``cascade="all, delete-orphan", passive_deletes=True`` and works.
Deleting a product was fine; deleting a template was not. One table, two
relationships, one configured.

**Defect 2 -- the per-template ``except`` continued on a poisoned session.**
``purge_expired_deleted_templates`` wraps each template in try/except so one bad
row cannot stop the sweep. Without a savepoint that did the opposite: a failed
flush leaves the session rolled back, so every LATER template failed too, and
the masking "transaction has been rolled back" error is what surfaced rather
than the real cause. The docstring above the loop asserted the steps were
"FK-safe" -- a comment claiming a guarantee the code does not provide, which is
why nobody found this sooner.

Real DB (rollback-isolated ``db_session``), parallel-safe: each test mints its
own rows and shares the fixture session with the service, matching
``test_tsk6132_softdelete_reaper.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from giljo_mcp.domain.soft_delete import RECOVER_WINDOW_DAYS
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.template_service import TemplateService


_EXPIRED = datetime.now(UTC) - timedelta(days=RECOVER_WINDOW_DAYS + 5)


def _tpl_service(db_manager, tenant_key, db_session) -> TemplateService:
    """Service bound to the TEST's session, so rows written here are visible to it."""
    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = tenant_key
    return TemplateService(db_manager=db_manager, tenant_manager=mock_tm, session=db_session)


async def _trashed_template(db_session, tenant_key: str, name_hint: str) -> AgentTemplate:
    tpl = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"be9531-{name_hint}-{uuid4().hex[:8]}",
        role="custom",
        category="custom",
        system_instructions="# Test\nBE-9531 reaper template.",
        is_active=True,
        version="1.0.0",
        deleted_at=_EXPIRED,
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _product(db_session, tenant_key: str) -> Product:
    product = Product(id=str(uuid4()), tenant_key=tenant_key, name=f"be9531-product-{uuid4().hex[:8]}")
    db_session.add(product)
    await db_session.flush()
    return product


def test_assignment_relationship_cascades_rather_than_nulling() -> None:
    """Pin the mapper configuration itself -- the cheapest guard against regression.

    Asserts the ORM is told to let the database's ON DELETE CASCADE do the work
    instead of loading children and nulling a NOT NULL column. Needs no database,
    so it fails fast and points straight at the mapper rather than at a symptom
    three layers away.
    """
    backref_cfg = ProductAgentAssignment.template.property.backref

    assert backref_cfg is not None, "template relationship lost its backref"
    assert not isinstance(backref_cfg, str), (
        "ProductAgentAssignment.template uses a bare string backref. On template "
        "delete SQLAlchemy will NULL product_agent_assignments.template_id, which "
        "is nullable=False. Use backref(..., cascade='all, delete-orphan', "
        "passive_deletes=True) as Product.agent_assignments already does."
    )

    _name, kwargs = backref_cfg
    assert kwargs.get("passive_deletes") is True, "must defer to the database's ON DELETE CASCADE"
    assert "delete" in (kwargs.get("cascade") or ""), "ORM-side delete cascade missing"


@pytest.mark.asyncio
async def test_reaper_purges_a_template_a_product_has_assigned(db_manager, db_session, test_tenant_key):
    """The live failure, reproduced: an expired template WITH an assignment.

    Pre-fix the NotNullViolationError fires inside the loop, the per-template
    ``except`` swallows it, and the reaper reports 0 purged while the template
    stays forever. That silent zero is the shape of the production bug.
    """
    svc = _tpl_service(db_manager, test_tenant_key, db_session)
    tpl = await _trashed_template(db_session, test_tenant_key, "assigned")
    product = await _product(db_session, test_tenant_key)
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            product_id=product.id,
            template_id=tpl.id,
        )
    )
    await db_session.flush()

    purged = await svc.purge_expired_deleted_templates(test_tenant_key)

    assert purged == 1, "the reaper silently skipped a template it was supposed to purge"

    remaining = (
        await db_session.execute(select(func.count()).select_from(AgentTemplate).where(AgentTemplate.id == tpl.id))
    ).scalar_one()
    assert remaining == 0, "the template survived its own purge"

    orphans = (
        await db_session.execute(
            select(func.count()).select_from(ProductAgentAssignment).where(ProductAgentAssignment.template_id == tpl.id)
        )
    ).scalar_one()
    assert orphans == 0, "the assignment outlived its template -- the database cascade did not run"


@pytest.mark.asyncio
async def test_one_failing_template_does_not_kill_the_rest_of_the_sweep(
    db_manager, db_session, test_tenant_key, monkeypatch
):
    """Defect 2: a failure on one template must not poison the others.

    The failure injected here is a REAL failed flush -- an IntegrityError from a
    NOT NULL violation, the same class the live bug produced. That matters: an
    earlier draft of this test raised a plain ``RuntimeError`` instead, which the
    ``except`` caught without the session ever entering a rolled-back state, so
    the test passed with the savepoint removed. A checker that cannot go red
    proves nothing, so this one is written to reproduce the mechanism, not the
    symptom.

    Order-independent by construction: whichever template the reaper reaches
    first is the one that fails, and the other must still be purged.
    """
    svc = _tpl_service(db_manager, test_tenant_key, db_session)
    await _trashed_template(db_session, test_tenant_key, "one")
    await _trashed_template(db_session, test_tenant_key, "two")

    real_delete = svc._repo.delete_template
    poisoned = {"done": False}

    async def _poison_first(session, template):
        """Fail the first template with a genuine flush error, then behave."""
        if not poisoned["done"]:
            poisoned["done"] = True
            session.add(
                ProductAgentAssignment(
                    id=str(uuid4()),
                    tenant_key=test_tenant_key,
                    product_id=None,  # NOT NULL -> IntegrityError on flush
                    template_id=template.id,
                )
            )
            await session.flush()
            raise AssertionError("the injected NOT NULL violation did not raise")
        return await real_delete(session, template)

    monkeypatch.setattr(svc._repo, "delete_template", _poison_first)

    purged = await svc.purge_expired_deleted_templates(test_tenant_key)

    assert poisoned["done"], "the test never triggered its own failure -- it proves nothing"
    assert purged == 1, (
        "one failing template stopped the whole sweep -- the session stayed poisoned "
        "for every later template, which is exactly what the savepoint prevents"
    )
