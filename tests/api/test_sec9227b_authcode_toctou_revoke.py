# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9227b — atomic auth-code consume (H1 TOCTOU) + revoke-on-reuse (M4).

H1 (TOCTOU): ``exchange_code_for_token`` used a check-then-set on
``auth_code.used`` (read the flag, later assign it) with NO atomicity, so two
concurrent /token exchanges of the SAME code could both pass the used-check and
both issue token pairs (double-spend). Fix: one atomic conditional UPDATE
(``used=false -> true``) with a rowcount guard is the whole check-and-set.

M4 (revoke on reuse, RFC 9700 §4.5.3): when a code is presented AGAIN after it
was already consumed, revoke every refresh family minted from it. The linkage is
``oauth_refresh_tokens.origin_code_hash`` (sha256 of the code), recorded at
issuance and looked up on the reuse path.

FLAG-1 discrimination (verified here): revocation fires ONLY on the sequential
reuse path (a code observed already-used at read time = a committed prior use).
The concurrent-loss path (rowcount!=1) does NOT revoke — a request that reaches
the atomic UPDATE has already passed PKCE, so it holds the verifier and is the
legitimate multi-egress twin; revoking there would self-DoS honest concurrent
double-submits, and the atomic UPDATE alone already prevents the double-issue.

Failing layer: the OAuth code-exchange service, driven through the real
``/api/oauth/token`` route (M4 boundary tests) and directly with a deterministic
concurrent-winner injected at the ``_verify_client_authentication`` async seam
(H1 concurrent-loss). Parallel-safe: unique tenant/user/code per test, committed
seed rows, monkeypatch-only patching, no shared mutable state, no ordering deps.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time as _time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from giljo_mcp.models.auth import User
from giljo_mcp.models.oauth import OAuthAuthorizationCode, OAuthRefreshToken
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services import oauth_token_idempotency as _idem_svc
from giljo_mcp.services.oauth_refresh_service import (
    hash_authorization_code,
    issue_refresh_token,
    new_family_id,
    revoke_families_for_code,
)
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService
from giljo_mcp.tenant import TenantManager


_REDIRECT = "http://localhost:3000/callback"


