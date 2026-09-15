# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID


def _generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _err_text(body: dict) -> str:
    return " ".join(str(body.get(k, "")) for k in ("error", "error_description", "detail", "message"))


async def _seed_user_and_code(
    db_manager,
    *,
    challenge: str,
    code_value: str,
    client_id: str,
    redirect_uri: str = "http://localhost:3000/callback",
    resource: str | None = None,
) -> str:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.oauth import OAuthAuthorizationCode
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()

    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"Refresh Test Org {uuid4().hex[:6]}",
            slug=f"refresh-org-{uuid4().hex[:8]}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        user = User(
            id=str(uuid4()),
            username=f"refresh_user_{uuid4().hex[:8]}",
            email=f"refresh_{uuid4().hex[:8]}@example.com",
            role="developer",
            tenant_key=tenant_key,
            is_active=True,
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        auth_code = OAuthAuthorizationCode(
            code=code_value,
            client_id=client_id,
            user_id=user.id,
            tenant_key=tenant_key,
            redirect_uri=redirect_uri,
            code_challenge=challenge,
            code_challenge_method="S256",
            scope="mcp:read mcp:write",
            resource=resource,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            used=False,
        )
        session.add(auth_code)
        await session.commit()

    return tenant_key


def _install_confidential_resolver(
    *clients: tuple[str, str, list[str]],
):
    from giljo_mcp.services import oauth_service as svc

    prior = svc.get_client_resolver()
    table = {cid: (h, uris) for (cid, h, uris) in clients}

    def _resolver(cid: str, tenant_key: str):
        assert tenant_key
        if cid not in table:
            return None
        secret_hash, uris = table[cid]
        return svc.ResolvedClient(
            client_id=cid,
            client_name="DCR Confidential Test Client",
            redirect_uris=uris,
            client_secret_hash=secret_hash,
        )

    svc.set_client_resolver(_resolver)

    def _restore() -> None:
        svc.set_client_resolver(prior)

    return _restore


