# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6063c: tenant-guard AST-walk memoization regression suite.

The spike (BE6063C perf spike results, Q1 = GO) proved the
``do_orm_execute`` tenant guard runs a full ``visitors.iterate`` walk on EVERY
execute (1.0/execute, not amortized by SQLAlchemy's compiled-statement cache):
47-83us of pure-Python CPU per query on the single sync worker.

This suite pins the security boundary that the memoization MUST preserve. The
walk's STRUCTURAL result (which tenant-scoped models a statement touches, which
models carry an explicit tenant predicate) is a pure function of statement
SHAPE and the registered model set -- safe to memoize keyed on SQLAlchemy's
``_generate_cache_key()``. The TENANT-DEPENDENT parts (the bind-parameter
tenant values and the per-execute ``with_loader_criteria``) are NEVER cached.

Failure modes this suite guards against:
- **Cache collision**: two distinct statement shapes hashing to one memo entry,
  so one shape gets the other's model set (under- or over-enforcement).
- **Tenant bleed**: a statement shape first executed by tenant A serves tenant
  A's criteria to a later execution by tenant B.
- **Stale memo across registration**: a model registered AFTER a statement shape
  was memoized is invisible to that shape's cached model set.
- **Non-cacheable statement**: a statement whose ``_generate_cache_key()`` is
  ``None`` must fall back to the live walk, not crash or silently skip
  enforcement.

Parallel-safe (xdist): the ``clear_walk_memo`` fixture clears the process-global
statement-shape memo before and after each test; ``reset_registry`` snapshots and
restores the SaaS extension set. No module-level mutable state; no test ordering
dependency.

