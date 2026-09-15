# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

from uuid import uuid4

import pytest
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy import update as sql_update

from giljo_mcp import tenant_guard
from giljo_mcp.models import Task
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager


def _tk() -> str:
    return TenantManager.generate_tenant_key()


def _use_tenant(session, tenant: str) -> None:
    session.info["tenant_key"] = tenant
    session.info[tenant_guard.TENANT_CONTEXT_SOURCE_KEY] = "service"


def _guard_warns(caplog) -> list[str]:
    return [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == "giljo_mcp.tenant_guard" and "tenant guard audit" in rec.getMessage()
    ]


async def _mk_template(session, tenant: str, version: str = "1.0.0") -> AgentTemplate:
    tpl = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant,
        name="orchestrator",
        category="core",
        system_instructions="do things",
        version=version,
    )
    session.add(tpl)
    await session.flush()
    return tpl


async def _read_version(session, tenant: str, template_id: str) -> str:
    session.info["tenant_key"] = tenant
    row = (
        await session.execute(
            select(AgentTemplate).where(AgentTemplate.id == template_id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else row.version


@pytest.mark.asyncio
async def test_mapped_update_injects_and_is_tenant_scoped(db_session, caplog):
    tenant_a, tenant_b = _tk(), _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    tpl_b = await _mk_template(db_session, tenant_b)
    await db_session.commit()
    tenant_guard._AUDIT_WARN_SEEN.clear()

    _use_tenant(db_session, tenant_a)
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(sql_update(AgentTemplate).where(AgentTemplate.id == tpl_a.id).values(version="a-new"))
        await db_session.execute(sql_update(AgentTemplate).where(AgentTemplate.id == tpl_b.id).values(version="hijack"))
    await db_session.flush()

    assert _guard_warns(caplog) == [], "mapped update(Model) must inject, not warn, after SEC-9094"
    assert await _read_version(db_session, tenant_a, tpl_a.id) == "a-new", "in-tenant mapped update must apply"
    assert await _read_version(db_session, tenant_b, tpl_b.id) == "1.0.0", "cross-tenant row must be scoped out"


@pytest.mark.asyncio
async def test_mapped_delete_injects_and_is_tenant_scoped(db_session, caplog):
    tenant_a, tenant_b = _tk(), _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    tpl_b = await _mk_template(db_session, tenant_b)
    await db_session.commit()
    tenant_guard._AUDIT_WARN_SEEN.clear()

    _use_tenant(db_session, tenant_a)
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(sql_delete(AgentTemplate).where(AgentTemplate.id == tpl_b.id))
        await db_session.execute(sql_delete(AgentTemplate).where(AgentTemplate.id == tpl_a.id))
    await db_session.flush()

    assert _guard_warns(caplog) == [], "mapped delete(Model) must inject, not warn, after SEC-9094"
    assert await _read_version(db_session, tenant_a, tpl_a.id) is None, "in-tenant mapped delete must apply"
    assert await _read_version(db_session, tenant_b, tpl_b.id) == "1.0.0", "cross-tenant row must survive"


@pytest.mark.asyncio
async def test_mapped_update_with_foreign_tenant_predicate_matches_nothing(db_session, caplog):
    tenant_a, tenant_b = _tk(), _tk()
    tpl_b = await _mk_template(db_session, tenant_b)
    await db_session.commit()
    tenant_guard._AUDIT_WARN_SEEN.clear()

    _use_tenant(db_session, tenant_a)
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(
            sql_update(AgentTemplate)
            .where(AgentTemplate.id == tpl_b.id, AgentTemplate.tenant_key == tenant_b)
            .values(version="hijack")
        )
    await db_session.flush()

    assert _guard_warns(caplog) == [], "explicit-foreign-predicate mapped update must inject, not warn"
    assert await _read_version(db_session, tenant_b, tpl_b.id) == "1.0.0", "foreign-tenant row must be untouched"


@pytest.mark.asyncio
async def test_mapped_update_same_tenant_explicit_predicate_still_updates(db_session, caplog):
    tenant_a = _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    await db_session.commit()
    tenant_guard._AUDIT_WARN_SEEN.clear()

    _use_tenant(db_session, tenant_a)
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(
            sql_update(AgentTemplate)
            .where(AgentTemplate.id == tpl_a.id, AgentTemplate.tenant_key == tenant_a)
            .values(version="a-new")
        )
    await db_session.flush()

    assert _guard_warns(caplog) == [], "same-tenant explicit-predicate mapped update must inject, not warn"
    assert await _read_version(db_session, tenant_a, tpl_a.id) == "a-new", "in-tenant update must apply"


@pytest.mark.asyncio
async def test_raw_table_update_still_injects_and_is_scoped(db_session, caplog):
    tenant_a, tenant_b = _tk(), _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    tpl_b = await _mk_template(db_session, tenant_b)
    await db_session.commit()
    tenant_guard._AUDIT_WARN_SEEN.clear()

    t = AgentTemplate.__table__
    _use_tenant(db_session, tenant_a)
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(sql_update(t).where(t.c.id == tpl_a.id).values(version="a-new"))
        await db_session.execute(sql_update(t).where(t.c.id == tpl_b.id).values(version="hijack"))
    await db_session.flush()

    assert _guard_warns(caplog) == [], "raw update(Table) is the pre-existing inject path -- still no warn"
    assert await _read_version(db_session, tenant_a, tpl_a.id) == "a-new"
    assert await _read_version(db_session, tenant_b, tpl_b.id) == "1.0.0", "raw-table cross-tenant row scoped out"


@pytest.mark.asyncio
async def test_select_scoping_unchanged(db_session):
    tenant_a, tenant_b = _tk(), _tk()
    await _mk_template(db_session, tenant_a)
    await _mk_template(db_session, tenant_b)
    await db_session.commit()

    _use_tenant(db_session, tenant_a)
    rows_a = (await db_session.execute(select(AgentTemplate))).scalars().all()
    assert all(r.tenant_key == tenant_a for r in rows_a), "SELECT still returns only the in-tenant rows"
    assert any(r.tenant_key == tenant_a for r in rows_a)


@pytest.mark.asyncio
async def test_genuine_no_match_warns_and_raises(db_session, caplog, monkeypatch):
    tenant_a = _tk()
    prod = Product(id=str(uuid4()), tenant_key=tenant_a, name="no-match", description="x", product_memory={})
    db_session.add(prod)
    await db_session.flush()
    _use_tenant(db_session, tenant_a)
    tenant_guard._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(tenant_guard, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        with pytest.raises(tenant_guard.TenantIsolationError):
            await db_session.execute(sql_delete(Product).where(Product.id == prod.id))

    warns = _guard_warns(caplog)
    assert warns, "a genuinely-unmatchable UPDATE/DELETE must still be audit-logged before raising"
    assert any("would have blocked" in m and "Task" in m for m in warns)
