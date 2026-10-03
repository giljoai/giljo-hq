# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.identity import validate_agent_display_name


LONG_ID = "x" * 65
CSRF_TOKEN = "test-api9703b-csrf"

OVER_LENGTH_ID_ROUTES = [
    ("GET", f"/api/v1/projects/{LONG_ID}", None),
    ("POST", f"/api/v1/projects/{LONG_ID}/activate", None),
    ("GET", f"/api/v1/projects/{LONG_ID}/summary", None),
    ("POST", f"/api/v1/projects/{LONG_ID}/continue-working", None),
    ("GET", f"/api/v1/products/{LONG_ID}", None),
    ("POST", f"/api/v1/products/{LONG_ID}/activate", None),
    ("GET", f"/api/v1/products/{LONG_ID}/vision", None),
    ("GET", f"/api/vision-documents/{LONG_ID}", None),
    ("GET", f"/api/v1/threads/{LONG_ID}", None),
    ("GET", f"/api/v1/tasks/{LONG_ID}/", None),
    ("DELETE", f"/api/v1/roadmap/items/{LONG_ID}", None),
    ("GET", f"/api/agent-jobs/{LONG_ID}", None),
    ("GET", f"/api/agent-jobs/{LONG_ID}/messages", None),
    ("PATCH", f"/api/jobs/{LONG_ID}/mission", {"mission": "m"}),
    ("GET", f"/api/v1/prompts/staging/{LONG_ID}", None),
    ("GET", f"/api/v1/templates/{LONG_ID}", None),
    ("GET", f"/api/v1/templates/{LONG_ID}/history", None),
    ("PATCH", f"/api/notifications/{LONG_ID}/read", None),
    ("GET", f"/api/v1/tasks/?product_id={LONG_ID}", None),
    ("GET", f"/api/v1/projects/?product_id={LONG_ID}", None),
    ("GET", f"/api/v1/threads?project_id={LONG_ID}", None),
    ("GET", f"/api/v1/projects/next-series?type_id={LONG_ID}", None),
    ("GET", f"/api/v1/stats/dashboard?product_id={LONG_ID}", None),
]


async def _admin_headers(db_manager, *, password: bytes | None = b"test_password") -> dict[str, str]:
    async with db_manager.get_session_async() as session:
        suffix = uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        org = Organization(name=f"BT Org {suffix}", slug=f"bt-org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        user = User(
            username=f"bt_user_{suffix}",
            email=f"bt_{suffix}@example.com",
            password_hash=bcrypt.hashpw(password, bcrypt.gensalt()).decode("utf-8") if password else None,
            tenant_key=tenant_key,
            role="admin",
            org_id=org.id,
        )
        session.add(user)
        await session.commit()
    token = JWTManager.create_access_token(user_id=user.id, username=user.username, role="admin", tenant_key=tenant_key)
    return {"Cookie": f"access_token={token}; csrf_token={CSRF_TOKEN}", "X-CSRF-Token": CSRF_TOKEN}


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "url", "body"), OVER_LENGTH_ID_ROUTES)
async def test_over_length_id_is_422(api_client, auth_headers, method, url, body):
    response = await api_client.request(method, url, headers=auth_headers, json=body)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_101_char_agent_display_name_is_422(api_client, auth_headers):
    response = await api_client.post(
        "/api/agent-jobs/spawn",
        headers=auth_headers,
        json={"agent_display_name": "a" * 101, "mission": "m", "project_id": str(uuid4())},
    )
    assert response.status_code == 422, response.text


def test_agent_display_name_validator_matches_the_column_width():
    assert validate_agent_display_name("a" * 100) == "a" * 100
    with pytest.raises(ValidationError):
        validate_agent_display_name("a" * 101)


@pytest.mark.asyncio
async def test_unknown_vision_document_type_is_422(api_client, auth_headers):
    response = await api_client.post(
        "/api/vision-documents/",
        headers=auth_headers,
        data={"product_id": str(uuid4()), "document_name": "d", "document_type": "foo", "content": "c"},
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_creating_a_project_as_completed_is_422(api_client, auth_headers):
    response = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={"name": "p", "description": "d", "product_id": str(uuid4()), "status": "completed"},
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_two_letter_subseries_on_project_update_is_422(api_client, auth_headers):
    response = await api_client.patch(f"/api/v1/projects/{uuid4()}", headers=auth_headers, json={"subseries": "ab"})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_roadmap_reorder_above_the_item_cap_is_422(api_client, auth_headers):
    items = [{"id": str(i), "sort_order": 0} for i in range(10_001)]
    response = await api_client.patch("/api/v1/roadmap/reorder", headers=auth_headers, json={"items": items})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_non_string_handover_template_on_general_settings_is_422(api_client, db_manager):
    headers = await _admin_headers(db_manager)
    response = await api_client.put(
        "/api/v1/settings/general", headers=headers, json={"settings": {"handover_template": 5}}
    )
    assert response.status_code == 422, response.text
    read_back = await api_client.get("/api/v1/settings/handover-template", headers=headers)
    assert read_back.status_code == 200, read_back.text


@pytest.mark.asyncio
async def test_oversized_api_key_permissions_are_422(api_client, auth_headers):
    response = await api_client.post(
        "/api/auth/api-keys", headers=auth_headers, json={"name": "key", "permissions": ["read"] * 51}
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_non_string_oauth_code_is_invalid_request(api_client):
    response = await api_client.post(
        "/api/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": 123,
            "client_id": "giljo-mcp-default",
            "redirect_uri": "http://localhost:3000/callback",
            "code_verifier": "v" * 43,
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_over_length_current_password_on_first_login_is_a_clean_400(api_client, auth_headers):
    response = await api_client.post(
        "/api/auth/complete-first-login",
        headers=auth_headers,
        json={
            "current_password": "p" * 100,
            "new_password": "N3w-Passw0rd!",
            "confirm_password": "N3w-Passw0rd!",
            "recovery_pin": "1234",
            "confirm_pin": "1234",
        },
    )
    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_first_login_for_a_user_with_no_stored_password_is_the_wrong_password_400(api_client, db_manager):
    headers = await _admin_headers(db_manager, password=None)
    response = await api_client.post(
        "/api/auth/complete-first-login",
        headers=headers,
        json={
            "current_password": "anything",
            "new_password": "N3w-Passw0rd!",
            "confirm_password": "N3w-Passw0rd!",
            "recovery_pin": "1234",
            "confirm_pin": "1234",
        },
    )
    assert response.status_code == 400, response.text
    assert "Current password is incorrect" in response.text
