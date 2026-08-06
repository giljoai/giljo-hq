# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9322 Finding 4 — ``PUT /api/v1/users/me/context/depth`` silently reset
every depth column the caller did not send.

The defect lives at the HTTP boundary, which is why this test is here and not
in ``tests/services/``. ``api/endpoints/users.py`` calls
``depth_request.depth_config.model_dump()`` on a ``DepthConfig`` whose six
fields all carry defaults, so a partial body was materialised into a full
six-key dict before it ever reached the service. The service itself
(``UserService._update_depth_config_impl``) iterates ``config.items()`` and is
already a correct partial merge — it only ever touched what it was handed.

Reachability (measured, not inferred): the Settings -> Context tab sends
exactly FOUR of the six keys — ``frontend/src/components/settings/
ContextPriorityConfig.vue`` posts ``memory_last_n_projects``, ``git_commits``,
``vision_documents`` and ``agent_templates``, and never
``tech_stack_sections`` or ``architecture_depth``. So every save from that tab
rewrote those two back to their defaults. That was invisible while
``tech_stack_sections`` was dead, and became real data loss the moment it was
wired (2026-07-31), because a user who had selected the leaner ``'required'``
tech-stack payload silently got the full one back.

The fix is ``model_dump(exclude_unset=True)`` — the service needs no change.

Parallel-safe: unique tenant/user per test, no module-level mutable state.
"""

from __future__ import annotations

import secrets
from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.auth.jwt_manager import JWTManager


pytestmark = pytest.mark.asyncio

_CSRF = secrets.token_urlsafe(32)
_DEPTH_URL = "/api/v1/users/me/context/depth"

# Every column, and the non-default value this test parks in it.
_ALL_SIX_NON_DEFAULT = {
    "vision_documents": "full",
    "memory_last_n_projects": 10,
    "git_commits": 100,
    "agent_templates": "full",
    "tech_stack_sections": "required",
    "architecture_depth": "detailed",
}

# What the Settings -> Context tab actually posts (four of six).
_FRONTEND_SENDS = {
    "memory_last_n_projects": 1,
    "git_commits": 5,
    "vision_documents": "light",
    "agent_templates": "basic",
}

_COLUMNS = (
    "depth_vision_documents",
    "depth_memory_last_n",
    "depth_git_commits",
    "depth_agent_templates",
    "depth_tech_stack_sections",
    "depth_architecture",
)


async def _seed_user(db_manager) -> tuple[str, str, str]:
    """Create org+user; return (user_id, username, tenant_key)."""
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"be9322_user_{unique}"

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"BE9322 Org {unique}",
            slug=f"be9322-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"be9322_{unique}@example.com",
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


async def _read_depth(db_manager, *, tenant_key: str, user_id: str) -> dict:
    """Detached snapshot of the six depth columns."""
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        user = await session.get(User, user_id)
        return {col: getattr(user, col) for col in _COLUMNS}


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


async def _put_depth(api_client, headers: dict, payload: dict):
    return await api_client.put(_DEPTH_URL, json={"depth_config": payload}, headers=headers)


async def test_partial_depth_put_preserves_the_keys_the_caller_did_not_send(api_client, db_manager):
    """THE REGRESSION. A body omitting a key must leave that column alone.

    Fail-first: before the fix this asserts 'required' and reads 'all', because
    model_dump() rebuilt the omitted keys at their Pydantic defaults.
    """
    user_id, username, tk = await _seed_user(db_manager)
    headers = _auth(_mint(user_id, username, tk))

    # Park a non-default value in every column via a full six-key write.
    resp = await _put_depth(api_client, headers, _ALL_SIX_NON_DEFAULT)
    assert resp.status_code == 200, resp.text
    before = await _read_depth(db_manager, tenant_key=tk, user_id=user_id)
    assert before["depth_tech_stack_sections"] == "required"
    assert before["depth_architecture"] == "detailed"

    # Now save the way the Context tab does: four keys, two omitted.
    resp = await _put_depth(api_client, headers, _FRONTEND_SENDS)
    assert resp.status_code == 200, resp.text
    after = await _read_depth(db_manager, tenant_key=tk, user_id=user_id)

    # The omitted columns must survive untouched.
    assert after["depth_tech_stack_sections"] == "required", (
        "BE-9322 Finding 4: an omitted key was silently reset to its default "
        f"('required' -> {after['depth_tech_stack_sections']!r}). The PUT must merge, not replace."
    )
    assert after["depth_architecture"] == "detailed", (
        f"BE-9322 Finding 4: omitted key reset ('detailed' -> {after['depth_architecture']!r})."
    )

    # ...and the keys that WERE sent must still apply (guard against over-correcting).
    assert after["depth_memory_last_n"] == 1
    assert after["depth_git_commits"] == 5
    assert after["depth_vision_documents"] == "light"
    assert after["depth_agent_templates"] == "basic"


async def test_empty_depth_config_is_a_noop_not_a_six_column_reset(api_client, db_manager):
    """An empty body must change nothing.

    Fail-first: before the fix this reset all six columns to their defaults.
    """
    user_id, username, tk = await _seed_user(db_manager)
    headers = _auth(_mint(user_id, username, tk))

    resp = await _put_depth(api_client, headers, _ALL_SIX_NON_DEFAULT)
    assert resp.status_code == 200, resp.text
    before = await _read_depth(db_manager, tenant_key=tk, user_id=user_id)

    resp = await _put_depth(api_client, headers, {})
    assert resp.status_code == 200, resp.text
    after = await _read_depth(db_manager, tenant_key=tk, user_id=user_id)

    assert after == before, f"BE-9322 Finding 4: an empty depth_config rewrote columns. before={before} after={after}"


async def test_full_six_key_put_still_writes_every_column(api_client, db_manager):
    """The fix must not break the full-body path.

    The QA harness writes all six keys on every depth write, so this pins the
    behaviour that must stay identical before and after the fix.
    """
    user_id, username, tk = await _seed_user(db_manager)
    headers = _auth(_mint(user_id, username, tk))

    resp = await _put_depth(api_client, headers, _ALL_SIX_NON_DEFAULT)
    assert resp.status_code == 200, resp.text
    after = await _read_depth(db_manager, tenant_key=tk, user_id=user_id)

    assert after == {
        "depth_vision_documents": "full",
        "depth_memory_last_n": 10,
        "depth_git_commits": 100,
        "depth_agent_templates": "full",
        "depth_tech_stack_sections": "required",
        "depth_architecture": "detailed",
    }
