# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import BOUND_THREAD_MARKER_SUBJECT
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_JAN = datetime(2026, 1, 1, tzinfo=UTC)
_FEB = datetime(2026, 2, 1, tzinfo=UTC)
_MAR = datetime(2026, 3, 1, tzinfo=UTC)


def _svc(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_project(db_session, tenant: str, pid: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        await db_session.execute(
            text("INSERT INTO products (id, tenant_key, name, is_active) VALUES (:p, :tk, 'P', true)"),
            {"p": f"prod_{tenant}", "tk": tenant},
        )
        await db_session.execute(
            text(
                "INSERT INTO projects (id, tenant_key, product_id, name, alias, description, mission, series_number) "
                "VALUES (:id, :tk, :prod, 'n', :alias, 'd', 'm', 1)"
            ),
            {"id": pid, "tk": tenant, "prod": f"prod_{tenant}", "alias": pid[:6]},
        )
        await db_session.flush()


async def _seed_thread(db_session, tenant, tid, pid, serial, subject, created) -> None:
    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            text(
                "INSERT INTO comm_threads (id, tenant_key, serial, subject, status, product_id, project_id, created_at) "
                "VALUES (:id, :tk, :s, :subj, 'open', :prod, :pid, :created)"
            ),
            {
                "id": tid,
                "tk": tenant,
                "s": serial,
                "subj": subject,
                "prod": f"prod_{tenant}",
                "pid": pid,
                "created": created,
            },
        )
        await db_session.flush()


async def _thread_count(db_session, tenant, pid) -> int:
    with tenant_session_context(db_session, tenant):
        return (
            await db_session.execute(
                text("SELECT count(*) FROM comm_threads WHERE tenant_key = :tk AND project_id = :pid"),
                {"tk": tenant, "pid": pid},
            )
        ).scalar()


async def test_none_creates_marker_thread(db_manager, db_session):
    tenant = "tk_be9012d_res_none"
    await _seed_project(db_session, tenant, "pj_n")
    svc = _svc(db_manager, db_session)
    out = await svc.resolve_or_create_bound_thread(project_id="pj_n", tenant_key=tenant)
    assert out["project_id"] == "pj_n"
    assert out["subject"] == BOUND_THREAD_MARKER_SUBJECT
    assert await _thread_count(db_session, tenant, "pj_n") == 1


async def test_single_organic_thread_is_reused_not_duplicated(db_manager, db_session):
    tenant = "tk_be9012d_res_organic"
    await _seed_project(db_session, tenant, "pj_o")
    await _seed_thread(db_session, tenant, "t_org", "pj_o", 50, "Chain hub", _JAN)
    svc = _svc(db_manager, db_session)
    out = await svc.resolve_or_create_bound_thread(project_id="pj_o", tenant_key=tenant)
    assert out["thread_id"] == "t_org", "an existing organic bound thread must be reused"
    assert await _thread_count(db_session, tenant, "pj_o") == 1, "no duplicate minted"


async def test_several_prefers_marker_thread(db_manager, db_session):
    tenant = "tk_be9012d_res_marker"
    await _seed_project(db_session, tenant, "pj_m")
    await _seed_thread(db_session, tenant, "t_org", "pj_m", 51, "Older hub", _JAN)
    await _seed_thread(db_session, tenant, "t_mark", "pj_m", 52, BOUND_THREAD_MARKER_SUBJECT, _FEB)
    svc = _svc(db_manager, db_session)
    out = await svc.resolve_or_create_bound_thread(project_id="pj_m", tenant_key=tenant)
    assert out["thread_id"] == "t_mark", "marker thread wins even when a newer/older organic exists"


async def test_several_without_marker_picks_oldest(db_manager, db_session):
    tenant = "tk_be9012d_res_oldest"
    await _seed_project(db_session, tenant, "pj_x")
    await _seed_thread(db_session, tenant, "t_old", "pj_x", 53, "hub one", _JAN)
    await _seed_thread(db_session, tenant, "t_new", "pj_x", 54, "hub two", _MAR)
    svc = _svc(db_manager, db_session)
    out = await svc.resolve_or_create_bound_thread(project_id="pj_x", tenant_key=tenant)
    assert out["thread_id"] == "t_old", "with no marker, the OLDEST bound thread is chosen (stable)"


async def test_resolve_is_idempotent(db_manager, db_session):
    tenant = "tk_be9012d_res_idem"
    await _seed_project(db_session, tenant, "pj_i")
    svc = _svc(db_manager, db_session)
    first = await svc.resolve_or_create_bound_thread(project_id="pj_i", tenant_key=tenant)
    second = await svc.resolve_or_create_bound_thread(project_id="pj_i", tenant_key=tenant)
    assert first["thread_id"] == second["thread_id"], "second resolve returns the same thread (no dup)"
    assert await _thread_count(db_session, tenant, "pj_i") == 1
