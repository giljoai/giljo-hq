# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

import logging
from uuid import uuid4

import pytest
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
async def test_classb_unscoped_delete_raises(db_session, caplog, monkeypatch):
    tenant_key = _tk()
    product = _product(tenant_key, "classb-unscoped")
    db_session.add(product)
    await db_session.flush()
    db_session.info["tenant_key"] = tenant_key
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        with pytest.raises(TenantIsolationError) as exc_info:
            await db_session.execute(sql_delete(Product).where(Product.id == product.id))

    assert "Task" in str(exc_info.value)
    warns = _guard_warns(caplog)
    assert warns, "Class-B raise must still be audit-logged before raising"
    assert "would have blocked" in warns[0] and "Task" in warns[0]


@pytest.mark.asyncio
async def test_classa_explicitly_scoped_delete_does_not_raise(db_session, caplog, monkeypatch):
    tenant_key = _tk()
    product = _product(tenant_key, "classa-scoped")
    db_session.add(product)
    await db_session.flush()
    db_session.info["tenant_key"] = tenant_key
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        result = await db_session.execute(
            sql_delete(Product).where(Product.id == product.id, Product.tenant_key == tenant_key)
        )

    assert result.rowcount == 1, "Class-A write must proceed (no raise, row actually deleted)"
    warns = _guard_warns(caplog)
    assert warns, "Class-A must still be audit-logged (log-only, unchanged)"
    assert "would have blocked" in warns[0] and "explicit tenant predicate" in warns[0]


@pytest.mark.asyncio
async def test_classb_audit_mode_logs_but_does_not_raise(db_session, caplog, monkeypatch):
    monkeypatch.setenv(guard_module._TENANT_GUARD_MODE_ENV, guard_module._TENANT_GUARD_AUDIT_MODE)
    tenant_key = _tk()
    product = _product(tenant_key, "classb-audit")
    db_session.add(product)
    await db_session.flush()
    db_session.info["tenant_key"] = tenant_key
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        result = await db_session.execute(sql_delete(Product).where(Product.id == product.id))

    assert result.rowcount == 1, "audit mode must let the Class-B write proceed (observe-only, no raise)"
    warns = _guard_warns(caplog)
    assert warns, "audit mode must still audit-log the Class-B write (tripwire observation)"
    assert "would have blocked" in warns[0] and "Task" in warns[0]