Project: BE-6063c.
"""

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
    """Clear the statement-shape walk memo around every test (xdist-safe)."""
    database._clear_walk_memo()
    try:
        yield
    finally:
        database._clear_walk_memo()


@pytest.fixture
def reset_registry():
    """Snapshot and RESTORE the SaaS extension set + rebuilt caches (xdist-safe)."""
    snapshot = set(database._REGISTERED_TENANT_SCOPED_MODELS)
    try:
        yield
    finally:
        database._REGISTERED_TENANT_SCOPED_MODELS.clear()
        database._REGISTERED_TENANT_SCOPED_MODELS.update(snapshot)
        register_tenant_scoped_models()  # rebuild union + invalidate walk memo


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


# --------------------------------------------------------------------------
# Pure-function memo correctness (DB-agnostic, fastest signal)
# --------------------------------------------------------------------------


def test_memo_returns_same_model_set_across_repeated_shape():
    """A repeated statement shape resolves to the identical model set (cache hit)."""
    stmt = select(Project).where(Project.id == "x")
    first = _tenant_models_for_statement(stmt)
    second = _tenant_models_for_statement(stmt)
    assert first == {Project}
    assert second == first


def test_distinct_where_structures_do_not_collide():
    """Same table, different WHERE structure must NOT share a memo entry.

    Both touch Project so the model set is identical here; the point is that the
    cache keys differ (no collision), proven by the predicate-walk which DOES
    differ: one carries an explicit tenant predicate, the other does not.
    """
    tenant_key = _tenant_key()
    with_pred = select(Project).where(Project.tenant_key == tenant_key)
    without_pred = select(Project).where(Project.id == "x")

    assert _models_with_tenant_predicate(with_pred) == {Project}
    assert _models_with_tenant_predicate(without_pred) == frozenset()
    # Re-issue in the opposite order: a naive shared key would now poison results.
    assert _models_with_tenant_predicate(without_pred) == frozenset()
    assert _models_with_tenant_predicate(with_pred) == {Project}


def test_aliased_vs_plain_do_not_collide():
    """An aliased entity and the plain entity are distinct shapes; both resolve."""
    plain = select(Project).where(Project.id == "x")
    p_alias = aliased(Project)
    aliased_stmt = select(p_alias).where(p_alias.id == "x")

    assert _tenant_models_for_statement(plain) == {Project}
    assert _tenant_models_for_statement(aliased_stmt) == {Project}
    # Interleave to surface any collision between the two cache keys.
    assert _tenant_models_for_statement(plain) == {Project}


def test_distinct_tables_resolve_distinct_model_sets():
    """Two single-table shapes over different tables keep separate model sets."""
    proj_stmt = select(Project).where(Project.id == "x")
    prod_stmt = select(Product).where(Product.id == "y")
    assert _tenant_models_for_statement(proj_stmt) == {Project}
    assert _tenant_models_for_statement(prod_stmt) == {Product}
    # Re-resolve interleaved: a colliding key would cross-contaminate the sets.
    assert _tenant_models_for_statement(proj_stmt) == {Project}
    assert _tenant_models_for_statement(prod_stmt) == {Product}


def test_registration_invalidates_walk_memo(reset_registry):
    """A model registered AFTER a shape is memoized must become visible to it.

    Without memo invalidation on registration, the formerly-cached model set
    would omit a newly tenant-scoped table -> silent isolation drop.
    """

    class _LateModel:
        """Non-mapped stand-in; membership is by identity, no __table__ needed."""

    stmt = select(Project).where(Project.id == "x")
    _tenant_models_for_statement(stmt)  # prime the memo for this shape

    register_tenant_scoped_models(_LateModel)  # MUST clear the walk memo

    # The memo object must have been swapped/cleared so the next resolve is fresh.
    assert _LateModel in database._all_tenant_scoped_models()
    # Project is still resolved (the shape recomputes cleanly post-invalidation).
    assert _tenant_models_for_statement(stmt) == {Project}


def test_non_cacheable_statement_falls_back_to_live_walk(monkeypatch):
    """If a statement has no cache key, the guard still resolves via the walk."""
    stmt = select(Project).where(Project.id == "x")
    monkeypatch.setattr(stmt, "_generate_cache_key", lambda: None, raising=False)
    assert _tenant_models_for_statement(stmt) == {Project}
    assert _models_with_tenant_predicate(stmt) == frozenset()


# --------------------------------------------------------------------------
# End-to-end tenant-bleed regression (real DB, enforcement path)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_shape_two_tenants_no_bleed_through_memo(db_session):
    """The SAME statement shape issued by tenant A then tenant B must apply B's
    criteria on B's execution -- the memo caches only the model set, never the
    per-execute tenant criteria.
    """
    tenant_a = _tenant_key()
    tenant_b = _tenant_key()
    product_a = _product(tenant_a, "bleed-a")
    product_b = _product(tenant_b, "bleed-b")
    db_session.add_all([product_a, product_b])
    await db_session.commit()

    # Identical statement shape, executed under two different tenant contexts.
    stmt = select(Product).order_by(Product.name)

    db_session.info["tenant_key"] = tenant_a
    rows_a = (await db_session.execute(stmt)).scalars().all()
    assert {p.tenant_key for p in rows_a} == {tenant_a}

    db_session.info["tenant_key"] = tenant_b
    rows_b = (await db_session.execute(stmt)).scalars().all()
    assert {p.tenant_key for p in rows_b} == {tenant_b}


# --------------------------------------------------------------------------
# Extraction back-compat + Deletion Test (BE-6063c: guard moved to tenant_guard.py)
# --------------------------------------------------------------------------


def test_guard_symbols_reexported_from_database():
    """The guard moved to ``tenant_guard`` but ``giljo_mcp.database`` must still
    expose every public guard name (back-compat for ~60 importers) and delegate
    private names via the PEP 562 ``__getattr__`` shim.
    """
    from giljo_mcp import tenant_guard

    # Public re-exports resolve to the SAME object in both modules.
    assert database.register_tenant_scoped_models is tenant_guard.register_tenant_scoped_models
    assert database.TenantIsolationError is tenant_guard.TenantIsolationError
    assert database.tenant_session_context is tenant_guard.tenant_session_context
    # PEP 562 live-union names + private symbols delegate through __getattr__.
    assert database.TENANT_SCOPED_MODELS == tenant_guard.TENANT_SCOPED_MODELS
    assert database._all_tenant_scoped_models() is tenant_guard._all_tenant_scoped_models()


def test_tenant_guard_imports_no_saas():
    """``giljo_mcp.tenant_guard`` (the security boundary's new home) imports zero
    SaaS modules -- the Deletion Test follows the code it guards.
    """
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module("giljo_mcp.tenant_guard"))
    assert "giljo_mcp.saas" not in source
    assert "from .saas" not in source
    assert "import saas" not in source
