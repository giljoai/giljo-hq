# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthAuthorizationCode
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID
from giljo_mcp.tenant import TenantManager


_REGISTERED_REDIRECT = "http://localhost:3000/callback"
_CRLF_REDIRECT = "http://evil.example\r\nINJECTED-TOKEN-LOG-LINE/callback"


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


async def _seed_user(db_manager) -> tuple[str, str]:
    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"SEC9227i Org {unique}", slug=f"sec9227i-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec9227i_user_{unique}",
                email=f"sec9227i_{unique}@example.com",
                role="developer",
                tenant_key=tk,
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()
    return user_id, tk


async def _seed_code(db_manager, *, user_id: str, tenant_key: str, challenge: str) -> str:
    code_value = secrets.token_urlsafe(64)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            OAuthAuthorizationCode(
                code=code_value,
                client_id=BUILTIN_CLIENT_ID,
                user_id=user_id,
                tenant_key=tenant_key,
                redirect_uri=_REGISTERED_REDIRECT,
                code_challenge=challenge,
                code_challenge_method="S256",
                scope="mcp:read mcp:write",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                used=False,
            )
        )
        await session.commit()
    return code_value


@pytest.mark.skipif(
    os.environ.get("GILJO_MODE") == "saas",
    reason="CE /token builtin-client path; SaaS resolver requires UUID client_ids",
)
@pytest.mark.asyncio
async def test_token_exc_log_sanitizes_crlf_redirect_uri(api_client, db_manager, monkeypatch, caplog):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    caplog.set_level(logging.WARNING, logger="api.endpoints.oauth")
    resp = await api_client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": BUILTIN_CLIENT_ID,
            "code_verifier": verifier,
            "redirect_uri": _CRLF_REDIRECT,
        },
    )

    assert resp.status_code == 400, resp.text
    records = [r for r in caplog.records if "OAuth token" in r.getMessage()]
    assert records, "expected a /token exception log record"
    joined = "\n".join(r.getMessage() for r in records)
    assert "INJECTED-TOKEN-LOG-LINE" in joined, "the redirect_uri value should still appear (sanitized)"
    assert "\r" not in joined, "raw carriage return (CRLF redirect_uri) reached the /token exc log"
    assert "\n" not in "".join(r.getMessage() for r in records), "raw newline reached the /token exc log"
