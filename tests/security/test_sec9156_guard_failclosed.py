# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.
"""SEC-9156 -- tenant-guard fail-closed flip (TSK-9008 Step 2).

The no-match UPDATE/DELETE branch in ``_enforce_tenant_scope`` used to warn-and-continue for
EVERY case where no tenant predicate could be injected. TSK-9008 Step 1 shipped that as
log-only pending a clean observation window (SEC-9093/SEC-9094 narrowed and instrumented it).
Step 2 (this project) makes the discriminator load-bearing:

  Class-B (``not explicit_tenant_models`` -- the statement carries NO explicit tenant
  predicate at all -- genuinely unscoped) now RAISES ``TenantIsolationError``.

  Class-A (``explicit_tenant_models`` non-empty -- the caller already scoped the statement,
  the walk just couldn't re-inject on this shape) is UNCHANGED: still warn-and-continue. This
  is the 23 observed benign caller-scoped hits (oauth-revoke, account-deletion, first-login,
  worker AgentExecution/AgentTodoItem writes) -- raising there would break legitimate writes.

Both tests force the no-match branch deterministically the same way test_be6004c_guard_audit_mode
and test_sec9094_tenant_guard_matcher do: monkeypatch ``_tenant_models_for_statement`` to report
an unrelated tenant-scoped model as "touched" so the real DELETE target never matches, guaranteeing
the no-match branch regardless of statement shape.
"""

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


# ---------------------------------------------------------------------------
# POSITIVE: Class-B (no explicit tenant predicate) -- genuinely unscoped -- RAISES
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_classb_unscoped_delete_raises(db_session, caplog, monkeypatch):
    """A DELETE with no explicit tenant predicate, whose target table cannot be matched to any
    of the walk-reported tenant models (nothing injectable), must now raise TenantIsolationError
    instead of warn-and-continue. Fail-first proof (reported separately): this exact test does
    NOT raise against the pre-flip code and DOES raise post-flip."""
    tenant_key = _tk()
    product = _product(tenant_key, "classb-unscoped")
    db_session.add(product)
    await db_session.flush()
    db_session.info["tenant_key"] = tenant_key
    guard_module._AUDIT_WARN_SEEN.clear()

    # Force the no-match branch: the walk reports Task as "touched" while the DELETE targets
    # Product's table -> _table_model(Product) is Product, not in {Task} -> nothing injectable.
    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        with pytest.raises(TenantIsolationError) as exc_info:
            await db_session.execute(sql_delete(Product).where(Product.id == product.id))

    assert "Task" in str(exc_info.value)
    # The Sentry-tripwire audit_warn still fires (logged) before the raise -- not silent.
    warns = _guard_warns(caplog)
    assert warns, "Class-B raise must still be audit-logged before raising"
    assert "would have blocked" in warns[0] and "Task" in warns[0]


# ---------------------------------------------------------------------------
# NEGATIVE (load-bearing): Class-A (explicit tenant predicate present) -- does NOT raise
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_classa_explicitly_scoped_delete_does_not_raise(db_session, caplog, monkeypatch):
    """A DELETE that already carries an explicit ``tenant_key == <ctx>`` predicate -- the
    Class-A shape (caller-scoped, walk just can't re-inject on this statement shape) -- must
    NOT raise. This proves the 23 observed benign callers survive the flip: the write proceeds
    and audit-warn still fires (log-only, as before)."""
    tenant_key = _tk()
    product = _product(tenant_key, "classa-scoped")
    db_session.add(product)
    await db_session.flush()
    db_session.info["tenant_key"] = tenant_key
    guard_module._AUDIT_WARN_SEEN.clear()

    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        # Explicit tenant predicate on the statement -> explicit_tenant_models non-empty -> Class-A.
        result = await db_session.execute(
            sql_delete(Product).where(Product.id == product.id, Product.tenant_key == tenant_key)
        )

    assert result.rowcount == 1, "Class-A write must proceed (no raise, row actually deleted)"
    warns = _guard_warns(caplog)
    assert warns, "Class-A must still be audit-logged (log-only, unchanged)"
    assert "would have blocked" in warns[0] and "explicit tenant predicate" in warns[0]


# ---------------------------------------------------------------------------
# KILL SWITCH: observe-only audit mode -- Class-B logs + tripwires but does NOT raise
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_classb_audit_mode_logs_but_does_not_raise(db_session, caplog, monkeypatch):
    """GILJO_TENANT_GUARD_MODE=audit (observe-only) must suppress the Class-B raise -- the same
    kill switch the two sibling raises in _enforce_tenant_scope already honor -- so an operator
    can halt a bad flip without a redeploy. The audit-warn (Sentry tripwire) STILL fires: it is
    observe-only, not blind."""
    monkeypatch.setenv(guard_module._TENANT_GUARD_MODE_ENV, guard_module._TENANT_GUARD_AUDIT_MODE)
    tenant_key = _tk()
    product = _product(tenant_key, "classb-audit")
    db_session.add(product)
    await db_session.flush()
    db_session.info["tenant_key"] = tenant_key
    guard_module._AUDIT_WARN_SEEN.clear()

    # Same forced no-match shape as the enforce-mode test -> genuinely unscoped (Class-B).
    monkeypatch.setattr(guard_module, "_tenant_models_for_statement", lambda statement: frozenset({Task}))

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.tenant_guard"):
        # Class-B under audit mode: logs + tripwires, but does NOT raise -- the write proceeds.
        result = await db_session.execute(sql_delete(Product).where(Product.id == product.id))

    assert result.rowcount == 1, "audit mode must let the Class-B write proceed (observe-only, no raise)"
    warns = _guard_warns(caplog)
    assert warns, "audit mode must still audit-log the Class-B write (tripwire observation)"
    assert "would have blocked" in warns[0] and "Task" in warns[0]
