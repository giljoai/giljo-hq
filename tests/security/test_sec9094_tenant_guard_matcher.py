# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.
"""SEC-9094 -- tenant-guard MATCHER redesign (matcher ONLY; warn->block stays HARD-HELD).

The guard's UPDATE/DELETE injection matched the target table with a raw identity check
(``statement.table is model.__table__``). A mapped-class bulk ``update(Model)`` /
``delete(Model)`` wraps the target in an ``AnnotatedTable`` that fails that identity, so the
statement fell through to the warn-and-continue branch and NO tenant predicate was injected --
the ~123/143 weekly benign warns. SEC-9094 routes injection through the same ``_table_model``
unwrap the guard's DETECTION already uses, so both the raw-table and the mapped-class shapes
inject the tenant predicate.

Two-sided contract pinned here:
  (+) mapped ``update(Model)`` / ``delete(Model)`` on a registered tenant model now injects the
      tenant predicate -- a cross-tenant target row is scoped out, the in-tenant row changes, no warn.
  (+) a mapped update carrying an explicit FOREIGN tenant predicate is scoped to NOTHING (the
      injected ``AND tenant_key == <ctx>`` contradicts it) -- strictly safer than the old
      warn-and-proceed, which executed the cross-tenant write.
  (-) happy path byte-unaffected: raw ``update(Table)`` still injects; SELECT scoping unchanged;
      a genuinely-unmatchable UPDATE/DELETE (target table is not a detected tenant model) still
      WARNS and does NOT raise (enforcement mode is untouched).

Enforcement mode (warn vs raise) is NOT touched by SEC-9094 -- the no-match branch stays warn-mode.
"""

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
    """Simulate a real request-scoped tenant context: an authoritative "service" source, not a
    flush-derived one. (A flush-derived context deliberately cannot authorize an explicit tenant
    predicate -- a pre-existing guard branch orthogonal to the SEC-9094 matcher.)"""
    session.info["tenant_key"] = tenant
    session.info[tenant_guard.TENANT_CONTEXT_SOURCE_KEY] = "service"


