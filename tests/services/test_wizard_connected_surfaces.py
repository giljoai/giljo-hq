# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthLogin, OAuthRefreshToken
from giljo_mcp.services.credential_status_service import get_credential_status
from giljo_mcp.services.oauth_refresh_service import get_connected_surfaces


pytestmark = pytest.mark.asyncio

CLAUDE_ID = "https://claude.ai/oauth/mcp-oauth-client-metadata"
CLAUDE_CODE_ID = "https://claude.ai/oauth/claude-code-client-metadata"
CHATGPT_ID = "https://chatgpt.com/oauth/client.json"
CHATGPT_CONNECTOR_ID = "https://chatgpt.com/oauth/abc123/client.json"
CODEX_ID = "https://chatgpt.com/oauth/codex/client.json"


async def _user(session, tenant_key: str) -> User:
    uid = uuid4().hex[:8]
    user = User(
        id=str(uuid4()),
        username=f"wcs_{uid}",
        email=f"wcs_{uid}@example.com",
        password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def _approval(
    session,
    *,
    tenant_key: str,
    user_id: str,
    client_id: str,
    revoked: bool = False,
    expires_in: timedelta = timedelta(days=30),
    mcp_client_name: str | None = None,
) -> None:
    family = str(uuid4())
    session.add(
        OAuthRefreshToken(
            token_hash=uuid4().hex,
            family_id=family,
            client_id=client_id,
            tenant_key=tenant_key,
            user_id=user_id,
            aud="https://example.test/mcp",
            expires_at=datetime.now(UTC) + expires_in,
            revoked=revoked,
        )
    )
    await session.flush()
    session.add(
        OAuthLogin(
            family_id=family,
            tenant_key=tenant_key,
            user_id=user_id,
            client_id=client_id,
            client_name="App",
            last_mcp_client_name=mcp_client_name,
        )
    )
    await session.flush()


async def _surfaces(session, tenant_key: str) -> list[str]:
    with tenant_session_context(session, tenant_key):
        return (await get_credential_status(session, tenant_key)).connected_surfaces


async def test_live_claude_approval_lists_claude(db_session):
    tk = f"tk_{uuid4().hex[:12]}"
    user = await _user(db_session, tk)
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CLAUDE_ID)
    assert await _surfaces(db_session, tk) == ["claude"]


async def test_live_chatgpt_approvals_list_chatgpt_once(db_session):
    tk = f"tk_{uuid4().hex[:12]}"
    user = await _user(db_session, tk)
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CHATGPT_ID)
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CHATGPT_CONNECTOR_ID)
    assert await _surfaces(db_session, tk) == ["chatgpt"]


async def test_both_surfaces_sorted(db_session):
    tk = f"tk_{uuid4().hex[:12]}"
    user = await _user(db_session, tk)
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CHATGPT_ID)
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CLAUDE_ID)
    assert await _surfaces(db_session, tk) == ["chatgpt", "claude"]


async def test_revoked_approval_absent(db_session):
    tk = f"tk_{uuid4().hex[:12]}"
    user = await _user(db_session, tk)
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CLAUDE_ID, revoked=True)
    assert await _surfaces(db_session, tk) == []


async def test_expired_approval_absent(db_session):
    tk = f"tk_{uuid4().hex[:12]}"
    user = await _user(db_session, tk)
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CLAUDE_ID, expires_in=timedelta(days=-1))
    assert await _surfaces(db_session, tk) == []


async def test_no_approval_empty_list(db_session):
    assert await _surfaces(db_session, f"tk_{uuid4().hex[:12]}") == []


async def test_another_tenants_approval_never_shows(db_session):
    tenant_a = f"tk_a_{uuid4().hex[:12]}"
    tenant_b = f"tk_b_{uuid4().hex[:12]}"
    user_a = await _user(db_session, tenant_a)
    await _user(db_session, tenant_b)
    await _approval(db_session, tenant_key=tenant_a, user_id=user_a.id, client_id=CLAUDE_ID)
    assert await _surfaces(db_session, tenant_a) == ["claude"]
    assert await _surfaces(db_session, tenant_b) == []


async def test_claude_code_sign_in_does_not_light_hosted_claude(db_session):
    tk = f"tk_{uuid4().hex[:12]}"
    user = await _user(db_session, tk)
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CLAUDE_ID, mcp_client_name="claude-code")
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CLAUDE_CODE_ID)
    assert await _surfaces(db_session, tk) == []


async def test_hosted_claude_used_by_desktop_still_lists_claude(db_session):
    tk = f"tk_{uuid4().hex[:12]}"
    user = await _user(db_session, tk)
    await _approval(
        db_session, tenant_key=tk, user_id=user.id, client_id=CLAUDE_ID, mcp_client_name="Anthropic/ClaudeAI"
    )
    assert await _surfaces(db_session, tk) == ["claude"]


async def test_other_clients_never_listed(db_session):
    tk = f"tk_{uuid4().hex[:12]}"
    user = await _user(db_session, tk)
    for cid in (CODEX_ID, "giljo-mcp-default", "https://cursor.com/oauth/mcp-client.json"):
        await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=cid)
    assert await _surfaces(db_session, tk) == []


async def test_response_body_holds_names_only(db_session):
    from api.endpoints.connect import get_connect_credential_status

    tk = f"tk_{uuid4().hex[:12]}"
    user = await _user(db_session, tk)
    await _approval(db_session, tenant_key=tk, user_id=user.id, client_id=CLAUDE_ID)
    with tenant_session_context(db_session, tk):
        result = await get_connect_credential_status(current_user=user, db=db_session)
    body = json.dumps(result.model_dump())
    row = (await db_session.execute(OAuthRefreshToken.__table__.select())).first()
    assert result.connected_surfaces == ["claude"]
    assert row.token_hash not in body
    assert row.family_id not in body
    assert "claude.ai" not in body and "token" not in body.replace("has_valid_oauth", "")


async def test_explicit_tenant_filter_holds_without_the_platform_guard(db_session):
    from giljo_mcp.database import tenant_isolation_bypass

    tenant_a = f"tk_a_{uuid4().hex[:12]}"
    tenant_b = f"tk_b_{uuid4().hex[:12]}"
    user_a = await _user(db_session, tenant_a)
    await _approval(db_session, tenant_key=tenant_a, user_id=user_a.id, client_id=CLAUDE_ID)
    with tenant_isolation_bypass(
        db_session, reason="prove the query's own tenant filter", models=(OAuthRefreshToken, OAuthLogin)
    ):
        assert await get_connected_surfaces(db_session, tenant_b) == []
        assert await get_connected_surfaces(db_session, tenant_a) == ["claude"]
