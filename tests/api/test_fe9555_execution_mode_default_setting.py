# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.tenant import TenantManager


ENDPOINT = "/api/v1/settings/execution-mode-default"
CSRF_TOKEN = "test-execution-mode-default-csrf"


async def _admin_headers_and_tenant(db_manager) -> tuple[dict[str, str], str]:
    async with db_manager.get_session_async() as session:
        suffix = uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")

        org = Organization(
            name=f"EMD Org {suffix}",
            slug=f"emd-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"emd_user_{suffix}",
            email=f"emd_{suffix}@example.com",
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


@pytest.mark.asyncio
async def test_defaults_to_ask_when_never_set(api_client, db_manager):
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)

    response = await api_client.get(ENDPOINT, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"execution_mode_default": "ask"}


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["subagent", "multi_terminal", "ask"])
async def test_put_then_get_round_trips_every_choice(api_client, db_manager, choice):
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)

    put_response = await api_client.put(ENDPOINT, headers=headers, json={"execution_mode_default": choice})
    get_response = await api_client.get(ENDPOINT, headers=headers)

    assert put_response.status_code == 200, put_response.text
    assert put_response.json()["execution_mode_default"] == choice
    assert get_response.json() == {"execution_mode_default": choice}


@pytest.mark.asyncio
@pytest.mark.parametrize("junk", ["terminals", "SUBAGENT", "claude", "", "true"])
async def test_a_value_that_is_not_one_of_the_three_is_refused(api_client, db_manager, junk):
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)

    response = await api_client.put(ENDPOINT, headers=headers, json={"execution_mode_default": junk})

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_the_write_preserves_sibling_general_settings(api_client, db_manager):
    headers, tenant_key = await _admin_headers_and_tenant(db_manager)

    async with db_manager.get_session_async() as session:
        service = SettingsService(session, tenant_key)
        general = await service.get_settings("general")
        general["fe9555_sibling_probe"] = "must survive"
        await service.update_settings("general", general)

    response = await api_client.put(ENDPOINT, headers=headers, json={"execution_mode_default": "subagent"})
    assert response.status_code == 200, response.text

    async with db_manager.get_session_async() as session:
        stored = await SettingsService(session, tenant_key).get_settings("general")

    assert stored.get("fe9555_sibling_probe") == "must survive", (
        "the execution-mode write clobbered a sibling key in the general category"
    )
    assert stored.get("execution_mode_default") == "subagent"


@pytest.mark.asyncio
async def test_the_default_is_tenant_isolated(api_client, db_manager):
    headers_a, _tenant_a = await _admin_headers_and_tenant(db_manager)
    headers_b, _tenant_b = await _admin_headers_and_tenant(db_manager)

    put_a = await api_client.put(ENDPOINT, headers=headers_a, json={"execution_mode_default": "subagent"})
    get_b = await api_client.get(ENDPOINT, headers=headers_b)

    assert put_a.status_code == 200
    assert get_b.json() == {"execution_mode_default": "ask"}, "tenant B saw tenant A's execution-mode default"


@pytest.mark.asyncio
async def test_the_stored_value_is_what_staging_actually_reads(api_client, db_manager):
    from giljo_mcp.execution_mode_default import (
        EXECUTION_MODE_DEFAULT_KEY,
        default_stage_mode,
    )

    headers, tenant_key = await _admin_headers_and_tenant(db_manager)
    await api_client.put(ENDPOINT, headers=headers, json={"execution_mode_default": "subagent"})

    async with db_manager.get_session_async() as session:
        stored = await SettingsService(session, tenant_key).get_setting_value(
            "general", EXECUTION_MODE_DEFAULT_KEY, default="ask"
        )

    assert default_stage_mode(stored) == "subagent", (
        f"staging would not honour what the settings endpoint stored (read back {stored!r})"
    )