def _generate_pkce_pair() -> tuple[str, str]:
    """Return a valid (code_verifier, code_challenge) S256 pair."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


async def _seed_user(db_manager) -> tuple[str, str]:
    """Create org+user committed; return (user_id, tenant_key)."""
    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"SEC9227b Org {unique}", slug=f"sec9227b-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"sec9227b_user_{unique}",
                email=f"sec9227b_{unique}@example.com",
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
    """Insert a fresh, unused authorization code (committed); return the code value."""
    code_value = secrets.token_urlsafe(64)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            OAuthAuthorizationCode(
                code=code_value,
                client_id=BUILTIN_CLIENT_ID,
                user_id=user_id,
                tenant_key=tenant_key,
                redirect_uri=_REDIRECT,
                code_challenge=challenge,
                code_challenge_method="S256",
                scope="mcp:read mcp:write",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                used=False,
            )
        )
        await session.commit()
    return code_value


async def _live_families(db_manager, *, tenant_key: str, user_id: str) -> int:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        rows = (
            (
                await session.execute(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.user_id == user_id,
                        OAuthRefreshToken.tenant_key == tenant_key,
                        OAuthRefreshToken.revoked.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
    return len(rows)


async def _refresh_row_for_code(db_manager, *, tenant_key: str, code: str) -> OAuthRefreshToken | None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        return (
            (
                await session.execute(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.origin_code_hash == hash_authorization_code(code),
                        OAuthRefreshToken.tenant_key == tenant_key,
                    )
                )
            )
            .scalars()
            .first()
        )


async def _token_call(api_client, *, code: str, verifier: str):
    return await api_client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": BUILTIN_CLIENT_ID,
            "code_verifier": verifier,
            "redirect_uri": _REDIRECT,
        },
    )


# --------------------------------------------------------------------------- #
# H1 — atomic consume, concurrent-loss path (deterministic, no double-issue)   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_h1_concurrent_loser_fails_closed_and_keeps_winner_family(db_manager, monkeypatch):
    """A concurrent exchange that loses the atomic consume must fail closed AND
    must NOT revoke the winner's just-issued family (FLAG 1).

    Deterministic race: a concurrent WINNER (separate committed session) consumes
    the code + issues its family at the ``_verify_client_authentication`` seam,
    which runs AFTER our SELECT cached ``used=False`` (so the used-fast-path is
    skipped — this is the concurrent path, not the sequential one) but BEFORE our
    atomic UPDATE (which then matches 0 rows). Pre-fix (non-atomic read-then-set)
    this loser would ALSO issue a pair (double-spend) — the assertions below fail
    on that code and pass on the atomic-UPDATE fix.
    """
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    orig_verify = OAuthService._verify_client_authentication
    fired = {"done": False}

    async def _verify_then_win(*, client_id: str, tenant_key: str, client_secret: str | None):
        if not fired["done"]:
            fired["done"] = True
            async with db_manager.get_session_async(tenant_key=tk) as win:
                await win.execute(
                    update(OAuthAuthorizationCode)
                    .where(
                        OAuthAuthorizationCode.code == code,
                        OAuthAuthorizationCode.tenant_key == tk,
                        OAuthAuthorizationCode.used == False,  # noqa: E712
                    )
                    .values(used=True)
                )
                await issue_refresh_token(
                    win,
                    family_id=new_family_id(),
                    client_id=BUILTIN_CLIENT_ID,
                    tenant_key=tk,
                    user_id=user_id,
                    scope="mcp:read mcp:write",
                    aud="",
                    lifetime_seconds=3600,
                    origin_code_hash=hash_authorization_code(code),
                )
                await win.commit()
        return await orig_verify(client_id=client_id, tenant_key=tenant_key, client_secret=client_secret)

    monkeypatch.setattr(OAuthService, "_verify_client_authentication", staticmethod(_verify_then_win))

    async with db_manager.get_session_async(tenant_key=tk) as loser:
        svc = OAuthService(db_session=loser)
        with pytest.raises(ValueError, match="already been used"):
            await svc.exchange_code_for_token(
                code=code,
                client_id=BUILTIN_CLIENT_ID,
                code_verifier=verifier,
                redirect_uri=_REDIRECT,
            )

    assert fired["done"], "the concurrent-winner seam must have fired mid-exchange"
    # Exactly ONE live family (the winner's) — the loser issued none (no double-spend)
    # AND did not revoke the winner (no self-DoS on the concurrent path).
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1


# --------------------------------------------------------------------------- #
# M4 — sequential reuse revokes the family (boundary: /api/oauth/token -> 400) #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_m4_sequential_reuse_revokes_family(api_client, db_manager, monkeypatch):
    """Replaying a consumed code OUTSIDE the idempotency window revokes every
    family it minted and rejects the replay (RFC 9700 §4.5.3)."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    # Collapse the window so the replay falls through to the reuse (used) path.
    monkeypatch.setattr(_idem_svc, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 0)

    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    first = await _token_call(api_client, code=code, verifier=verifier)
    assert first.status_code == 200, first.text
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1

    _time.sleep(0.05)  # past the collapsed window

    replay = await _token_call(api_client, code=code, verifier=verifier)
    assert replay.status_code == 400, replay.text
    assert replay.json().get("error") == "invalid_request", replay.text
    # The family minted by the first exchange is now revoked (no live rows).
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 0


