# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.loop_directive_composer import append_loop_directive, compose_loop_directive
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_MARKER = "LOOP / SLEEP DIRECTIVE"


def test_append_loop_directive_inactive_is_noop():
    assert append_loop_directive("BASE", active=False) == "BASE"


def test_append_loop_directive_active_appends_marker():
    out = append_loop_directive("BASE", active=True)
    assert out.startswith("BASE")
    assert _MARKER in out


def _opener(db_session):
    @asynccontextmanager
    async def _open(tenant_key):
        with tenant_session_context(db_session, tenant_key):
            yield db_session

    return _open


async def _arm(db_session, tenant: str, agent_id: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    comm = CommThreadService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    thread = await comm.create_thread(subject="loop", creator_id=agent_id, tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="loop",
        to_participant=agent_id,
        loop_directive=True,
        from_agent="orchestrator",
        tenant_key=tenant,
    )


async def test_compose_appends_when_armed(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _arm(db_session, tenant, "agent-x")
    out = await compose_loop_directive("BASE", _opener(db_session), tenant, "agent-x")
    assert _MARKER in out


async def test_compose_noop_when_not_armed(db_session):
    tenant = TenantManager.generate_tenant_key()
    out = await compose_loop_directive("BASE", _opener(db_session), tenant, "agent-x")
    assert out == "BASE"


async def test_compose_never_raises_on_read_failure():
    def _broken(_tenant_key):
        raise RuntimeError("db down")

    out = await compose_loop_directive("BASE", _broken, "tk", "agent-x")
    assert out == "BASE"
