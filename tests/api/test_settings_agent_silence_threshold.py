# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import delete, select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Configuration, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.system_setting import SystemSetting
from giljo_mcp.tenant import TenantManager


ENDPOINT = "/api/v1/settings/system/agent-silence-threshold"
SILENCE_THRESHOLD_KEY = "agent_silence_threshold_minutes"
CSRF_TOKEN = "test-agent-silence-threshold-csrf"


async def _cleanup_tenant_override(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async() as session:
        await session.execute(
            delete(Configuration).where(
                Configuration.tenant_key == tenant_key,
                Configuration.key == SILENCE_THRESHOLD_KEY,
            )
        )
        await session.commit()


async def _cleanup_threshold(db_manager) -> None:
    async with db_manager.get_session_async() as session:
        await session.execute(delete(SystemSetting).where(SystemSetting.key == SILENCE_THRESHOLD_KEY))
        await session.commit()


async def _set_threshold(db_manager, value: str) -> None:
    async with db_manager.get_session_async() as session:
        await session.execute(delete(SystemSetting).where(SystemSetting.key == SILENCE_THRESHOLD_KEY))
        session.add(SystemSetting(key=SILENCE_THRESHOLD_KEY, value=value))
        await session.commit()


async def _admin_headers_and_tenant(db_manager) -> tuple[dict[str, str], str]:
    async with db_manager.get_session_async() as session:
        unique_suffix = uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")

        org = Organization(
            name=f"Admin Org {unique_suffix}",
            slug=f"admin-org-{unique_suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"admin_user_{unique_suffix}",
            email=f"admin_{unique_suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="admin",
            org_id=org.id,
        )
        session.add(user)
        await session.commit()

    token = JWTManager.create_access_token(
        user_id=user.id,
        username=user.username,
        role="admin",
        tenant_key=user.tenant_key,
    )
    headers = {
        "Cookie": f"access_token={token}; csrf_token={CSRF_TOKEN}",
        "X-CSRF-Token": CSRF_TOKEN,
    }
    return headers, tenant_key


async def _admin_headers(db_manager) -> dict[str, str]:
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)
    return headers


@pytest.mark.asyncio
async def test_get_agent_silence_threshold_reads_global_system_setting(api_client, auth_headers, db_manager):
    await _cleanup_threshold(db_manager)
    await _set_threshold(db_manager, "23")

    response = await api_client.get(ENDPOINT, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"agent_silence_threshold_minutes": 23}
    await _cleanup_threshold(db_manager)


@pytest.mark.asyncio
async def test_put_agent_silence_threshold_writes_system_setting(api_client, db_manager):
    await _cleanup_threshold(db_manager)
    headers = await _admin_headers(db_manager)

    response = await api_client.put(
        ENDPOINT,
        headers=headers,
        json={"agent_silence_threshold_minutes": 18},
    )

    assert response.status_code == 200
    assert response.json() == {"agent_silence_threshold_minutes": 18, "message": "Settings updated successfully"}

    async with db_manager.get_session_async() as session:
        result = await session.execute(select(SystemSetting.value).where(SystemSetting.key == SILENCE_THRESHOLD_KEY))
        assert result.scalar_one() == "18"
    await _cleanup_threshold(db_manager)


# ---------------------------------------------------------------------------
# FE-9241: SaaS-configurable agent-silence timer (per-tenant override)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saas_get_agent_silence_threshold_falls_back_to_deployment_default(api_client, db_manager):
    """SaaS, no per-tenant override set: GET returns the deployment-wide default,
    exactly like the CE endpoint would -- the first link in the fallback chain."""
    await _cleanup_threshold(db_manager)
    await _set_threshold(db_manager, "23")
    headers, tenant_key = await _admin_headers_and_tenant(db_manager)

    with patch("api.app_state.GILJO_MODE", "saas"):
        response = await api_client.get(ENDPOINT, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"agent_silence_threshold_minutes": 23}
    await _cleanup_threshold(db_manager)
    await _cleanup_tenant_override(db_manager, tenant_key)


@pytest.mark.asyncio
async def test_saas_put_then_get_persists_tenant_override(api_client, db_manager):
    """SaaS PUT writes a per-tenant override in `configurations` (not system_settings);
    a subsequent GET for the SAME tenant returns that override, not the deployment default."""
    await _cleanup_threshold(db_manager)
    await _set_threshold(db_manager, "23")
    headers, tenant_key = await _admin_headers_and_tenant(db_manager)

    with patch("api.app_state.GILJO_MODE", "saas"):
        put_response = await api_client.put(
            ENDPOINT,
            headers=headers,
            json={"agent_silence_threshold_minutes": 60},
        )
        get_response = await api_client.get(ENDPOINT, headers=headers)

    assert put_response.status_code == 200
    assert put_response.json() == {"agent_silence_threshold_minutes": 60, "message": "Settings updated successfully"}
    assert get_response.status_code == 200
    assert get_response.json() == {"agent_silence_threshold_minutes": 60}

    # The deployment-wide system_settings row must be untouched by the SaaS write.
    async with db_manager.get_session_async() as session:
        result = await session.execute(select(SystemSetting.value).where(SystemSetting.key == SILENCE_THRESHOLD_KEY))
        assert result.scalar_one() == "23"

    await _cleanup_threshold(db_manager)
    await _cleanup_tenant_override(db_manager, tenant_key)


@pytest.mark.asyncio
async def test_saas_agent_silence_threshold_is_tenant_isolated(api_client, db_manager):
    """ADR-009: tenant A's override is invisible to and unaffected by tenant B."""
    await _cleanup_threshold(db_manager)
    await _set_threshold(db_manager, "23")
    headers_a, tenant_a = await _admin_headers_and_tenant(db_manager)
    headers_b, tenant_b = await _admin_headers_and_tenant(db_manager)

    with patch("api.app_state.GILJO_MODE", "saas"):
        put_a = await api_client.put(ENDPOINT, headers=headers_a, json={"agent_silence_threshold_minutes": 99})
        get_b = await api_client.get(ENDPOINT, headers=headers_b)

    assert put_a.status_code == 200
    # Tenant B never set an override -> still sees the deployment default, NOT A's 99.
    assert get_b.status_code == 200
    assert get_b.json() == {"agent_silence_threshold_minutes": 23}

    await _cleanup_threshold(db_manager)
    await _cleanup_tenant_override(db_manager, tenant_a)
    await _cleanup_tenant_override(db_manager, tenant_b)


@pytest.mark.asyncio
async def test_saas_put_agent_silence_threshold_rejects_out_of_range(api_client, db_manager):
    """Boundary validation (1-1440): an out-of-range value is a clean 4xx client
    rejection (ValidationError), never a raw DB 500."""
    headers, tenant_key = await _admin_headers_and_tenant(db_manager)

    with patch("api.app_state.GILJO_MODE", "saas"):
        response = await api_client.put(
            ENDPOINT,
            headers=headers,
            json={"agent_silence_threshold_minutes": 1441},
        )

    assert response.status_code < 500
    assert response.status_code in (400, 422)

    await _cleanup_tenant_override(db_manager, tenant_key)
