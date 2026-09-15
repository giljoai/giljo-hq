# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

import logging
from uuid import uuid4

import pytest
from sqlalchemy import bindparam
from sqlalchemy import delete as sql_delete

import giljo_mcp.tenant_guard as guard_module
from giljo_mcp.models import Task
from giljo_mcp.models.products import Product
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tenant_guard import TenantIsolationError


def _tk() -> str:
    return TenantManager.generate_tenant_key()


def _product(tenant_key: str, name: str) -> Product:
    return Product(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        description=f"{name} description",
        product_memory={},
    )


def _guard_warns(caplog) -> list[str]:
    return [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == "giljo_mcp.tenant_guard" and "tenant guard audit" in rec.getMessage()
    ]


@pytest.mark.asyncio
async def test_classb_wrong_tenant_value_predicate_raises(db_session, caplog, monkeypatch):
    session_tenant = _tk()
    other_tenant = _tk()
    db_session.info["tenant_key"] = session_tenant
    product = _product(other_tenant, "classb-wrong-tenant-value")
    db_session.add(product)
    await db_session.flush()
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        with pytest.raises(TenantIsolationError) as exc_info:
            await db_session.execute(
                sql_delete(Product).where(Product.id == product.id, Product.tenant_key == other_tenant)
            )

    assert "Task" in str(exc_info.value)
    warns = _guard_warns(caplog)
    assert warns, "a wrong-tenant-value write must still be audit-logged before raising"
    assert "would have blocked" in warns[0]
    assert "do not match this tenant" in warns[0]


@pytest.mark.asyncio
async def test_classa_matching_tenant_value_still_does_not_raise(db_session, caplog, monkeypatch):
    tenant_key = _tk()
    db_session.info["tenant_key"] = tenant_key
    product = _product(tenant_key, "classa-matching-value")
    db_session.add(product)
    await db_session.flush()
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        result = await db_session.execute(
            sql_delete(Product).where(Product.id == product.id, Product.tenant_key == tenant_key)
        )

    assert result.rowcount == 1, "correctly-scoped Class-A write must still proceed unraised"
    warns = _guard_warns(caplog)
    assert warns
    assert "do not match this tenant" not in warns[0]


@pytest.mark.asyncio
async def test_classb_no_predicate_still_raises(db_session, caplog, monkeypatch):
    tenant_key = _tk()
    db_session.info["tenant_key"] = tenant_key
    product = _product(tenant_key, "classb-no-predicate")
    db_session.add(product)
    await db_session.flush()
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        with pytest.raises(TenantIsolationError):
            await db_session.execute(sql_delete(Product).where(Product.id == product.id))

    warns = _guard_warns(caplog)
    assert warns
    assert "explicit tenant predicate" not in warns[0]


@pytest.mark.asyncio
async def test_classb_wrong_tenant_value_audit_mode_logs_but_does_not_raise(db_session, caplog, monkeypatch):
    monkeypatch.setenv(guard_module._TENANT_GUARD_MODE_ENV, guard_module._TENANT_GUARD_AUDIT_MODE)
    session_tenant = _tk()
    other_tenant = _tk()
    db_session.info["tenant_key"] = session_tenant
    product = _product(other_tenant, "classb-wrong-value-audit")
    db_session.add(product)
    await db_session.flush()
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        result = await db_session.execute(
            sql_delete(Product).where(Product.id == product.id, Product.tenant_key == other_tenant)
        )

    assert result.rowcount == 1, "audit mode must let the write proceed (observe-only, no raise)"
    warns = _guard_warns(caplog)
    assert warns


@pytest.mark.asyncio
async def test_bindparam_matching_value_does_not_raise(db_session, caplog, monkeypatch):
    tenant_key = _tk()
    db_session.info["tenant_key"] = tenant_key
    product = _product(tenant_key, "bindparam-matching-value")
    db_session.add(product)
    await db_session.flush()
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    stmt = sql_delete(Product).where(Product.id == product.id, Product.tenant_key == bindparam("tk"))
    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        result = await db_session.execute(stmt, {"tk": tenant_key})

    assert result.rowcount == 1, "a deferred bindparam predicate matching this tenant must proceed unraised"
    warns = _guard_warns(caplog)
    assert warns
    assert "do not match this tenant" not in warns[0]


@pytest.mark.asyncio
async def test_bindparam_wrong_tenant_value_raises(db_session, caplog, monkeypatch):
    session_tenant = _tk()
    other_tenant = _tk()
    db_session.info["tenant_key"] = session_tenant
    product = _product(other_tenant, "bindparam-wrong-value")
    db_session.add(product)
    await db_session.flush()
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    stmt = sql_delete(Product).where(Product.id == product.id, Product.tenant_key == bindparam("tk"))
    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        with pytest.raises(TenantIsolationError):
            await db_session.execute(stmt, {"tk": other_tenant})

    warns = _guard_warns(caplog)
    assert warns
    assert "do not match this tenant" in warns[0]


@pytest.mark.asyncio
async def test_bindparam_executemany_mixed_tenants_raises(db_session, caplog, monkeypatch):
    tenant_a = _tk()
    tenant_b = _tk()
    db_session.info["tenant_key"] = tenant_a
    product_a = _product(tenant_a, "bindparam-executemany-a")
    product_b = _product(tenant_b, "bindparam-executemany-b")
    db_session.add_all([product_a, product_b])
    await db_session.flush()
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    stmt = sql_delete(Product).where(Product.id == bindparam("pid"), Product.tenant_key == bindparam("tk"))
    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        with pytest.raises(TenantIsolationError):
            await db_session.execute(
                stmt,
                [
                    {"pid": product_a.id, "tk": tenant_a},
                    {"pid": product_b.id, "tk": tenant_b},
                ],
            )

    warns = _guard_warns(caplog)
    assert warns
    assert "do not match this tenant" in warns[0]
