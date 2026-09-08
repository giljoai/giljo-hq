# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9553 M4 — per-user notification preferences, server-side.

The settings surface the one-notification-model build needs is three
preferences, and the requirement is that they live SERVER-SIDE per user:
the web UI is hosted, so settings must follow the user to every machine rather
than sitting in one browser's localStorage (which is where the toast position
and duration still live).

WHY THIS EXTENDS ``users.notification_preferences`` RATHER THAN ADDING A
SETTINGS CATEGORY. That column already exists, already has a single validated
write path through ``UserService.update_notification_preferences``, and its
endpoint pair already sits on the current-user settings route behind
``get_current_active_user`` rather than ``require_admin`` — which is correct for
a personal display preference. The route is the ``_URL`` constant below. The
``settings`` table's ``general`` category was the alternative and would have
been cheaper to copy, but its writes are
admin-gated and tenant- rather than user-scoped. Reusing the owning service for
the entity beats reusing whatever service is nearest.

THE OLD-SHAPE QUESTION, which the repo's data-facing rule requires an answer to
before shipping: every existing row holds only the two legacy keys, or NULL.
The answer here is (a), code tolerates the old shape — the read merges stored
values over the defaults, so a legacy row reads back complete without any
migration and without a write. Nothing rewrites user data to add these keys;
they appear in a row the first time that user changes one. ``test_a_legacy_row``
below is the pin for exactly that.

**Edition Scope:** Both
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager


pytestmark = pytest.mark.asyncio

_URL = "/api/v1/users/me/settings/notification-preferences"
_CSRF = "fe9553-csrf-token"

# The three keys this milestone adds, with the values the project record rules
# as defaults: lifecycle banners on, advisories in the fold on, and popout
# scope = everything a banner shows.
_RULED_DEFAULTS: dict[str, Any] = {
    "banner_lifecycle_enabled": True,
    "banner_advisories_in_fold": True,
    "popout_scope": "all",
}

_LEGACY_KEYS = ("context_tuning_reminder", "tuning_reminder_threshold")


async def _seed_user(db_manager) -> tuple[str, str, str]:
    """Create org+user; return (user_id, username, tenant_key)."""
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
    """Write the column directly, to stage a row in a shape the API cannot produce."""
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
    """A fresh user reads back all three keys, at the values the record rules."""
    headers, _user_id, _tk = await _headers(db_manager)

    resp = await api_client.get(_URL, headers=headers)

    assert resp.status_code == 200, resp.text
    prefs = resp.json()["notification_preferences"]
    for key, expected in _RULED_DEFAULTS.items():
        assert prefs[key] == expected, f"{key} should default to {expected!r}, got {prefs.get(key)!r}"


async def test_a_legacy_row_reads_back_complete_without_a_migration(api_client, db_manager):
    """The old-shape answer: tolerance, not data surgery.

    A row written before this milestone holds ONLY the two legacy keys. It must
    read back with the three new keys filled from defaults, without erroring and
    without the read rewriting the row -- CE self-hosters have no operator to
    clean their database, so the read has to cope on its own.
    """
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
    # New keys present, at defaults.
    for key, expected in _RULED_DEFAULTS.items():
        assert prefs[key] == expected
    # Legacy values untouched by the merge.
    assert prefs["context_tuning_reminder"] is False
    assert prefs["tuning_reminder_threshold"] == 42

    # And the READ did not write: the stored row is still in its old shape.
    stored = await _read_raw_prefs(db_manager, tenant_key=tk, user_id=user_id)
    assert set(stored) == set(_LEGACY_KEYS), (
        "a read must not migrate the row -- the new keys should appear only when "
        f"the user actually changes one, but the stored row is now {sorted(stored)}"
    )


async def test_a_null_row_reads_back_complete(api_client, db_manager):
    """notification_preferences is nullable, and NULL is the commonest legacy shape."""
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
    """The data-loss lesson, as a pin.

    FE-9555's settings write had to read-modify-write its category because a
    blind overwrite drops every other key. The same hazard applies here, and the
    same test shape catches it: set everything to non-default, then send ONE
    key, and check nothing else moved.
    """
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

    # One key, on its own.
    resp = await api_client.put(_URL, json={"banner_lifecycle_enabled": True}, headers=headers)
    assert resp.status_code == 200, resp.text

    prefs = resp.json()["notification_preferences"]
    assert prefs["banner_lifecycle_enabled"] is True
    for key, expected in everything.items():
        if key == "banner_lifecycle_enabled":
            continue
        assert prefs[key] == expected, f"{key} was clobbered by a single-key write"


async def test_an_empty_put_changes_nothing(api_client, db_manager):
    """An empty payload is a no-op, never a reset to defaults."""
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
    """A rejected value must be a 4xx, never a 500 and never a silent default.

    popout_scope is enum-like, and the reader treats an unknown value as its
    safe default -- so a typo that stored successfully would look like it saved
    and then quietly behave as something else forever. Same reasoning FE-9555
    gave for validating execution_mode_default against a shared tuple.
    """
    headers, _user_id, _tk = await _headers(db_manager)

    resp = await api_client.put(_URL, json=bad, headers=headers)

    assert 400 <= resp.status_code < 500, (
        f"expected a client error for {bad!r}, got {resp.status_code}: {resp.text[:200]}"
    )


async def test_one_account_never_sees_anothers_preference(api_client, db_manager):
    """Two separate accounts are isolated from each other's preferences.

    RENAMED AND RE-SCOPED. This was called
    ``test_preferences_are_per_user_not_per_tenant`` and its docstring claimed
    to pin that the preferences live on the USER row rather than being
    tenant-scoped. It cannot prove that, and the check exists because of the
    same shape from the other side on FE-9586: a mutation of theirs killed no
    test, and the test they wrote to make it bite did not bite either, because
    the platform layer was already guaranteeing what the assertion named.

    Why this one overclaimed: ``_headers`` mints a fresh tenant_key per user, so
    A and B are in different tenants. Had these preferences been stored
    tenant-scoped in the ``settings`` table instead of on ``users``, this test
    would pass identically -- so it never distinguished the two designs, it only
    ever demonstrated cross-account isolation.

    And the stronger claim is not testable at all here. ADR-009 makes tenant_key
    per-user, 1:1, permanently; there is no legal configuration in which a
    tenant holds two users, so no fixture can separate "per user" from "per
    tenant" without constructing a state the product forbids. Asserting it
    anyway would be a test of the tenancy invariant wearing this column's name.

    What this test genuinely pins, and it is worth pinning: one account's write
    does not leak into another account's read. If that ever breaks, a shared or
    mis-scoped read has been introduced.
    """
    headers_a, _uid_a, _tk_a = await _headers(db_manager)
    headers_b, _uid_b, _tk_b = await _headers(db_manager)

    await api_client.put(_URL, json={"popout_scope": "off"}, headers=headers_a)

    resp_b = await api_client.get(_URL, headers=headers_b)
    assert resp_b.json()["notification_preferences"]["popout_scope"] == "all", "account B saw account A's preference"

    # Positive control: the write A made is real. Without this, the assertion
    # above passes just as happily if the PUT silently did nothing at all.
    resp_a = await api_client.get(_URL, headers=headers_a)
    assert resp_a.json()["notification_preferences"]["popout_scope"] == "off"
