# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9212 regression: the context-tuning banner's user lookup honors the guard.

FE-9202 shipped ``_resolve_active_user_id`` running a raw
``select(User.id).where(User.tenant_key == ...)`` inside a plain
``get_session_async()`` session with NO tenant session context. The fail-closed
tenant guard rejects predicate-only scoping, so on the test-install box the 6-hourly
banner refresh logged ``TenantIsolationError`` every tick and the 14-day
context-tuning banner silently never fired for any tenant.

The FE-9202 unit test (test_fe9202_context_tuning_banner.py) missed it because it
monkeypatches ``_resolve_active_user_id`` out at its call site — the one function
that trips the guard in production is the one function stubbed away, and every
case passed ``db_manager=object()`` so no real session/guard ever ran. This is
the BE-9040 burn-in ("mocked sessions miss the tenant guard").

These tests exercise the REAL function against a REAL Postgres session with the
guard pinned to ``enforce`` and the ambient tenant explicitly cleared (the
genuinely-contextless startup baseline — mirrors test_be6004c_guard_bite). Before
the fix both cases RAISE ``TenantIsolationError``; after it they resolve correctly
and tenant-scoped.

Parallel-safe: unique ``tk_...`` tenants, monkeypatch-scoped env, no module-level
mutable state. The positive case COMMITS its own org+user through a real
tenant-scoped session (db_session rolls back and is invisible to the fresh
connection the lookup opens) and deletes them in a finally.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from api.startup import context_tuning_banner as ctb
from giljo_mcp.database import TenantIsolationError  # noqa: F401  (documents the pre-fix failure)
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


@pytest.mark.asyncio
async def test_resolve_active_user_id_finds_tenant_user_under_enforce(db_manager, monkeypatch):
    """The real lookup resolves the tenant's user with the guard active.

    RED before the fix: the contextless ``select(User.id)`` raised
    ``TenantIsolationError``. GREEN after: ``tenant_session_context`` authorizes
    the read and it returns THIS tenant's user id (proving the fix returns real
    data, not a masked None).
    """
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]
    org_id = str(uuid4())
    user_id = str(uuid4())

    # Commit through a genuinely-committing tenant-scoped session: db_session
    # rolls back at teardown, so a row added there is invisible to the fresh
    # connection _resolve_active_user_id opens. The session's tenant context
    # authorizes the writes under the fail-closed guard. INSERTs are not
    # guard-governed (only SELECT/UPDATE/DELETE), so the seed is unaffected.
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Organization(
                id=org_id,
                name=f"BE9212 Org {suffix}",
                slug=f"be9212-org-{suffix}",
                tenant_key=tenant_key,
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"be9212_{suffix}",
                tenant_key=tenant_key,
                role="developer",
                org_id=org_id,
                is_active=True,
            )
        )
        await session.commit()

    try:
        # Clear the ambient tenant the integration autouse fixture set, so the
        # guard sees the genuinely-contextless startup baseline the production bug
        # hit — the fix (not an ambient ContextVar) must authorize the read.
        TenantManager.clear_current_tenant()
        resolved = await ctb._resolve_active_user_id(db_manager, tenant_key)
        assert resolved == user_id
    finally:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(delete(User).where(User.tenant_key == tenant_key))
            await session.execute(delete(Organization).where(Organization.tenant_key == tenant_key))
            await session.commit()


@pytest.mark.asyncio
async def test_resolve_active_user_id_empty_tenant_returns_none_under_enforce(db_manager, monkeypatch):
    """A tenant with no user resolves to None — not a raise, not a cross-tenant leak.

    RED before the fix: the guard raised on the unscoped statement regardless of
    rows. GREEN after: the scoped read finds nothing for this fresh tenant and
    returns None.
    """
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")
    TenantManager.clear_current_tenant()
    empty_tenant = TenantManager.generate_tenant_key()

    resolved = await ctb._resolve_active_user_id(db_manager, empty_tenant)

    assert resolved is None