async def _exchange_code_for_token_pair(
    api_client,
    *,
    code_value: str,
    client_id: str,
    client_secret: str,
    code_verifier: str,
    redirect_uri: str = "http://localhost:3000/callback",
    resource: str | None = None,
) -> dict:
    payload = {
        "grant_type": "authorization_code",
        "code": code_value,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "client_secret": client_secret,
    }
    if resource is not None:
        payload["resource"] = resource
    response = await api_client.post("/api/oauth/token", data=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body, "Phase 2 confidential clients receive refresh_token"
    return body


def _bcrypt_hash(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


class TestRefreshTokenGrant:

    @pytest.mark.asyncio
    async def test_refresh_rotates_token(self, api_client, db_manager, monkeypatch):
        from giljo_mcp.services import oauth_refresh_service as _refresh_svc

        monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id = str(uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt_hash(plaintext_secret)
        redirect_uri = "http://localhost:3000/callback"

        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            client_id=client_id,
        )

        restore = _install_confidential_resolver((client_id, secret_hash, [redirect_uri]))
        try:
            initial = await _exchange_code_for_token_pair(
                api_client,
                code_value=code_value,
                client_id=client_id,
                client_secret=plaintext_secret,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
            )

            r1 = initial["refresh_token"]

            response = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r1,
                    "client_id": client_id,
                    "client_secret": plaintext_secret,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            r2 = body["refresh_token"]

            assert r2 != r1, "refresh_token must rotate"
            assert body["access_token"].count(".") == 2
            assert body["token_type"] == "bearer"

            replay = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r1,
                    "client_id": client_id,
                    "client_secret": plaintext_secret,
                },
            )
            assert replay.status_code == 401, replay.text
            replay_body = replay.json()
            replay_detail = _err_text(replay_body)
            assert "invalid_grant" in replay_detail.lower(), replay_body
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_refresh_token_reuse_revokes_family(self, api_client, db_manager, monkeypatch):
        from giljo_mcp.services import oauth_refresh_service as _refresh_svc

        monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id = str(uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt_hash(plaintext_secret)
        redirect_uri = "http://localhost:3000/callback"

        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            client_id=client_id,
        )

        restore = _install_confidential_resolver((client_id, secret_hash, [redirect_uri]))
        try:
            initial = await _exchange_code_for_token_pair(
                api_client,
                code_value=code_value,
                client_id=client_id,
                client_secret=plaintext_secret,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
            )
            r1 = initial["refresh_token"]

            rotation = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r1,
                    "client_id": client_id,
                    "client_secret": plaintext_secret,
                },
            )
            assert rotation.status_code == 200, rotation.text
            r2 = rotation.json()["refresh_token"]

            replay = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r1,
                    "client_id": client_id,
                    "client_secret": plaintext_secret,
                },
            )
            assert replay.status_code == 401, replay.text

            sibling = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r2,
                    "client_id": client_id,
                    "client_secret": plaintext_secret,
                },
            )
            assert sibling.status_code == 401, sibling.text
            sibling_body = sibling.json()
            sibling_detail = _err_text(sibling_body)
            assert "invalid_grant" in sibling_detail.lower(), sibling_body
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_refresh_cross_tenant_blocked(self, api_client, db_manager):
        from sqlalchemy import select as _select

        from giljo_mcp.database import tenant_isolation_bypass
        from giljo_mcp.models.oauth import OAuthRefreshToken

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id_a = str(uuid4())
        client_id_b = str(uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt_hash(plaintext_secret)
        redirect_uri = "http://localhost:3000/callback"

        tenant_a = await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            client_id=client_id_a,
        )

        restore = _install_confidential_resolver(
            (client_id_a, secret_hash, [redirect_uri]),
            (client_id_b, secret_hash, [redirect_uri]),
        )
        try:
            initial = await _exchange_code_for_token_pair(
                api_client,
                code_value=code_value,
                client_id=client_id_a,
                client_secret=plaintext_secret,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
            )
            r1 = initial["refresh_token"]

            response = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r1,
                    "client_id": client_id_b,
                    "client_secret": plaintext_secret,
                },
            )
            assert response.status_code == 401, response.text
            body = response.json()
            detail = _err_text(body)
            assert "invalid_grant" in detail.lower(), body

            async with db_manager.get_session_async() as session:
                with tenant_isolation_bypass(
                    session,
                    reason="test: cross-tenant refresh-row inspection to prove isolation",
                    models=(OAuthRefreshToken,),
                ):
                    rows = (
                        (
                            await session.execute(
                                _select(OAuthRefreshToken).where(OAuthRefreshToken.client_id == client_id_a)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    b_rows = (
                        (
                            await session.execute(
                                _select(OAuthRefreshToken).where(OAuthRefreshToken.client_id == client_id_b)
                            )
                        )
                        .scalars()
                        .all()
                    )
                assert rows, "tenant A's refresh row must still exist"
                assert all(row.tenant_key == tenant_a for row in rows), [r.tenant_key for r in rows]
                assert not b_rows, "no refresh row should be issued for client_id_b"
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_refresh_with_wrong_secret(self, api_client, db_manager):
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id = str(uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt_hash(plaintext_secret)
        redirect_uri = "http://localhost:3000/callback"

        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            client_id=client_id,
        )

        restore = _install_confidential_resolver((client_id, secret_hash, [redirect_uri]))
        try:
            initial = await _exchange_code_for_token_pair(
                api_client,
                code_value=code_value,
                client_id=client_id,
                client_secret=plaintext_secret,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
            )
            r1 = initial["refresh_token"]

            response = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r1,
                    "client_id": client_id,
                    "client_secret": "totally-wrong-secret",
                },
            )
            assert response.status_code == 401, response.text
            body = response.json()
            detail = _err_text(body)
            assert "invalid_client" in detail.lower(), body
        finally:
            restore()


class TestRefreshBlocksDeactivatedUser:

    @pytest.mark.asyncio
    async def test_refresh_blocks_deactivated_user(self, api_client, db_manager, monkeypatch):
        from sqlalchemy import update as _update

        from giljo_mcp.models.auth import User
        from giljo_mcp.services import oauth_refresh_service as _refresh_svc

        monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id = str(uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt_hash(plaintext_secret)
        redirect_uri = "http://localhost:3000/callback"

        tenant_key = await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            client_id=client_id,
        )

        restore = _install_confidential_resolver((client_id, secret_hash, [redirect_uri]))
        try:
            initial = await _exchange_code_for_token_pair(
                api_client,
                code_value=code_value,
                client_id=client_id,
                client_secret=plaintext_secret,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
            )
            r1 = initial["refresh_token"]

            ok = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r1,
                    "client_id": client_id,
                    "client_secret": plaintext_secret,
                },
            )
            assert ok.status_code == 200, ok.text
            r2 = ok.json()["refresh_token"]
            assert r2 != r1

            async with db_manager.get_session_async(tenant_key=tenant_key) as session:
                await session.execute(_update(User).where(User.tenant_key == tenant_key).values(is_active=False))
                await session.commit()

            blocked = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r2,
                    "client_id": client_id,
                    "client_secret": plaintext_secret,
                },
            )
            assert blocked.status_code == 401, blocked.text
            body = blocked.json()
            detail = _err_text(body)
            assert "invalid_grant" in detail.lower(), body
        finally:
            restore()


