# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    monkeypatch.setattr(guard_module, "_AUDIT_WARN_SEEN", set())


@pytest.mark.parametrize("mode_value", [None, "foo", "enfore", ""])
@pytest.mark.asyncio
async def test_contextless_query_raises_when_not_audit(db_manager, monkeypatch, mode_value):
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
    assert isinstance(rows, list)


@pytest.mark.asyncio
async def test_uppercase_audit_value_is_normalized(db_manager, monkeypatch, caplog):
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
    assert "explicit tenant predicate" not in message


@pytest.mark.asyncio
async def test_mapped_class_bulk_update_now_injects(db_manager, caplog):
    tenant_key = _tenant_key()

    async with TransactionalTestContext(db_manager) as session:
        product = _product(tenant_key, "bulk-target")
        session.add(product)
        await session.flush()
        session.info["tenant_key"] = tenant_key

        with caplog.at_level(logging.WARNING, logger="giljo_mcp.database"):
            await session.execute(update(Product).where(Product.tenant_key == tenant_key).values(name="bulk-renamed"))

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
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()

    async with TransactionalTestContext(db_manager) as session:
        session.add_all([_product(tenant_a, "own"), _product(tenant_b, "other")])
        await session.flush()
        session.info["tenant_key"] = tenant_a

        await session.execute(update(Product.__table__).values(name="renamed"))
        session.expire_all()

        rows_a = (await session.execute(select(Product))).scalars().all()
        session.info["tenant_key"] = tenant_b
        rows_b = (await session.execute(select(Product))).scalars().all()

    assert [p.name for p in rows_a] == ["renamed"], (
        "the tenant-scoped update must still apply to the caller's own tenant"
    )
    assert [p.name for p in rows_b] == ["other"], "the tenant predicate must still protect another tenant's row"
