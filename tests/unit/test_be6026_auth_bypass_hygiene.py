# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.api_key_utils import get_key_prefix
from giljo_mcp.models.auth import APIKey, User
from giljo_mcp.tenant import TenantManager


def _stored_key_prefix(plaintext: str) -> str:
    return get_key_prefix(plaintext, length=12)


def _user(tenant_key: str, username: str) -> User:
    return User(
        id=str(uuid4()),
        tenant_key=tenant_key,
        username=username,
        email=f"{username}_{uuid4().hex[:6]}@example.com",
        password_hash="not-used",
        role="developer",
        is_active=True,
    )


def _api_key_row(tenant_key: str, user_id: str, plaintext: str, *, name: str) -> APIKey:
    key_prefix = _stored_key_prefix(plaintext)
    return APIKey(
        id=str(uuid4()),
        tenant_key=tenant_key,
        user_id=user_id,
        name=name,
        key_hash=bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        key_prefix=key_prefix,
        permissions=["*"],
        is_active=True,
    )




class TestValidateApiKeyNarrowsByPrefix:
    @pytest.mark.asyncio
    async def test_only_prefix_matching_key_is_bcrypt_checked(self, db_session, monkeypatch):
        from api import auth_utils

        tenant = TenantManager.generate_tenant_key()
        user = _user(tenant, f"apikey_owner_{uuid4().hex[:6]}")
        db_session.add(user)
        await db_session.flush()

        real_plaintext = "gk_realkey_" + uuid4().hex
        real_key = _api_key_row(tenant, user.id, real_plaintext, name="real")

        decoys = [
            _api_key_row(tenant, user.id, "gk_decoyAAA_" + uuid4().hex, name="decoy-a"),
            _api_key_row(tenant, user.id, "gk_decoyBBB_" + uuid4().hex, name="decoy-b"),
        ]
        db_session.add_all([real_key, *decoys])
        await db_session.commit()

        checked_hashes: list[str] = []
        real_checkpw = bcrypt.checkpw

        def _spy_checkpw(password: bytes, hashed: bytes) -> bool:
            checked_hashes.append(hashed.decode("utf-8"))
            return real_checkpw(password, hashed)

        monkeypatch.setattr("bcrypt.checkpw", _spy_checkpw)

        result = await auth_utils.validate_api_key(real_plaintext, db=db_session)

        assert result is not None
        assert result["tenant_key"] == tenant
        assert real_key.key_hash in checked_hashes
        for decoy in decoys:
            assert decoy.key_hash not in checked_hashes
        assert len(checked_hashes) == 1

    @pytest.mark.asyncio
    async def test_wrong_prefix_presentation_returns_none_without_scanning(self, db_session, monkeypatch):
        from api import auth_utils

        tenant = TenantManager.generate_tenant_key()
        user = _user(tenant, f"apikey_owner_{uuid4().hex[:6]}")
        db_session.add(user)
        await db_session.flush()

        stored_plaintext = "gk_storedkey_" + uuid4().hex
        db_session.add(_api_key_row(tenant, user.id, stored_plaintext, name="stored"))
        await db_session.commit()

        check_count = {"n": 0}
        real_checkpw = bcrypt.checkpw

        def _spy_checkpw(password: bytes, hashed: bytes) -> bool:
            check_count["n"] += 1
            return real_checkpw(password, hashed)

        monkeypatch.setattr("bcrypt.checkpw", _spy_checkpw)

        result = await auth_utils.validate_api_key("gk_nomatchXX_" + uuid4().hex, db=db_session)

        assert result is None
        assert check_count["n"] == 0




class TestBuildApiKeyResultResolvesByUserId:
    @pytest.mark.asyncio
    async def test_label_colliding_with_other_username_does_not_resolve_wrong_user(self, db_session, db_manager):
        from contextlib import asynccontextmanager

        from giljo_mcp.auth_manager import AuthManager

        tenant = TenantManager.generate_tenant_key()
        owner = _user(tenant, f"true_owner_{uuid4().hex[:6]}")
        label = f"shared_label_{uuid4().hex[:6]}"
        impostor = _user(tenant, label)
        db_session.add_all([owner, impostor])
        await db_session.commit()

        @asynccontextmanager
        async def _session_ctx():
            yield db_session

        db_manager.get_session_async = _session_ctx

        mgr = AuthManager()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_manager=db_manager)))

        key_info = {
            "name": label,
            "user_id": owner.id,
            "tenant_key": tenant,
            "permissions": ["*"],
        }

        result = await mgr._build_api_key_result(key_info, request)

        assert result["authenticated"] is True
        assert result["tenant_key"] == tenant
        assert "user_obj" in result
        assert result["user_obj"].id == owner.id
        assert result["user_obj"].username == owner.username
        assert result["user"] == owner.username
        assert result["user_id"] == owner.username
        assert result["user"] != label
        assert result["user_id"] != label

    @pytest.mark.asyncio
    async def test_keyinfo_without_user_id_skips_enrichment(self, db_session, db_manager):
        from contextlib import asynccontextmanager

        from giljo_mcp.auth_manager import AuthManager

        tenant = TenantManager.generate_tenant_key()

        called = {"session": False}

        @asynccontextmanager
        async def _session_ctx():
            called["session"] = True
            yield db_session

        db_manager.get_session_async = _session_ctx

        mgr = AuthManager()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_manager=db_manager)))

        key_info = {
            "name": "Installer Generated",
            "tenant_key": tenant,
            "permissions": ["*"],
        }

        result = await mgr._build_api_key_result(key_info, request)

        assert result["authenticated"] is True
        assert result["tenant_key"] == tenant
        assert "user_obj" not in result
        assert called["session"] is False
        assert result["user"] == "Installer Generated"
        assert result["user_id"] == "Installer Generated"




class TestKeyPrefixConventionAgreement:

    @pytest.mark.parametrize(
        "plaintext",
        [
            "",
            "gk_a",
            "12345678901",
            "123456789012",
            "1234567890123",
            "gk_realisticlongtoken_" + "a" * 30,
        ],
    )
    def test_stored_and_lookup_prefix_match(self, plaintext):
        stored = _stored_key_prefix(plaintext)
        lookup = get_key_prefix(plaintext)
        assert lookup == stored

    def test_exact_boundary_has_no_spurious_ellipsis(self):
        plaintext = "123456789012"
        assert len(plaintext) == 12
        assert _stored_key_prefix(plaintext) == "123456789012"
        assert get_key_prefix(plaintext) == "123456789012"

    @pytest.mark.asyncio
    async def test_validate_api_key_finds_exact_boundary_key(self, db_session):
        from api import auth_utils

        tenant = TenantManager.generate_tenant_key()
        user = _user(tenant, f"apikey_owner_{uuid4().hex[:6]}")
        db_session.add(user)
        await db_session.flush()

        boundary_plaintext = "abcdefghijkl"
        assert len(boundary_plaintext) == 12
        db_session.add(_api_key_row(tenant, user.id, boundary_plaintext, name="boundary"))
        await db_session.commit()

        result = await auth_utils.validate_api_key(boundary_plaintext, db=db_session)

        assert result is not None
        assert result["tenant_key"] == tenant