# --------------------------------------------------------------------------- #
# M4 cache-ordering: same-verifier retry in window is idempotent, NOT reuse     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_m4_same_verifier_retry_in_window_is_idempotent_no_revoke(api_client, db_manager, monkeypatch):
    """A same-verifier retry INSIDE the window hits the (verifier-keyed) idempotency
    cache and returns the SAME pair — it must NOT be treated as reuse, so the family
    stays live. This is the benign concurrent-retry the window exists to serve."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_idem_svc, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 30)

    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    first = await _token_call(api_client, code=code, verifier=verifier)
    assert first.status_code == 200, first.text
    again = await _token_call(api_client, code=code, verifier=verifier)
    assert again.status_code == 200, again.text
    # Idempotent: identical pair returned, and the family is untouched (not revoked).
    assert again.json()["refresh_token"] == first.json()["refresh_token"]
    assert again.json()["access_token"] == first.json()["access_token"]
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1


@pytest.mark.asyncio
async def test_m4_varied_verifier_replay_misses_cache_and_revokes(api_client, db_manager, monkeypatch):
    """A replay with a DIFFERENT verifier computes a different idempotency signature,
    MISSES the verifier-keyed cache (step-a H2 fix), reaches the used-fast-path, and
    triggers reuse revocation — even inside the window. This is the exact cache-
    ordering hazard class that hid step a's bypass, asserted directly."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setattr(_idem_svc, "OAUTH_TOKEN_IDEMPOTENCY_WINDOW_SECONDS", 30)

    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    first = await _token_call(api_client, code=code, verifier=verifier)
    assert first.status_code == 200, first.text
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1

    # Same code, DIFFERENT verifier -> different signature -> cache miss -> reuse path.
    replay = await _token_call(api_client, code=code, verifier=secrets.token_urlsafe(64))
    assert replay.status_code == 400, replay.text
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 0


# --------------------------------------------------------------------------- #
# M4 linkage + happy path: issuance records origin_code_hash                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_origin_code_hash_recorded_on_issuance(api_client, db_manager, monkeypatch):
    """A normal exchange issues a pair AND records origin_code_hash = sha256(code)
    on the refresh row, so a later reuse of that code can find + revoke the family."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, tk = await _seed_user(db_manager)
    verifier, challenge = _generate_pkce_pair()
    code = await _seed_code(db_manager, user_id=user_id, tenant_key=tk, challenge=challenge)

    resp = await _token_call(api_client, code=code, verifier=verifier)
    assert resp.status_code == 200, resp.text
    assert resp.json().get("refresh_token")

    row = await _refresh_row_for_code(db_manager, tenant_key=tk, code=code)
    assert row is not None, "issued refresh row must be linked to its origin code"
    assert row.origin_code_hash == hash_authorization_code(code)
    assert row.user_id == user_id


# --------------------------------------------------------------------------- #
# revoke_families_for_code helper — revokes matching families, commits, scoped  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_revoke_families_for_code_revokes_all_matching_and_commits(db_manager, monkeypatch):
    """The extracted helper revokes EVERY family linked to the code (across
    families), leaves unrelated families alone, and commits durably."""
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    user_id, tk = await _seed_user(db_manager)
    code = secrets.token_urlsafe(64)
    other_code = secrets.token_urlsafe(64)

    async with db_manager.get_session_async(tenant_key=tk) as session:
        for _ in range(2):  # two distinct families from the SAME code
            await issue_refresh_token(
                session,
                family_id=new_family_id(),
                client_id=BUILTIN_CLIENT_ID,
                tenant_key=tk,
                user_id=user_id,
                scope="mcp:read mcp:write",
                aud="",
                lifetime_seconds=3600,
                origin_code_hash=hash_authorization_code(code),
            )
        # an unrelated family from a DIFFERENT code — must survive
        await issue_refresh_token(
            session,
            family_id=new_family_id(),
            client_id=BUILTIN_CLIENT_ID,
            tenant_key=tk,
            user_id=user_id,
            scope="mcp:read mcp:write",
            aud="",
            lifetime_seconds=3600,
            origin_code_hash=hash_authorization_code(other_code),
        )
        await session.commit()

    async with db_manager.get_session_async(tenant_key=tk) as session:
        revoked = await revoke_families_for_code(session, code=code, tenant_key=tk)
    assert revoked == 2, "both families minted from the reused code must be revoked"

    # Durable + scoped: exactly one live family remains (the unrelated other_code one),
    # read on a FRESH session (proves the helper's explicit commit persisted).
    assert await _live_families(db_manager, tenant_key=tk, user_id=user_id) == 1
    survivor = await _refresh_row_for_code(db_manager, tenant_key=tk, code=other_code)
    assert survivor is not None and survivor.revoked is False
