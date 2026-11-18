# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.taxonomy_ops import (
    DEFAULT_TAXONOMY_TYPES,
    RESERVED_TYPE_ABBRS,
    ensure_default_types_seeded,
)
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_ALL_ABBRS = sorted(t["abbr"] for t in DEFAULT_TAXONOMY_TYPES)


async def _abbrs(session, tenant_key: str) -> list[str]:
    with tenant_session_context(session, tenant_key):
        rows = await session.execute(select(TaxonomyType.abbreviation).where(TaxonomyType.tenant_key == tenant_key))
        return sorted(rows.scalars().all())


async def _put(session, tenant_key: str, *abbrs: str) -> None:
    with tenant_session_context(session, tenant_key):
        for i, abbr in enumerate(abbrs):
            session.add(
                TaxonomyType(tenant_key=tenant_key, abbreviation=abbr, label=abbr, color="#111111", sort_order=i)
            )
        await session.flush()


@pytest_asyncio.fixture
async def tenants(db_manager, db_session):
    keys = (TenantManager.generate_tenant_key(), TenantManager.generate_tenant_key())
    suffix = uuid4().hex[:8]
    for tk in keys:
        db_session.add(Organization(name=f"Org {tk[-6:]}{suffix}", slug=f"o-{tk[-8:]}", tenant_key=tk, is_active=True))
    await db_session.commit()
    try:
        yield keys
    finally:
        for tk in keys:
            async with db_manager.get_session_async() as cleanup:
                with tenant_session_context(cleanup, tk):
                    await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tk))
                await cleanup.commit()


@pytest.mark.parametrize("stranded", [("TSK",), ("TSK", "HND", "CHT"), ("CHT",)])
async def test_reserved_only_tenant_gets_defaults(db_session, tenants, stranded):
    tenant_key, other = tenants
    await _put(db_session, tenant_key, *stranded)
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    assert await _abbrs(db_session, tenant_key) == _ALL_ABBRS
    assert await _abbrs(db_session, other) == []


@pytest.mark.parametrize("extra", ["BE", "MINE"])
async def test_tenant_with_any_non_reserved_type_is_untouched(db_session, tenants, extra):
    tenant_key, other = tenants
    assert extra not in RESERVED_TYPE_ABBRS
    await _put(db_session, tenant_key, "TSK", extra)
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    assert await _abbrs(db_session, tenant_key) == sorted(["TSK", extra])
    assert await _abbrs(db_session, other) == []


async def test_other_tenant_with_lone_reserved_row_is_not_touched_by_healing_this_one(db_session, tenants):
    tenant_key, other = tenants
    await _put(db_session, tenant_key, "TSK")
    await _put(db_session, other, "TSK")
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    assert await _abbrs(db_session, tenant_key) == _ALL_ABBRS
    assert await _abbrs(db_session, other) == ["TSK"]


async def test_two_racers_heal_without_failure_or_duplicate(db_manager, tenants):
    tenant_key, _ = tenants
    async with db_manager.get_session_async() as s:
        await _put(s, tenant_key, "TSK")
        await s.commit()

    async def racer():
        async with db_manager.get_session_async() as s:
            with tenant_session_context(s, tenant_key):
                await ensure_default_types_seeded(s, tenant_key)
            await s.commit()

    results = await asyncio.gather(racer(), racer(), return_exceptions=True)
    assert [r for r in results if isinstance(r, Exception)] == []
    async with db_manager.get_session_async() as s:
        assert await _abbrs(s, tenant_key) == _ALL_ABBRS
