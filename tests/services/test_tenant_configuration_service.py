# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for TenantConfigurationService's per-tenant agent-silence-threshold override
(FE-9241 — SaaS-configurable agent-silence timer).

Covers the SERVICE layer (the failing layer for this feature per the mandatory
regression-test rule): get/set round trip, boundary validation (int, 1-1440,
raises ValidationError not a DB 500), and tenant isolation (ADR-009 — tenant A's
override is invisible to and unaffected by tenant B).
"""

from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.tenant_configuration_service import TenantConfigurationService


@pytest.mark.asyncio
async def test_get_agent_silence_threshold_minutes_returns_none_when_unset(db_manager, test_tenant_key):
    service = TenantConfigurationService(db_manager=db_manager, tenant_key=test_tenant_key)

    result = await service.get_agent_silence_threshold_minutes()

    assert result is None


@pytest.mark.asyncio
async def test_set_then_get_agent_silence_threshold_minutes_round_trips(db_manager, test_tenant_key):
    service = TenantConfigurationService(db_manager=db_manager, tenant_key=test_tenant_key)

    persisted = await service.set_agent_silence_threshold_minutes(45)
    assert persisted == 45

    result = await service.get_agent_silence_threshold_minutes()
    assert result == 45


@pytest.mark.asyncio
async def test_set_agent_silence_threshold_minutes_overwrites_previous_value(db_manager, test_tenant_key):
    service = TenantConfigurationService(db_manager=db_manager, tenant_key=test_tenant_key)

    await service.set_agent_silence_threshold_minutes(10)
    await service.set_agent_silence_threshold_minutes(200)

    result = await service.get_agent_silence_threshold_minutes()
    assert result == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [0, -1, 1441, 999999])
async def test_set_agent_silence_threshold_minutes_rejects_out_of_range(db_manager, test_tenant_key, bad_value):
    """1-1440 inclusive is the valid range; a clean ValidationError, not a DB 500."""
    service = TenantConfigurationService(db_manager=db_manager, tenant_key=test_tenant_key)

    with pytest.raises(ValidationError):
        await service.set_agent_silence_threshold_minutes(bad_value)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [5.5, "10", None])
async def test_set_agent_silence_threshold_minutes_rejects_non_int(db_manager, test_tenant_key, bad_value):
    """Untrusted input must be a real int -- a float/str/None is rejected before touching the DB."""
    service = TenantConfigurationService(db_manager=db_manager, tenant_key=test_tenant_key)

    with pytest.raises(ValidationError):
        await service.set_agent_silence_threshold_minutes(bad_value)


@pytest.mark.asyncio
async def test_set_agent_silence_threshold_minutes_accepts_boundary_values(db_manager, test_tenant_key):
    service = TenantConfigurationService(db_manager=db_manager, tenant_key=test_tenant_key)

    assert await service.set_agent_silence_threshold_minutes(1) == 1
    assert await service.set_agent_silence_threshold_minutes(1440) == 1440


@pytest.mark.asyncio
async def test_agent_silence_threshold_is_tenant_isolated(db_manager, test_tenant_key):
    """ADR-009: tenant A's override is invisible to and unaffected by tenant B."""
    from giljo_mcp.tenant import TenantManager

    tenant_a = test_tenant_key
    tenant_b = TenantManager.generate_tenant_key()

    service_a = TenantConfigurationService(db_manager=db_manager, tenant_key=tenant_a)
    service_b = TenantConfigurationService(db_manager=db_manager, tenant_key=tenant_b)

    await service_a.set_agent_silence_threshold_minutes(7)

    # Tenant B never set an override -> still None, unaffected by A's write.
    assert await service_b.get_agent_silence_threshold_minutes() is None
    # Tenant A's own read is unaffected by B's absence.
    assert await service_a.get_agent_silence_threshold_minutes() == 7

    # Now B sets its own, different, value -- A's must not change.
    await service_b.set_agent_silence_threshold_minutes(500)
    assert await service_a.get_agent_silence_threshold_minutes() == 7
    assert await service_b.get_agent_silence_threshold_minutes() == 500
