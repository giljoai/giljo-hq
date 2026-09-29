# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import bcrypt
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.job_completion_closeout_gate import read_closeout_mode
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


_CSRF = secrets.token_urlsafe(32)
HUB = "/api/v1/threads/chain-hub"
CLOSEOUT = "/api/v1/settings/closeout-mode"


async def _seed_admin(db_manager) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()
        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
            tenant_key=tenant_key,
            role="admin",
            org_id=org.id,
            first_name="Test",
            last_name=f"User{suffix}",
        )
        session.add(user)
        await session.flush()
        with tenant_session_context(session, tenant_key):
            await ensure_default_types_seeded(session, tenant_key)
        await session.commit()

    token = JWTManager.create_access_token(user_id=user.id, username=user.username, role="admin", tenant_key=tenant_key)
    return {
        "tenant_key": tenant_key,
        "headers": {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF},
    }


async def _seed_run_and_threads(db_manager, tenant_key: str, run_id: str, threads: list[tuple]) -> None:
    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            await session.execute(
                text(
                    "INSERT INTO sequence_runs "
                    "(id, tenant_key, project_ids, resolved_order, current_index, execution_mode, status, "
                    " review_policy, project_statuses) "
                    "VALUES (:id, :tk, '[]'::jsonb, '[]'::jsonb, 0, 'multi_terminal', 'running', "
                    " 'per_card', '{}'::jsonb)"
                ),
                {"id": run_id, "tk": tenant_key},
            )
            for tid, serial, subject, created, linked_run in threads:
                await session.execute(
                    text(
                        "INSERT INTO comm_threads (id, tenant_key, serial, subject, status, created_at, sequence_run_id) "
                        "VALUES (:id, :tk, :s, :subj, 'open', :created, :run)"
                    ),
                    {"id": tid, "tk": tenant_key, "s": serial, "subj": subject, "created": created, "run": linked_run},
                )
        await session.commit()




@pytest.mark.asyncio
async def test_chain_hub_is_the_linked_thread_not_an_older_one_that_mentions_the_run(
    api_client: AsyncClient, db_manager
) -> None:
    seed = await _seed_admin(db_manager)
    run_id = str(uuid.uuid4())
    decoy, hub = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run_and_threads(
        db_manager,
        seed["tenant_key"],
        run_id,
        [
            (decoy, 9001, f"Notes about run {run_id}", datetime(2026, 1, 1, tzinfo=UTC), None),
            (hub, 9002, "Chain: ship the widget", datetime(2026, 2, 1, tzinfo=UTC), run_id),
        ],
    )

    resp = await api_client.get(HUB, headers=seed["headers"], params={"sequence_run_id": run_id})

    assert resp.status_code == 200, resp.text
    assert resp.json()["thread"]["thread_id"] == hub


@pytest.mark.asyncio
async def test_chain_hub_is_null_when_the_run_has_none_and_hidden_across_tenants(
    api_client: AsyncClient, db_manager
) -> None:
    owner = await _seed_admin(db_manager)
    other = await _seed_admin(db_manager)
    run_id = str(uuid.uuid4())
    await _seed_run_and_threads(
        db_manager,
        owner["tenant_key"],
        run_id,
        [(str(uuid.uuid4()), 9003, "Chain hub", datetime(2026, 2, 1, tzinfo=UTC), run_id)],
    )

    unknown = await api_client.get(HUB, headers=owner["headers"], params={"sequence_run_id": str(uuid.uuid4())})
    foreign = await api_client.get(HUB, headers=other["headers"], params={"sequence_run_id": run_id})

    assert unknown.status_code == 200, unknown.text
    assert unknown.json() == {"thread": None}
    assert foreign.status_code == 200, foreign.text
    assert foreign.json() == {"thread": None}, "another tenant's chain hub leaked"




@pytest.mark.asyncio
async def test_closeout_mode_write_preserves_sibling_general_settings(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_admin(db_manager)
    async with db_manager.get_session_async() as session:
        service = SettingsService(session, seed["tenant_key"])
        general = await service.get_settings("general")
        general.update({"execution_mode_default": "subagent", "fe9702d_sibling_probe": "must survive"})
        await service.update_settings("general", general)

    resp = await api_client.put(CLOSEOUT, headers=seed["headers"], json={"closeout_mode": "autonomous"})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"closeout_mode": "autonomous"}
    async with db_manager.get_session_async() as session:
        stored = await SettingsService(session, seed["tenant_key"]).get_settings("general")
        assert await read_closeout_mode(session, seed["tenant_key"]) == "autonomous"
    assert stored.get("execution_mode_default") == "subagent"
    assert stored.get("fe9702d_sibling_probe") == "must survive"


@pytest.mark.asyncio
@pytest.mark.parametrize("junk", ["HITL", "auto", "", "true"])
async def test_closeout_mode_refuses_an_unknown_value(api_client: AsyncClient, db_manager, junk) -> None:
    seed = await _seed_admin(db_manager)

    resp = await api_client.put(CLOSEOUT, headers=seed["headers"], json={"closeout_mode": junk})

    assert resp.status_code == 422, resp.text
