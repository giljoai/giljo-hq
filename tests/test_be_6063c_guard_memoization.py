# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import aliased

from giljo_mcp import database
from giljo_mcp.database import (
    _models_with_tenant_predicate,
    _tenant_models_for_statement,
    register_tenant_scoped_models,
)
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager


@pytest.fixture(autouse=True)
def clear_walk_memo():
    database._clear_walk_memo()
    try:
        yield
    finally:
        database._clear_walk_memo()


@pytest.fixture
def reset_registry():
    snapshot = set(database._REGISTERED_TENANT_SCOPED_MODELS)
    try:
        yield
    finally:
        database._REGISTERED_TENANT_SCOPED_MODELS.clear()
        database._REGISTERED_TENANT_SCOPED_MODELS.update(snapshot)
        register_tenant_scoped_models()


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




def test_memo_returns_same_model_set_across_repeated_shape():
    stmt = select(Project).where(Project.id == "x")
    first = _tenant_models_for_statement(stmt)
    second = _tenant_models_for_statement(stmt)
    assert first == {Project}
    assert second == first


def test_distinct_where_structures_do_not_collide():
    tenant_key = _tenant_key()
    with_pred = select(Project).where(Project.tenant_key == tenant_key)
    without_pred = select(Project).where(Project.id == "x")

    assert _models_with_tenant_predicate(with_pred) == {Project}
    assert _models_with_tenant_predicate(without_pred) == frozenset()
    assert _models_with_tenant_predicate(without_pred) == frozenset()
    assert _models_with_tenant_predicate(with_pred) == {Project}


def test_aliased_vs_plain_do_not_collide():
    plain = select(Project).where(Project.id == "x")
    p_alias = aliased(Project)
    aliased_stmt = select(p_alias).where(p_alias.id == "x")

    assert _tenant_models_for_statement(plain) == {Project}
    assert _tenant_models_for_statement(aliased_stmt) == {Project}
    assert _tenant_models_for_statement(plain) == {Project}


def test_distinct_tables_resolve_distinct_model_sets():
    proj_stmt = select(Project).where(Project.id == "x")
    prod_stmt = select(Product).where(Product.id == "y")
    assert _tenant_models_for_statement(proj_stmt) == {Project}
    assert _tenant_models_for_statement(prod_stmt) == {Product}
    assert _tenant_models_for_statement(proj_stmt) == {Project}
    assert _tenant_models_for_statement(prod_stmt) == {Product}


def test_registration_invalidates_walk_memo(reset_registry):

    class _LateModel:
        pass

    stmt = select(Project).where(Project.id == "x")
    _tenant_models_for_statement(stmt)

    register_tenant_scoped_models(_LateModel)

    assert _LateModel in database._all_tenant_scoped_models()
    assert _tenant_models_for_statement(stmt) == {Project}


def test_non_cacheable_statement_falls_back_to_live_walk(monkeypatch):
    stmt = select(Project).where(Project.id == "x")
    monkeypatch.setattr(stmt, "_generate_cache_key", lambda: None, raising=False)
    assert _tenant_models_for_statement(stmt) == {Project}
    assert _models_with_tenant_predicate(stmt) == frozenset()




@pytest.mark.asyncio
async def test_same_shape_two_tenants_no_bleed_through_memo(db_session):
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "bleed-a")
    product_b = _product(tenant_b, "bleed-b")
    db_session.add_all([product_a, product_b])
    await db_session.commit()

    stmt = select(Product).order_by(Product.name)

    db_session.info["tenant_key"] = tenant_a
    rows_a = (await db_session.execute(stmt)).scalars().all()
    assert {p.tenant_key for p in rows_a} == {tenant_a}

    db_session.info["tenant_key"] = tenant_b
    rows_b = (await db_session.execute(stmt)).scalars().all()
    assert {p.tenant_key for p in rows_b} == {tenant_b}




def test_guard_symbols_reexported_from_database():
    from giljo_mcp import tenant_guard

    assert database.register_tenant_scoped_models is tenant_guard.register_tenant_scoped_models
    assert database.TenantIsolationError is tenant_guard.TenantIsolationError
    assert database.tenant_session_context is tenant_guard.tenant_session_context
    assert database.TENANT_SCOPED_MODELS == tenant_guard.TENANT_SCOPED_MODELS
    assert database._all_tenant_scoped_models() is tenant_guard._all_tenant_scoped_models()


def test_tenant_guard_imports_no_saas():
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module("giljo_mcp.tenant_guard"))
    assert "giljo_mcp.saas" not in source
    assert "from .saas" not in source
    assert "import saas" not in source
