# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.
"""SEC-9272 -- tenant-guard Class-A/B discriminator hardening (pre-existing weakness).

SEC-9156 taught the no-match UPDATE/DELETE branch in ``_enforce_tenant_scope`` to
raise for Class-B (no explicit tenant predicate at all) while leaving Class-A
(statement carries SOME explicit ``tenant_key == <value>`` predicate on a
registered model) as warn-and-continue. That discriminator only checked
PRESENCE of an explicit predicate -- never that the predicate's VALUE matches the
tenant the session is actually authenticated as. A statement carrying an explicit
``tenant_key == '<some other tenant>'`` predicate (e.g. a caller bug that threads
the wrong tenant_key variable into a query, or references a real OTHER tenant's
id) was classified Class-A and allowed to proceed unraised even though the write
is not actually scoped to the caller's own tenant -- a real cross-tenant write the
guard was supposed to catch.

This is pre-existing (predates SEC-9156 entirely -- the presence-only check was
already the discriminator before the raise even existed) and is closed by cross-
checking ``_tenant_predicate_values`` (already used by the SEPARATE flush-derived
branch a few lines up, just never reused by the no-match branch) against the
resolved tenant_key for this execute.

Session-state note: the tests below set ``db_session.info["tenant_key"]`` BEFORE
adding/flushing the row (not after, unlike test_sec9156_guard_failclosed.py's
matching-value tests). This matters: the ``after_flush`` listener
(``_record_single_tenant_flush``) only stamps ``TENANT_CONTEXT_SOURCE_KEY =
"flush"`` when ``tenant_key`` was NOT already set at flush time. Setting it first
keeps the session on the ordinary "service" path so these tests exercise the
no-match branch's OWN discriminator, not the separate (already value-checked)
flush-derived branch a few lines above it in ``_enforce_tenant_scope``.

Fail-first proof: ``test_classb_wrong_tenant_value_predicate_raises`` is RED
against pre-fix ``tenant_guard.py`` (``pytest.raises`` reports "DID NOT RAISE" --
the wrong-tenant-value delete is waved through as Class-A and actually deletes the
other tenant's row) and GREEN after the value-check hardening. The remaining
tests pin the three untouched behaviors so the fix cannot regress them.

Scope note: this closes the predicate VALUE dimension only (a predicate present
but naming the wrong tenant). It does NOT touch the separate COVERAGE dimension
(whether every touched model individually carries its own matching predicate) --
that stays exactly as SEC-9156 left it; there is no live caller shape that hits it.

FIX1 (post-shipping follow-up, bottom of this file): a deferred ``bindparam()``
tenant predicate -- SQLAlchemy's idiomatic bulk UPDATE/DELETE shape, where the
value is supplied at ``execute()`` time rather than compiled into the statement --
was a false-positive-raise blind spot in the value-check above: reading
``BindParameter.value`` alone sees nothing for that shape (SQLAlchemy leaves it
``None``), so a genuinely correctly-scoped write would misclassify as Class-B and
raise. Closed by falling back to resolving the bind by its ``.key`` against
``execute_state.parameters`` (single dict, or an executemany list of dicts unioned
across rows so a mixed-tenant batch still raises).
"""

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


# ---------------------------------------------------------------------------
# THE GAP (fail-first): an explicit predicate for the WRONG tenant must NOT
# be treated as caller-scoped -- it must raise exactly like a genuinely absent
# predicate (Class-B), not be waved through as benign Class-A.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_classb_wrong_tenant_value_predicate_raises(db_session, caplog, monkeypatch):
    """A session authenticated as ``session_tenant`` issues a DELETE whose explicit
    predicate names a DIFFERENT tenant (``other_tenant``) -- and that predicate's
    id + value genuinely match a real row belonging to ``other_tenant``. This must
    raise TenantIsolationError (a real cross-tenant delete attempt), not be
    classified as benign Class-A merely because SOME explicit tenant predicate is
    present on the statement."""
    session_tenant = _tk()
    other_tenant = _tk()
    db_session.info["tenant_key"] = session_tenant  # set BEFORE add/flush -- see module docstring
    product = _product(other_tenant, "classb-wrong-tenant-value")
    db_session.add(product)
    await db_session.flush()
    guard_module._AUDIT_WARN_SEEN.clear()

    # Force the no-match branch (same technique as test_sec9156_guard_failclosed.py):
    # the walk reports Task as "touched" while the DELETE targets Product's table.
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


# ---------------------------------------------------------------------------
# UNCHANGED: Class-A, predicate value matches the session's own tenant -- still
# does NOT raise (the 23 SEC-9156-observed benign callers must survive).
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# UNCHANGED: Class-B, no explicit predicate at all -- still raises (SEC-9156).
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# KILL SWITCH: audit mode still suppresses the raise for the new wrong-value case.
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# FIX1 (post-shipping follow-up): a deferred bindparam() tenant predicate --
# SQLAlchemy's idiomatic bulk UPDATE/DELETE shape, where the value is bound at
# execute() time via `parameters` rather than compiled into the statement --
# was a false-positive-raise blind spot. `_tenant_predicate_values` only read
# `BindParameter.value`, which SQLAlchemy leaves None for this shape, so a
# genuinely correctly-scoped write was misclassified as Class-B and raised.
# No live caller hit this (every current Class-A caller uses the inline-literal
# shape), but it is a latent trap on a load-bearing security control.
#
# Fail-first proof: test_bindparam_matching_value_does_not_raise is RED against
# pre-FIX1 tenant_guard.py (raises TenantIsolationError on a write that is
# actually correctly scoped -- explicit_tenant_values comes back empty because
# `.value` is None on the deferred bind) and GREEN after `_bind_operand_values`
# falls back to resolving by `.key` against execute_state.parameters.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bindparam_matching_value_does_not_raise(db_session, caplog, monkeypatch):
    """(a) A deferred bindparam tenant predicate, resolved at execute() time via a
    single params dict to the SESSION'S OWN tenant, must NOT raise -- this is a
    genuinely correctly-scoped write using SQLAlchemy's idiomatic bulk-write shape,
    not a Class-B write."""
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
    """(b) A deferred bindparam tenant predicate resolved at execute() time to a
    DIFFERENT tenant than the session's must raise -- the value-check must resolve
    the deferred bind, not merely treat an unresolvable bind as automatically unsafe
    (that would coincidentally also raise, but for the wrong reason, and would mask
    case (a) above as broken too)."""
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
    """(c) An executemany (list-of-dicts params) DELETE whose rows carry TWO
    different tenant values must raise -- the union of resolved values across all
    parameter rows is {tenant_a, tenant_b}, not exactly {session tenant}, so a
    mixed-tenant batch can never be waved through just because one row happens to
    match."""
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
