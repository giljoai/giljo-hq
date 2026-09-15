# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.settings_service import TenantSkillsAckService


pytestmark = pytest.mark.asyncio




async def _make_tenant_in_db(db_manager) -> str:
    suffix = uuid4().hex[:8]
    tk = f"skills_test_{suffix}"
    from giljo_mcp.database import tenant_session_context

    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tk):
            org = Organization(
                id=str(uuid4()),
                tenant_key=tk,
                name=f"Skills Org {suffix}",
                slug=f"skills-org-{suffix}",
                is_active=True,
            )
            session.add(org)
            await session.commit()
    return tk


async def _get_ack_version(db_manager, tenant_key: str) -> str | None:
    async with db_manager.get_session_async() as session:
        svc = TenantSkillsAckService(session, tenant_key)
        return await svc.get_acknowledged_version()




async def test_acknowledge_only_updates_calling_tenant(db_manager):
    tk_a = await _make_tenant_in_db(db_manager)
    tk_b = await _make_tenant_in_db(db_manager)

    async with db_manager.get_session_async() as session:
        svc_a = TenantSkillsAckService(session, tk_a)
        returned = await svc_a.acknowledge("1.1.0")

    assert returned == "1.1.0"

    version_a = await _get_ack_version(db_manager, tk_a)
    version_b = await _get_ack_version(db_manager, tk_b)

    assert version_a == "1.1.0"
    assert version_b is None, "tenant_B must not be affected by tenant_A's acknowledge()"


async def test_get_acknowledged_version_returns_none_for_never_acked(db_manager):
    suffix = uuid4().hex[:8]
    tk = f"neveracked_{suffix}"
    version = await _get_ack_version(db_manager, tk)
    assert version is None


async def test_acknowledge_creates_then_updates(db_manager):
    tk = await _make_tenant_in_db(db_manager)

    async with db_manager.get_session_async() as session:
        svc = TenantSkillsAckService(session, tk)
        await svc.acknowledge("1.0.0")

    async with db_manager.get_session_async() as session:
        svc = TenantSkillsAckService(session, tk)
        await svc.acknowledge("1.1.0")

    result = await _get_ack_version(db_manager, tk)
    assert result == "1.1.0"


async def test_tenant_a_ack_resolves_only_tenant_a_drift(db_manager):
    tk_a = await _make_tenant_in_db(db_manager)
    tk_b = await _make_tenant_in_db(db_manager)

    current_version = "99.0.0"

    async with db_manager.get_session_async() as session:
        svc_a = TenantSkillsAckService(session, tk_a)
        await svc_a.acknowledge("1.0.0")

    from api.startup.background_tasks import _compute_skills_drift

    with patch("giljo_mcp.tools.slash_command_templates.SKILLS_VERSION", current_version):
        drift_a_before = await _compute_skills_drift(db_manager, tk_a)
        drift_b_before = await _compute_skills_drift(db_manager, tk_b)

    assert drift_a_before is not None, "A should have drift before acknowledging current"
    assert drift_b_before is None, "B never acked -> no banner"

    async with db_manager.get_session_async() as session:
        svc_a = TenantSkillsAckService(session, tk_a)
        await svc_a.acknowledge(current_version)

    with patch("giljo_mcp.tools.slash_command_templates.SKILLS_VERSION", current_version):
        drift_a_after = await _compute_skills_drift(db_manager, tk_a)
        drift_b_after = await _compute_skills_drift(db_manager, tk_b)

    assert drift_a_after is None, "A resolved its drift — banner should clear"
    assert drift_b_after is None, "B still never-acked — no banner"




async def test_compute_skills_drift_when_acknowledged_older(db_manager):
    from api.startup.background_tasks import _compute_skills_drift

    suffix = uuid4().hex[:8]
    tk = f"drift_old_{suffix}"

    async with db_manager.get_session_async() as session:
        svc = TenantSkillsAckService(session, tk)
        await svc.acknowledge("1.0.0")

    with patch("giljo_mcp.tools.slash_command_templates.SKILLS_VERSION", "2.0.0"):
        result = await _compute_skills_drift(db_manager, tk)

    assert result is not None
    assert result["current"] == "2.0.0"
    assert result["announced"] == "1.0.0"
    assert "message" in result


async def test_compute_skills_drift_no_drift_when_equal(db_manager):
    from api.startup.background_tasks import _compute_skills_drift

    suffix = uuid4().hex[:8]
    tk = f"drift_eq_{suffix}"

    async with db_manager.get_session_async() as session:
        svc = TenantSkillsAckService(session, tk)
        await svc.acknowledge("1.1.16")

    with patch("giljo_mcp.tools.slash_command_templates.SKILLS_VERSION", "1.1.16"):
        result = await _compute_skills_drift(db_manager, tk)

    assert result is None


async def test_compute_skills_drift_no_drift_when_never_acked(db_manager):
    from api.startup.background_tasks import _compute_skills_drift

    suffix = uuid4().hex[:8]
    tk = f"drift_never_{suffix}"

    with patch("giljo_mcp.tools.slash_command_templates.SKILLS_VERSION", "2.0.0"):
        result = await _compute_skills_drift(db_manager, tk)

    assert result is None, "Never-acked tenant must not trigger a banner"
