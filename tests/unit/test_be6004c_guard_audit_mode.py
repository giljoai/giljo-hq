# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE6004C-0: env-gated audit (observe-only) mode for the fail-closed tenant guard.

Verifies that:
- unset / garbage GILJO_TENANT_GUARD_MODE behaves exactly as enforce (raises),
- =audit converts a contextless tenant-scoped query into a logged WARNING (no raise),
- =audit still applies the tenant filter when a tenant_key IS resolvable (true superset,
  never a blanket no-op).

Parallel-safe: monkeypatch for env + module-global dedupe set, TransactionalTestContext
for DB touches, no test-ordering dependencies.
"""

import logging
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

import giljo_mcp.tenant_guard as guard_module
from giljo_mcp.database import TenantIsolationError
from giljo_mcp.models import Task
from giljo_mcp.models.products import Product
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import TransactionalTestContext


def _tenant_key() -> str:
    return TenantManager.generate_tenant_key()


def _product(tenant_key: str, name: str) -> Product:
    return Product(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        description=f"{name} description",
        product_memory={},
    )


@pytest.fixture(autouse=True)
def _isolate_audit_dedupe(monkeypatch):
    """Give each test a fresh dedupe set so warnings fire deterministically.

    The guard mutates tenant_guard._AUDIT_WARN_SEEN — the canonical binding
    (giljo_mcp.database merely re-exports it via __getattr__, so patching the
    database module would only create a dead shadow attribute). monkeypatch
    restores the original binding at teardown; xdist workers are separate
    processes, so no cross-worker mutable state is shared.
    """
    monkeypatch.setattr(guard_module, "_AUDIT_WARN_SEEN", set())


@pytest.mark.parametrize("mode_value", [None, "foo", "enfore", ""])
@pytest.mark.asyncio
async def test_contextless_query_raises_when_not_audit(db_manager, monkeypatch, mode_value):
    """Unset / typo / empty / garbage values all behave as enforce: contextless raises."""
    if mode_value is None:
        monkeypatch.delenv("GILJO_TENANT_GUARD_MODE", raising=False)
    else:
        monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", mode_value)

    async with TransactionalTestContext(db_manager) as session:
        session.add(_product(_tenant_key(), "ctxless"))
        await session.flush()
        session.info.pop("tenant_key", None)
        session.info.pop("tenant_key_source", None)
        prev = TenantManager.get_current_tenant()
        TenantManager.clear_current_tenant()
        try:
            with pytest.raises(TenantIsolationError):
                await session.execute(select(Product))
        finally:
            if prev:
                TenantManager.set_current_tenant(prev)


@pytest.mark.asyncio
async def test_contextless_query_warns_and_continues_in_audit(db_manager, monkeypatch, caplog):
    """audit: a contextless tenant-scoped query LOGS a WARNING and does NOT raise."""
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "audit")

    async with TransactionalTestContext(db_manager) as session:
        session.add(_product(_tenant_key(), "audit-ctxless"))
        await session.flush()
        session.info.pop("tenant_key", None)
        session.info.pop("tenant_key_source", None)
        prev = TenantManager.get_current_tenant()
        TenantManager.clear_current_tenant()
        try:
            with caplog.at_level(logging.WARNING, logger="giljo_mcp.database"):
                result = await session.execute(select(Product))
                rows = result.scalars().all()
        finally:
            if prev:
                TenantManager.set_current_tenant(prev)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "tenant guard audit" in r.getMessage()]
    assert warnings, "expected an audit WARNING for the contextless tenant-scoped query"
    message = warnings[0].getMessage()
    assert "Product" in message
    assert "statement_type=select" in message
    # The query ran (no raise); audit must not 500.
    assert isinstance(rows, list)


@pytest.mark.asyncio
async def test_uppercase_audit_value_is_normalized(db_manager, monkeypatch, caplog):
    """Env read is .strip().lower(): 'AUDIT' (with whitespace) still enables observe mode."""
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "  AUDIT ")

    async with TransactionalTestContext(db_manager) as session:
        session.add(_product(_tenant_key(), "audit-upper"))
        await session.flush()
        session.info.pop("tenant_key", None)
        session.info.pop("tenant_key_source", None)
        prev = TenantManager.get_current_tenant()
        TenantManager.clear_current_tenant()
        try:
            with caplog.at_level(logging.WARNING, logger="giljo_mcp.database"):
                await session.execute(select(Product))
        finally:
            if prev:
                TenantManager.set_current_tenant(prev)

    assert any("tenant guard audit" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


@pytest.mark.asyncio
async def test_audit_still_applies_tenant_filter_when_context_resolvable(db_manager, monkeypatch):
    """audit is a strict SUPERSET of enforce: when tenant_key is resolvable the filter
    is STILL applied. A row for another tenant must NOT leak through (not a no-op)."""
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "audit")
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()

    async with TransactionalTestContext(db_manager) as session:
        session.add_all([_product(tenant_a, "tenant-a"), _product(tenant_b, "tenant-b")])
        await session.flush()
        session.info["tenant_key"] = tenant_a

        result = await session.execute(select(Product).order_by(Product.name))
        tenants = {p.tenant_key for p in result.scalars().all()}

    assert tenants == {tenant_a}, "audit mode must still scope to the active tenant, not leak tenant_b"


@pytest.mark.asyncio
async def test_audit_dedupes_repeated_contextless_warnings(db_manager, monkeypatch, caplog):
    """Risk R7: repeated identical contextless queries emit ONE warning, not a flood."""
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "audit")

    async with TransactionalTestContext(db_manager) as session:
        session.add(_product(_tenant_key(), "dedupe"))
        await session.flush()
        session.info.pop("tenant_key", None)
        session.info.pop("tenant_key_source", None)
        prev = TenantManager.get_current_tenant()
        TenantManager.clear_current_tenant()
        try:
            with caplog.at_level(logging.WARNING, logger="giljo_mcp.database"):
                for _ in range(5):
                    await session.execute(select(Product))
        finally:
            if prev:
                TenantManager.set_current_tenant(prev)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "tenant guard audit" in r.getMessage()]
    assert len(warnings) == 1, f"expected exactly one de-duped audit warning, got {len(warnings)}"


@pytest.mark.asyncio
async def test_update_no_match_branch_logs_and_raises(db_manager, monkeypatch, caplog):
    """TSK-9008 Step 2 (fail-closed, SEC-9156, shipped): a Class-B UPDATE/DELETE -- touches a
    tenant-scoped model set, no model's table matches the target (no predicate injectable), AND
    carries no explicit tenant predicate -- LOGS via _audit_warn (still, unchanged) and now
    RAISES TenantIsolationError under enforce (the default mode). Superseded assertion: this
    branch used to warn-and-continue (Step 1, log-only); Step 2 makes it fail-closed for the
    genuinely-unscoped case. The Class-A (explicit-predicate) sibling stays warn-and-continue --
    see test_sec9156_guard_failclosed.py::test_classa_explicitly_scoped_delete_does_not_raise.

    This variant forces the branch deterministically (independent of statement shape) by
    making the walk report an unrelated tenant-scoped model as "touched" -- the DELETE's own
    table then never matches any model in that set. The natural statement shape that reaches
    the same branch is covered by test_mapped_class_bulk_update_hits_no_match_branch below.
    """
    tenant_key = _tenant_key()
    product = _product(tenant_key, "no-match-target")

    async with TransactionalTestContext(db_manager) as session:
        session.add(product)
        await session.flush()
        session.info["tenant_key"] = tenant_key

        monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

        with caplog.at_level(logging.WARNING, logger="giljo_mcp.database"):
            with pytest.raises(TenantIsolationError):
                await session.execute(delete(Product).where(Product.id == product.id))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "tenant guard audit" in r.getMessage()]
    assert warnings, "expected an audit WARNING for the no-match UPDATE/DELETE branch (still logged before raising)"
    message = warnings[0].getMessage()
    assert "would have blocked" in message
    assert "Task" in message
    assert "statement_type=delete" in message
    # No explicit tenant predicate in this statement, so no explicit-predicate suffix.
    assert "explicit tenant predicate" not in message


@pytest.mark.asyncio
async def test_mapped_class_bulk_update_now_injects(db_manager, caplog):
    """SEC-9094 flip: a mapped-class bulk update (``update(Product)``) wraps the table in an
    AnnotatedTable, which the OLD identity match could not resolve -- so it used to reach the
    TSK-9008 log-only (warn) branch. The SEC-9094 matcher routes injection through the same
    ``_table_model`` unwrap the detection walk uses, so this shape now INJECTS the tenant
    predicate: the write applies AND the guard is quiet (no "would have blocked" warn). The
    genuinely-unmatchable case still warns AND now raises -- see test_update_no_match_branch_logs_and_raises."""
    tenant_key = _tenant_key()

    async with TransactionalTestContext(db_manager) as session:
        product = _product(tenant_key, "bulk-target")
        session.add(product)
        await session.flush()
        session.info["tenant_key"] = tenant_key

        with caplog.at_level(logging.WARNING, logger="giljo_mcp.database"):
            await session.execute(update(Product).where(Product.tenant_key == tenant_key).values(name="bulk-renamed"))

        # bulk UPDATE bypasses the identity map; populate_existing forces a fresh DB read.
        renamed = (
            await session.execute(
                select(Product).where(Product.id == product.id).execution_options(populate_existing=True)
            )
        ).scalar_one()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "tenant guard audit" in r.getMessage()]
    assert warnings == [], "mapped-class bulk update now injects -- no 'would have blocked' warn"
    assert renamed.name == "bulk-renamed", "the in-tenant mapped-class update must apply"


@pytest.mark.asyncio
async def test_normal_update_is_still_tenant_scoped(db_manager):
    """Regression guard: the new no-match branch must not affect the ordinary UPDATE/DELETE
    path, where the target table DOES match a tenant-scoped model (statement.table identity
    matches model.__table__, the pre-existing match branch) and the tenant predicate is
    injected exactly as before. (Bulk-update against the raw Table -- rather than the mapped
    class -- is what actually satisfies that identity check; see the module's `is` comparison.)
    """
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()

    async with TransactionalTestContext(db_manager) as session:
        session.add_all([_product(tenant_a, "own"), _product(tenant_b, "other")])
        await session.flush()
        session.info["tenant_key"] = tenant_a

        await session.execute(update(Product.__table__).values(name="renamed"))
        session.expire_all()

        # Reads are tenant-scoped too, so verify each tenant's row under its own context.
        rows_a = (await session.execute(select(Product))).scalars().all()
        session.info["tenant_key"] = tenant_b
        rows_b = (await session.execute(select(Product))).scalars().all()

    assert [p.name for p in rows_a] == ["renamed"], (
        "the tenant-scoped update must still apply to the caller's own tenant"
    )
    assert [p.name for p in rows_b] == ["other"], "the tenant predicate must still protect another tenant's row"