class TestRefreshAcceptsJsonAndBasicAuth:

    @pytest.mark.asyncio
    async def test_refresh_accepts_json_content_type(self, api_client, db_manager):
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id = str(uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt_hash(plaintext_secret)
        redirect_uri = "http://localhost:3000/callback"

        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            client_id=client_id,
        )

        restore = _install_confidential_resolver((client_id, secret_hash, [redirect_uri]))
        try:
            initial = await _exchange_code_for_token_pair(
                api_client,
                code_value=code_value,
                client_id=client_id,
                client_secret=plaintext_secret,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
            )
            r1 = initial["refresh_token"]

            response = await api_client.post(
                "/api/oauth/refresh",
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": r1,
                    "client_id": client_id,
                    "client_secret": plaintext_secret,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert "access_token" in body
            assert "refresh_token" in body
            assert body["refresh_token"] != r1
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_refresh_accepts_basic_auth_header(self, api_client, db_manager):
        import base64 as _b64

        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        client_id = str(uuid4())
        plaintext_secret = secrets.token_urlsafe(48)
        secret_hash = _bcrypt_hash(plaintext_secret)
        redirect_uri = "http://localhost:3000/callback"

        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            client_id=client_id,
        )

        basic = _b64.b64encode(f"{client_id}:{plaintext_secret}".encode("ascii")).decode("ascii")

        restore = _install_confidential_resolver((client_id, secret_hash, [redirect_uri]))
        try:
            initial = await _exchange_code_for_token_pair(
                api_client,
                code_value=code_value,
                client_id=client_id,
                client_secret=plaintext_secret,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
            )
            r1 = initial["refresh_token"]

            response = await api_client.post(
                "/api/oauth/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": r1,
                    "client_id": client_id,
                },
                headers={"Authorization": f"Basic {basic}"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert "access_token" in body
            assert body["refresh_token"] != r1
        finally:
            restore()


class TestPublicClientRefreshTokenGrant:

    async def _public_token_pair(
        self,
        api_client,
        db_manager,
        *,
        redirect_uri: str = "http://localhost:3000/callback",
    ) -> dict:
        verifier, challenge = _generate_pkce_pair()
        code_value = secrets.token_urlsafe(64)
        await _seed_user_and_code(
            db_manager,
            challenge=challenge,
            code_value=code_value,
            client_id=BUILTIN_CLIENT_ID,
            redirect_uri=redirect_uri,
        )
        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": BUILTIN_CLIENT_ID,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    @pytest.mark.asyncio
    async def test_public_client_token_issues_refresh_token(self, api_client, db_manager):
        body = await self._public_token_pair(api_client, db_manager)
        assert "access_token" in body
        assert isinstance(body.get("refresh_token"), str) and body["refresh_token"], body
        assert isinstance(body.get("refresh_expires_in"), int) and body["refresh_expires_in"] > 0, body

    @pytest.mark.asyncio
    async def test_public_client_refresh_rotates_and_old_token_rejected(self, api_client, db_manager, monkeypatch):
        from giljo_mcp.services import oauth_refresh_service as _refresh_svc

        monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)

        initial = await self._public_token_pair(api_client, db_manager)
        r1 = initial["refresh_token"]

        rotation = await api_client.post(
            "/api/oauth/refresh",
            data={
                "grant_type": "refresh_token",
                "refresh_token": r1,
                "client_id": BUILTIN_CLIENT_ID,
            },
        )
        assert rotation.status_code == 200, rotation.text
        body = rotation.json()
        r2 = body["refresh_token"]
        assert r2 != r1, "refresh_token must rotate"
        assert body["access_token"].count(".") == 2
        assert body["token_type"] == "bearer"

        replay = await api_client.post(
            "/api/oauth/refresh",
            data={
                "grant_type": "refresh_token",
                "refresh_token": r1,
                "client_id": BUILTIN_CLIENT_ID,
            },
        )
        assert replay.status_code == 401, replay.text
        replay_body = replay.json()
        replay_detail = _err_text(replay_body)
        assert "invalid_grant" in replay_detail.lower(), replay_body

    @pytest.mark.asyncio
    async def test_public_client_consumed_token_reuse_revokes_family(self, api_client, db_manager, monkeypatch):
        from giljo_mcp.services import oauth_refresh_service as _refresh_svc

        monkeypatch.setattr(_refresh_svc, "OAUTH_REFRESH_IDEMPOTENCY_WINDOW_SECONDS", 0)

        initial = await self._public_token_pair(api_client, db_manager)
        r1 = initial["refresh_token"]

        rotation = await api_client.post(
            "/api/oauth/refresh",
            data={"grant_type": "refresh_token", "refresh_token": r1, "client_id": BUILTIN_CLIENT_ID},
        )
        assert rotation.status_code == 200, rotation.text
        r2 = rotation.json()["refresh_token"]

        replay = await api_client.post(
            "/api/oauth/refresh",
            data={"grant_type": "refresh_token", "refresh_token": r1, "client_id": BUILTIN_CLIENT_ID},
        )
        assert replay.status_code == 401, replay.text

        sibling = await api_client.post(
            "/api/oauth/refresh",
            data={"grant_type": "refresh_token", "refresh_token": r2, "client_id": BUILTIN_CLIENT_ID},
        )
        assert sibling.status_code == 401, sibling.text
        sibling_body = sibling.json()
        sibling_detail = _err_text(sibling_body)
        assert "invalid_grant" in sibling_detail.lower(), sibling_body

    @pytest.mark.asyncio
    async def test_public_client_refresh_rejects_presented_secret(self, api_client, db_manager):
        initial = await self._public_token_pair(api_client, db_manager)
        r1 = initial["refresh_token"]

        response = await api_client.post(
            "/api/oauth/refresh",
            data={
                "grant_type": "refresh_token",
                "refresh_token": r1,
                "client_id": BUILTIN_CLIENT_ID,
                "client_secret": "public-clients-must-not-send-this",
            },
        )
        assert response.status_code == 401, response.text
        body = response.json()
        detail = _err_text(body)
        assert "invalid_client" in detail.lower(), body
