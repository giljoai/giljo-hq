# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager


pytestmark = pytest.mark.asyncio

_URL = "/api/v1/users/me/settings/notification-preferences"
_CSRF = "fe9553-csrf-token"

_RULED_DEFAULTS: dict[str, Any] = {
    "banner_lifecycle_enabled": True,
    "banner_advisories_in_fold": True,
    "popout_scope": "all",
}

_LEGACY_KEYS = ("context_tuning_reminder", "tuning_reminder_threshold")


async def _seed_user(db_manager) -> tuple[str, str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"fe9553_user_{unique}"

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"FE9553 Org {unique}",
            slug=f"fe9553-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"fe9553_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"unused-in-this-suite", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()

    return user_id, username, tk


async def _set_raw_prefs(db_manager, *, tenant_key: str, user_id: str, prefs: dict | None) -> None:
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        user = await session.get(User, user_id)
        user.notification_preferences = prefs
        await session.commit()


async def _read_raw_prefs(db_manager, *, tenant_key: str, user_id: str) -> dict | None:
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        user = await session.get(User, user_id)
        return dict(user.notification_preferences) if user.notification_preferences else None


def _auth(token: str) -> dict:
    return {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


def _mint(user_id: str, username: str, tenant_key: str) -> str:
    return JWTManager.create_access_token(
        user_id=user_id,
        username=username,
        role="developer",
        tenant_key=tenant_key,
        revocation_epoch=0,
    )


async def _headers(db_manager) -> tuple[dict, str, str]:
    user_id, username, tk = await _seed_user(db_manager)
    return _auth(_mint(user_id, username, tk)), user_id, tk


async def test_defaults_are_the_ruled_defaults_for_a_user_who_never_set_them(api_client, db_manager):
    headers, _user_id, _tk = await _headers(db_manager)

    resp = await api_client.get(_URL, headers=headers)

    assert resp.status_code == 200, resp.text
    prefs = resp.json()["notification_preferences"]
    for key, expected in _RULED_DEFAULTS.items():
        assert prefs[key] == expected, f"{key} should default to {expected!r}, got {prefs.get(key)!r}"


async def test_a_legacy_row_reads_back_complete_without_a_migration(api_client, db_manager):
    headers, user_id, tk = await _headers(db_manager)
    await _set_raw_prefs(
        db_manager,
        tenant_key=tk,
        user_id=user_id,
        prefs={"context_tuning_reminder": False, "tuning_reminder_threshold": 42},
    )

    resp = await api_client.get(_URL, headers=headers)

    assert resp.status_code == 200, resp.text
    prefs = resp.json()["notification_preferences"]
    for key, expected in _RULED_DEFAULTS.items():
        assert prefs[key] == expected
    assert prefs["context_tuning_reminder"] is False
    assert prefs["tuning_reminder_threshold"] == 42

    stored = await _read_raw_prefs(db_manager, tenant_key=tk, user_id=user_id)
    assert set(stored) == set(_LEGACY_KEYS), (
        "a read must not migrate the row -- the new keys should appear only when "
        f"the user actually changes one, but the stored row is now {sorted(stored)}"
    )


async def test_a_null_row_reads_back_complete(api_client, db_manager):
    headers, user_id, tk = await _headers(db_manager)
    await _set_raw_prefs(db_manager, tenant_key=tk, user_id=user_id, prefs=None)

    resp = await api_client.get(_URL, headers=headers)

    assert resp.status_code == 200, resp.text
    prefs = resp.json()["notification_preferences"]
    for key, expected in _RULED_DEFAULTS.items():
        assert prefs[key] == expected


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("banner_lifecycle_enabled", False),
        ("banner_advisories_in_fold", False),
        ("popout_scope", "actionable"),
        ("popout_scope", "off"),
        ("popout_scope", "all"),
    ],
)
async def test_each_preference_round_trips(api_client, db_manager, key, value):
    headers, _user_id, _tk = await _headers(db_manager)

    put = await api_client.put(_URL, json={key: value}, headers=headers)
    assert put.status_code == 200, put.text
    assert put.json()["notification_preferences"][key] == value

    get = await api_client.get(_URL, headers=headers)
    assert get.json()["notification_preferences"][key] == value


async def test_writing_one_preference_preserves_every_sibling(api_client, db_manager):
    headers, _user_id, _tk = await _headers(db_manager)

    everything = {
        "context_tuning_reminder": False,
        "tuning_reminder_threshold": 77,
        "banner_lifecycle_enabled": False,
        "banner_advisories_in_fold": False,
        "popout_scope": "off",
    }
    seed = await api_client.put(_URL, json=everything, headers=headers)
    assert seed.status_code == 200, seed.text

    resp = await api_client.put(_URL, json={"banner_lifecycle_enabled": True}, headers=headers)
    assert resp.status_code == 200, resp.text

    prefs = resp.json()["notification_preferences"]
    assert prefs["banner_lifecycle_enabled"] is True
    for key, expected in everything.items():
        if key == "banner_lifecycle_enabled":
            continue
        assert prefs[key] == expected, f"{key} was clobbered by a single-key write"


async def test_an_empty_put_changes_nothing(api_client, db_manager):
    headers, _user_id, _tk = await _headers(db_manager)

    await api_client.put(_URL, json={"popout_scope": "off"}, headers=headers)
    resp = await api_client.put(_URL, json={}, headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["notification_preferences"]["popout_scope"] == "off"


@pytest.mark.parametrize(
    "bad",
    [
        {"popout_scope": "everything"},
        {"popout_scope": ""},
        {"popout_scope": 1},
        {"popout_scope": None},
    ],
)
async def test_an_unrecognised_popout_scope_is_refused(api_client, db_manager, bad):
    headers, _user_id, _tk = await _headers(db_manager)

    resp = await api_client.put(_URL, json=bad, headers=headers)

    assert 400 <= resp.status_code < 500, (
        f"expected a client error for {bad!r}, got {resp.status_code}: {resp.text[:200]}"
    )


async def test_one_account_never_sees_anothers_preference(api_client, db_manager):
    headers_a, _uid_a, _tk_a = await _headers(db_manager)
    headers_b, _uid_b, _tk_b = await _headers(db_manager)

    await api_client.put(_URL, json={"popout_scope": "off"}, headers=headers_a)

    resp_b = await api_client.get(_URL, headers=headers_b)
    assert resp_b.json()["notification_preferences"]["popout_scope"] == "all", "account B saw account A's preference"

    resp_a = await api_client.get(_URL, headers=headers_a)
    assert resp_a.json()["notification_preferences"]["popout_scope"] == "off"
