# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.system_prompts.service import ADDITIONS_HEADING, SystemPromptService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

ENDPOINT = "/api/v1/system/orchestrator-prompt"
RESET_ENDPOINT = f"{ENDPOINT}/reset"
CSRF_TOKEN = "test-be9754a-csrf"
ADDITIONS = "## House notice\n\nThis deployment builds itself."


@pytest.fixture
def prompt_service(db_manager, monkeypatch):
    from api.app_state import state

    service = SystemPromptService(db_manager)
    monkeypatch.setattr(state, "system_prompt_service", service)
    return service


async def _admin_headers(db_manager) -> dict[str, str]:
    async with db_manager.get_session_async() as session:
        suffix = uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        org = Organization(name=f"OP Org {suffix}", slug=f"op-org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        user = User(
            username=f"op_user_{suffix}",
            email=f"op_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tenant_key,
            role="admin",
            org_id=org.id,
        )
        session.add(user)
        await session.commit()

    token = JWTManager.create_access_token(
        user_id=user.id, username=user.username, role="admin", tenant_key=user.tenant_key
    )
    return {"Cookie": f"access_token={token}; csrf_token={CSRF_TOKEN}", "X-CSRF-Token": CSRF_TOKEN}


async def test_get_with_nothing_saved_reports_no_mode(api_client, db_manager, prompt_service):
    headers = await _admin_headers(db_manager)

    body = (await api_client.get(ENDPOINT, headers=headers, params={"product_id": str(uuid.uuid4())})).json()

    assert body["mode"] is None
    assert body["additions"] is None
    assert body["is_override"] is False
    assert body["content"] == body["default_content"]


async def test_put_additions_then_get_returns_the_layered_shape(api_client, db_manager, prompt_service):
    headers = await _admin_headers(db_manager)
    product_id = str(uuid.uuid4())

    put = await api_client.put(ENDPOINT, headers=headers, json={"additions": ADDITIONS, "product_id": product_id})
    get = await api_client.get(ENDPOINT, headers=headers, params={"product_id": product_id})

    for response in (put, get):
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mode"] == "additions"
        assert body["additions"] == ADDITIONS
        assert body["is_override"] is True
        assert body["scope"] == "product"
        assert body["content"] == f"{body['default_content']}\n\n{ADDITIONS_HEADING}\n\n{ADDITIONS}"


async def test_additions_for_one_product_do_not_reach_another(api_client, db_manager, prompt_service):
    headers = await _admin_headers(db_manager)
    product_id, other_product = str(uuid.uuid4()), str(uuid.uuid4())

    await api_client.put(ENDPOINT, headers=headers, json={"additions": ADDITIONS, "product_id": product_id})
    other = (await api_client.get(ENDPOINT, headers=headers, params={"product_id": other_product})).json()
    no_product = (await api_client.get(ENDPOINT, headers=headers)).json()

    for body in (other, no_product):
        assert body["mode"] is None
        assert body["scope"] == "default"
        assert body["content"] == body["default_content"]


async def test_legacy_content_put_still_saves_a_replacement(api_client, db_manager, prompt_service):
    headers = await _admin_headers(db_manager)

    body = (
        await api_client.put(
            ENDPOINT, headers=headers, json={"content": "Whole replacement.", "product_id": str(uuid.uuid4())}
        )
    ).json()

    assert body["mode"] == "replace"
    assert body["additions"] is None
    assert body["content"] == "Whole replacement."


@pytest.mark.parametrize("body", [{"additions": ADDITIONS}, {"content": "Whole replacement."}])
@pytest.mark.parametrize("product_id", [None, "", "   "])
async def test_put_without_a_product_is_a_422_and_saves_nothing(
    api_client, db_manager, prompt_service, body, product_id
):
    headers = await _admin_headers(db_manager)
    payload = {**body, "product_id": product_id}

    response = await api_client.put(ENDPOINT, headers=headers, json=payload)

    assert response.status_code == 422, response.text
    assert "product_id is required" in response.text
    read_back = (await api_client.get(ENDPOINT, headers=headers)).json()
    assert read_back["is_override"] is False


@pytest.mark.parametrize("product_id", [None, "", "   "])
async def test_reset_without_a_product_is_a_422_and_clears_nothing(api_client, db_manager, prompt_service, product_id):
    headers = await _admin_headers(db_manager)
    kept = str(uuid.uuid4())
    await api_client.put(ENDPOINT, headers=headers, json={"additions": ADDITIONS, "product_id": kept})
    params = {} if product_id is None else {"product_id": product_id}

    response = await api_client.post(RESET_ENDPOINT, headers=headers, params=params)

    assert response.status_code == 422, response.text
    still = (await api_client.get(ENDPOINT, headers=headers, params={"product_id": kept})).json()
    assert still["additions"] == ADDITIONS


@pytest.mark.parametrize("payload", [{}, {"content": "a", "additions": "b"}, {"product_id": None}])
async def test_put_needs_exactly_one_of_additions_or_content(api_client, db_manager, prompt_service, payload):
    headers = await _admin_headers(db_manager)

    response = await api_client.put(ENDPOINT, headers=headers, json=payload)

    assert response.status_code == 422, response.text


async def test_blank_additions_are_a_400(api_client, db_manager, prompt_service):
    headers = await _admin_headers(db_manager)

    response = await api_client.put(
        ENDPOINT, headers=headers, json={"additions": "   ", "product_id": str(uuid.uuid4())}
    )

    assert response.status_code == 400, response.text


async def test_reset_clears_additions(api_client, db_manager, prompt_service):
    headers = await _admin_headers(db_manager)
    product_id = str(uuid.uuid4())
    await api_client.put(ENDPOINT, headers=headers, json={"additions": ADDITIONS, "product_id": product_id})

    reset = await api_client.post(RESET_ENDPOINT, headers=headers, params={"product_id": product_id})

    assert reset.status_code == 200, reset.text
    body = reset.json()
    assert body["mode"] is None
    assert body["additions"] is None
    assert body["is_override"] is False
    assert body["content"] == body["default_content"]


async def test_additions_are_invisible_to_another_account(api_client, db_manager, prompt_service):
    mine, theirs = await _admin_headers(db_manager), await _admin_headers(db_manager)
    product_id = str(uuid.uuid4())
    await api_client.put(ENDPOINT, headers=theirs, json={"additions": ADDITIONS, "product_id": product_id})

    body = (await api_client.get(ENDPOINT, headers=mine, params={"product_id": product_id})).json()

    assert body["mode"] is None
    assert ADDITIONS not in body["content"]
