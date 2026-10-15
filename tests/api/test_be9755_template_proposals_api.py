# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate, Product, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.template_proposal_service import TemplateProposalService
from giljo_mcp.system_prompts.service import SystemPromptService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

BASE = "/api/v1/template-proposals"
CSRF = "be9755-csrf"
LIST_KEYS = {
    "id",
    "target_kind",
    "template_id",
    "template_name",
    "product_id",
    "product_name",
    "rung",
    "current_text",
    "proposed_text",
    "reason",
    "proposed_by",
    "created_at",
    "replaced_note",
}


async def _user_headers(db_manager, tenant_key: str, role: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    async with db_manager.get_session_async() as session:
        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        user = User(
            username=f"be9755_{suffix}",
            email=f"be9755_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
            tenant_key=tenant_key,
            role=role,
            org_id=org.id,
        )
        session.add(user)
        await session.commit()
        user_id, username = user.id, user.username
    token = JWTManager.create_access_token(user_id=user_id, username=username, role=role, tenant_key=tenant_key)
    return {"Cookie": f"access_token={token}; csrf_token={CSRF}", "X-CSRF-Token": CSRF, "_username": username}


async def _account(db_manager) -> dict:
    tenant_key = TenantManager.generate_tenant_key()
    member = await _user_headers(db_manager, tenant_key, "developer")
    admin = await _user_headers(db_manager, tenant_key, "admin")
    product_id, template_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            session.add(Product(id=product_id, name="Storefront", tenant_key=tenant_key, is_active=True))
            await session.flush()
            session.add(
                AgentTemplate(
                    id=template_id,
                    tenant_key=tenant_key,
                    product_id=product_id,
                    name=f"implementer-{uuid.uuid4().hex[:6]}",
                    role="implementer",
                    system_instructions="bootstrap",
                    user_instructions="Live text.",
                )
            )
            await session.commit()
    service = TemplateProposalService(db_manager)
    template_proposal = await service.propose(
        tenant_key=tenant_key,
        target_kind="agent_template",
        template_id_or_name=template_id,
        proposed_text="Proposed text.",
        reason="Clearer steps.",
        proposed_by="claude agent",
    )
    additions_proposal = await service.propose(
        tenant_key=tenant_key,
        target_kind="orchestrator_additions",
        rung="product",
        product_id=product_id,
        proposed_text="Always lint.",
        reason="Lint misses.",
    )
    return {
        "tenant_key": tenant_key,
        "member": member,
        "admin": admin,
        "product_id": product_id,
        "template_id": template_id,
        "template_proposal": template_proposal["proposal_id"],
        "additions_proposal": additions_proposal["proposal_id"],
    }


def _h(headers: dict) -> dict:
    return {k: v for k, v in headers.items() if not k.startswith("_")}


async def test_list_and_count_follow_each_editors_gate(api_client, db_manager):
    acct = await _account(db_manager)

    member_list = await api_client.get(BASE, headers=_h(acct["member"]))
    admin_list = await api_client.get(BASE, headers=_h(acct["admin"]))
    member_count = await api_client.get(f"{BASE}/count", headers=_h(acct["member"]))
    admin_count = await api_client.get(f"{BASE}/count", headers=_h(acct["admin"]))

    assert member_list.status_code == 200, member_list.text
    body = member_list.json()
    assert set(body) == {"count", "proposals"}
    assert body["count"] == 1
    [item] = body["proposals"]
    assert set(item) == LIST_KEYS
    assert item["target_kind"] == "agent_template"
    assert item["template_id"] == acct["template_id"]
    assert item["product_name"] == "Storefront"
    assert item["current_text"] == "Live text."
    assert item["proposed_text"] == "Proposed text."
    assert item["proposed_by"] == "claude agent"
    assert admin_list.json()["count"] == 2
    assert member_count.json() == {"count": 1}
    assert admin_count.json() == {"count": 2}


async def test_member_applies_a_template_proposal(api_client, db_manager):
    acct = await _account(db_manager)

    resp = await api_client.post(f"{BASE}/{acct['template_proposal']}/apply", headers=_h(acct["member"]))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "applied": True,
        "target_kind": "agent_template",
        "template_id": acct["template_id"],
        "applied_by": acct["member"]["_username"],
    }
    template = await api_client.get(f"/api/v1/templates/{acct['template_id']}", headers=_h(acct["member"]))
    assert template.json()["user_instructions"] == "Proposed text."
    assert (await api_client.get(f"{BASE}/count", headers=_h(acct["member"]))).json() == {"count": 0}


async def test_member_rejects_a_template_proposal(api_client, db_manager):
    acct = await _account(db_manager)

    resp = await api_client.post(f"{BASE}/{acct['template_proposal']}/reject", headers=_h(acct["member"]))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"rejected": True}
    template = await api_client.get(f"/api/v1/templates/{acct['template_id']}", headers=_h(acct["member"]))
    assert template.json()["user_instructions"] == "Live text."
    assert (await api_client.get(f"{BASE}/count", headers=_h(acct["admin"]))).json() == {"count": 1}


async def test_additions_proposal_needs_the_admin_role(api_client, db_manager):
    acct = await _account(db_manager)
    url = f"{BASE}/{acct['additions_proposal']}"

    assert (await api_client.post(f"{url}/apply", headers=_h(acct["member"]))).status_code == 403
    assert (await api_client.post(f"{url}/reject", headers=_h(acct["member"]))).status_code == 403

    resp = await api_client.post(f"{url}/apply", headers=_h(acct["admin"]))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "applied": True,
        "target_kind": "orchestrator_additions",
        "rung": "product",
        "applied_by": acct["admin"]["_username"],
    }
    stored = await SystemPromptService(db_manager).read_rung_additions(
        tenant_key=acct["tenant_key"], product_id=acct["product_id"]
    )
    assert stored == "Always lint."


async def test_another_accounts_proposal_is_not_found(api_client, db_manager):
    owner = await _account(db_manager)
    stranger = await _account(db_manager)

    for action in ("apply", "reject"):
        resp = await api_client.post(f"{BASE}/{owner['template_proposal']}/{action}", headers=_h(stranger["admin"]))
        assert resp.status_code == 404, resp.text
    listed = (await api_client.get(BASE, headers=_h(stranger["admin"]))).json()
    assert owner["template_proposal"] not in {p["id"] for p in listed["proposals"]}
    assert (await api_client.get(f"{BASE}/count", headers=_h(owner["admin"]))).json() == {"count": 2}


async def test_routes_require_sign_in(api_client):
    assert (await api_client.get(BASE)).status_code == 401
    assert (await api_client.get(f"{BASE}/count")).status_code == 401
