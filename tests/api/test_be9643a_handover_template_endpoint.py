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
from giljo_mcp.services.handover_template import (
    DEFAULT_HANDOVER_TEMPLATE,
    HANDOVER_TEMPLATE_MAX_CHARS,
)
from giljo_mcp.services.handover_validation import REQUIRED_HANDOVER_HEADINGS
from giljo_mcp.tenant import TenantManager


ENDPOINT = "/api/v1/settings/handover-template"
RESET_ENDPOINT = f"{ENDPOINT}/reset"
CSRF_TOKEN = "test-handover-template-csrf"


async def _admin_headers_and_tenant(db_manager) -> tuple[dict[str, str], str]:
    async with db_manager.get_session_async() as session:
        suffix = uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")

        org = Organization(
            name=f"HT Org {suffix}",
            slug=f"ht-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            username=f"ht_user_{suffix}",
            email=f"ht_{suffix}@example.com",
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
async def test_an_account_that_never_set_one_reads_the_default(api_client, db_manager):
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)

    response = await api_client.get(ENDPOINT, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["handover_template"] == DEFAULT_HANDOVER_TEMPLATE
    assert body["is_default"] is True


@pytest.mark.asyncio
async def test_put_then_get_round_trips(api_client, db_manager):
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)
    custom = DEFAULT_HANDOVER_TEMPLATE + "\n## Runbooks\n- one path per line\n"

    put_response = await api_client.put(ENDPOINT, headers=headers, json={"handover_template": custom})
    get_response = await api_client.get(ENDPOINT, headers=headers)

    assert put_response.status_code == 200, put_response.text
    assert put_response.json()["handover_template"] == custom
    assert get_response.json()["handover_template"] == custom
    assert get_response.json()["is_default"] is False


@pytest.mark.asyncio
async def test_a_template_missing_a_required_heading_is_stored_with_it_appended(api_client, db_manager):
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)

    put_response = await api_client.put(
        ENDPOINT,
        headers=headers,
        json={"handover_template": "## Context\nWhat this session was.\n"},
    )

    assert put_response.status_code == 200, put_response.text
    stored = put_response.json()["handover_template"]
    assert "## Context" in stored, "the operator's own section was dropped"
    for heading in REQUIRED_HANDOVER_HEADINGS:
        assert heading in stored, f"{heading} was neither kept nor appended"


@pytest.mark.asyncio
async def test_an_over_length_template_is_refused(api_client, db_manager):
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)

    response = await api_client.put(
        ENDPOINT,
        headers=headers,
        json={"handover_template": "x" * (HANDOVER_TEMPLATE_MAX_CHARS + 1)},
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["context"]["field"] == "handover_template", body
    assert body["context"]["constraint"] == "max_length", body
    assert body["context"]["max_length"] == HANDOVER_TEMPLATE_MAX_CHARS, body
    assert str(HANDOVER_TEMPLATE_MAX_CHARS) in body["message"], body


@pytest.mark.asyncio
async def test_an_over_length_template_does_not_overwrite_the_saved_one(api_client, db_manager):
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)
    custom = DEFAULT_HANDOVER_TEMPLATE + "\n## Runbooks\n- one path per line\n"
    await api_client.put(ENDPOINT, headers=headers, json={"handover_template": custom})

    await api_client.put(ENDPOINT, headers=headers, json={"handover_template": "x" * (HANDOVER_TEMPLATE_MAX_CHARS + 1)})
    get_response = await api_client.get(ENDPOINT, headers=headers)

    assert get_response.json()["handover_template"] == custom


@pytest.mark.asyncio
async def test_reset_restores_the_default(api_client, db_manager):
    headers, _tenant_key = await _admin_headers_and_tenant(db_manager)
    await api_client.put(
        ENDPOINT,
        headers=headers,
        json={"handover_template": DEFAULT_HANDOVER_TEMPLATE + "\n## Runbooks\n- x\n"},
    )

    reset_response = await api_client.post(RESET_ENDPOINT, headers=headers)
    get_response = await api_client.get(ENDPOINT, headers=headers)

    assert reset_response.status_code == 200, reset_response.text
    assert reset_response.json()["handover_template"] == DEFAULT_HANDOVER_TEMPLATE
    assert reset_response.json()["is_default"] is True
    assert get_response.json()["handover_template"] == DEFAULT_HANDOVER_TEMPLATE


@pytest.mark.asyncio
async def test_the_template_is_tenant_scoped(api_client, db_manager):
    headers_a, _tenant_a = await _admin_headers_and_tenant(db_manager)
    headers_b, _tenant_b = await _admin_headers_and_tenant(db_manager)

    await api_client.put(
        ENDPOINT,
        headers=headers_a,
        json={"handover_template": DEFAULT_HANDOVER_TEMPLATE + "\n## Only mine\n- x\n"},
    )
    response_b = await api_client.get(ENDPOINT, headers=headers_b)

    assert "## Only mine" not in response_b.json()["handover_template"]
    assert response_b.json()["is_default"] is True


@pytest.mark.asyncio
async def test_an_unauthenticated_caller_cannot_read_or_write(api_client):
    get_response = await api_client.get(ENDPOINT)
    put_response = await api_client.put(ENDPOINT, json={"handover_template": "x"})

    assert get_response.status_code in (401, 403), get_response.text
    assert put_response.status_code in (401, 403), put_response.text
