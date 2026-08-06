# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9227i (L5 audit follow-up) — the /token exception-log sinks must sanitize.

The independent audit caught a real CWE-117 that the first L5 sweep missed: the
/token handler NEVER passes ``redirect_uri`` (or ``client_id``) through
``_enforce_oauth_field_caps``, so an authenticated user with a valid code can POST
a CRLF-injected ``redirect_uri`` that mismatches the code's registered value. The
service raises ``redirect_uri mismatch: ... got '<CRLF>'`` and the catch-all
``logger.warning("OAuth token exchange failed: %s", exc)`` logs the RAW exception
— injecting a forged line into the log.

The lesson the audit named: a DIRECT ``_enforce_oauth_field_caps(redirect_uri=...)``
unit test proves nothing about the WIRED call site (which never passes
redirect_uri to it). So this repro drives the real ``POST /api/oauth/token`` route
and observes the log record. The fix sanitizes ``str(exc)`` at every oauth
exception-log sink.

Parallel-safe: unique tenant/user/code per test, committed seed rows,
monkeypatch-only, no shared mutable state.
"""

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
# A different redirect_uri than the one bound to the code, carrying a CRLF so a
# raw log write would forge a new line. Built with explicit escapes (ASCII source).
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


# The builtin client is a CE concept; the SaaS OAuth resolver resolves clients by
# UUID (DCR-issued), so BUILTIN_CLIENT_ID cannot resolve there — the same reason
# the sec9227b /token tests only run in CE. The exc-sink fix in oauth.py is itself
# edition-agnostic; this route repro is CE-only.
@pytest.mark.skipif(
    os.environ.get("GILJO_MODE") == "saas",
    reason="CE /token builtin-client path; SaaS resolver requires UUID client_ids",
)
@pytest.mark.asyncio
async def test_token_exc_log_sanitizes_crlf_redirect_uri(api_client, db_manager, monkeypatch, caplog):
    """FAIL-FIRST at the WIRED /token route: a valid code + a CRLF redirect_uri
    that mismatches the bound value -> the catch-all exc log. Pre-fix the raw
    CRLF reaches the log line; post-fix sanitize(str(exc)) at the sink strips it.
    """
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
    # The forged marker is logged (the value IS observed) but WITHOUT a raw line break.
    assert "INJECTED-TOKEN-LOG-LINE" in joined, "the redirect_uri value should still appear (sanitized)"
    assert "\r" not in joined, "raw carriage return (CRLF redirect_uri) reached the /token exc log"
    assert "\n" not in "".join(r.getMessage() for r in records), "raw newline reached the /token exc log"