def _guard_warns(caplog) -> list[str]:
    """Every tenant-guard audit warning emitted (any class)."""
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
    """Read a template's version under an explicit tenant context (guard scopes SELECTs too)."""
    session.info["tenant_key"] = tenant
    row = (
        await session.execute(
            select(AgentTemplate).where(AgentTemplate.id == template_id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else row.version


# ---------------------------------------------------------------------------
# (+) mapped-class UPDATE now injects + is tenant-scoped (RED before the matcher fix)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mapped_update_injects_and_is_tenant_scoped(db_session, caplog):
    tenant_a, tenant_b = _tk(), _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    tpl_b = await _mk_template(db_session, tenant_b)
    await db_session.commit()
    tenant_guard._AUDIT_WARN_SEEN.clear()

    _use_tenant(db_session, tenant_a)
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        # in-tenant: mapped bulk update to A's own row -> injected tenant_key == A -> applies.
        await db_session.execute(sql_update(AgentTemplate).where(AgentTemplate.id == tpl_a.id).values(version="a-new"))
        # cross-tenant probe: target B's row under tenant-A context -> injected predicate scopes it out.
        await db_session.execute(sql_update(AgentTemplate).where(AgentTemplate.id == tpl_b.id).values(version="hijack"))
    await db_session.flush()

    assert _guard_warns(caplog) == [], "mapped update(Model) must inject, not warn, after SEC-9094"
    assert await _read_version(db_session, tenant_a, tpl_a.id) == "a-new", "in-tenant mapped update must apply"
    assert await _read_version(db_session, tenant_b, tpl_b.id) == "1.0.0", "cross-tenant row must be scoped out"


# ---------------------------------------------------------------------------
# (+) mapped-class DELETE now injects + is tenant-scoped (RED before the matcher fix)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mapped_delete_injects_and_is_tenant_scoped(db_session, caplog):
    tenant_a, tenant_b = _tk(), _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    tpl_b = await _mk_template(db_session, tenant_b)
    await db_session.commit()
    tenant_guard._AUDIT_WARN_SEEN.clear()

    _use_tenant(db_session, tenant_a)
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        # cross-tenant probe first: target B's row under tenant-A context -> scoped out, survives.
        await db_session.execute(sql_delete(AgentTemplate).where(AgentTemplate.id == tpl_b.id))
        # in-tenant: delete A's own row -> injected tenant_key == A -> removed.
        await db_session.execute(sql_delete(AgentTemplate).where(AgentTemplate.id == tpl_a.id))
    await db_session.flush()

    assert _guard_warns(caplog) == [], "mapped delete(Model) must inject, not warn, after SEC-9094"
    assert await _read_version(db_session, tenant_a, tpl_a.id) is None, "in-tenant mapped delete must apply"
    assert await _read_version(db_session, tenant_b, tpl_b.id) == "1.0.0", "cross-tenant row must survive"


# ---------------------------------------------------------------------------
# (+) former Class-A: an explicit FOREIGN tenant predicate is scoped to NOTHING (RED before)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mapped_update_with_foreign_tenant_predicate_matches_nothing(db_session, caplog):
    tenant_a, tenant_b = _tk(), _tk()
    tpl_b = await _mk_template(db_session, tenant_b)
    await db_session.commit()
    tenant_guard._AUDIT_WARN_SEEN.clear()

    _use_tenant(db_session, tenant_a)
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        # attacker carries an explicit tenant_b predicate under tenant-A context: injected AND
        # tenant_key == A contradicts it -> matches nothing. (Old behavior: warn + execute -> hijack.)
        await db_session.execute(
            sql_update(AgentTemplate)
            .where(AgentTemplate.id == tpl_b.id, AgentTemplate.tenant_key == tenant_b)
            .values(version="hijack")
        )
    await db_session.flush()

    assert _guard_warns(caplog) == [], "explicit-foreign-predicate mapped update must inject, not warn"
    assert await _read_version(db_session, tenant_b, tpl_b.id) == "1.0.0", "foreign-tenant row must be untouched"


# ---------------------------------------------------------------------------
# (+) former Class-A same-tenant: explicit in-tenant predicate still applies, no warn (RED before)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# (-) happy path unchanged: raw update(Table) still injects + is tenant-scoped
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# (-) happy path unchanged: SELECT scoping is unaffected by the UPDATE/DELETE matcher change
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# (-) matcher-scope boundary: a genuinely-unmatchable, predicate-absent UPDATE/DELETE still
#     WARNS (audit-logged) -- and, since SEC-9156 shipped Step 2, now also RAISES (Class-B).
#     SEC-9094 only widens WHICH shapes inject; the enforcement-mode flip is a separate,
#     later-authorized change (SEC-9156) pinned here so a revert of either is caught.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_genuine_no_match_warns_and_raises(db_session, caplog, monkeypatch):
    """The target table is NOT a detected tenant model (walk forced to report an unrelated model),
    so nothing is injectable, and the statement carries no explicit tenant predicate (Class-B) --
    the guard audit-logs (unchanged) and now raises TenantIsolationError (SEC-9156)."""
    tenant_a = _tk()
    prod = Product(id=str(uuid4()), tenant_key=tenant_a, name="no-match", description="x", product_memory={})
    db_session.add(prod)
    await db_session.flush()
    _use_tenant(db_session, tenant_a)
    tenant_guard._AUDIT_WARN_SEEN.clear()

    # Force the branch deterministically: the walk reports Task as "touched" while the DELETE
    # targets Product's table -> _table_model(Product) is Product, which is NOT in {Task} -> no inject.
    monkeypatch.setattr(tenant_guard, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        with pytest.raises(tenant_guard.TenantIsolationError):
            await db_session.execute(sql_delete(Product).where(Product.id == prod.id))

    warns = _guard_warns(caplog)
    assert warns, "a genuinely-unmatchable UPDATE/DELETE must still be audit-logged before raising"
    assert any("would have blocked" in m and "Task" in m for m in warns)
