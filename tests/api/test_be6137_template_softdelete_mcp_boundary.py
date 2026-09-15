# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from giljo_mcp.models.templates import AgentTemplate


pytestmark = pytest.mark.asyncio




class _TestSessionDbManager:

    def __init__(self, session) -> None:
        self._session = session

    @contextlib.asynccontextmanager
    async def get_session_async(self, **_kwargs):
        yield self._session




def _make_template(tenant_key: str, name: str | None = None) -> AgentTemplate:
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name or f"be6137-mcp-{uuid4().hex[:8]}",
        role="custom",
        category="custom",
        system_instructions="# BE-6137 MCP boundary test template",
        is_active=True,
        version="1.0.0",
    )




async def test_list_agent_templates_excludes_soft_deleted(db_session, test_tenant_key):
    from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates

    live = _make_template(test_tenant_key)
    trashed = _make_template(test_tenant_key)
    trashed.deleted_at = datetime.now(UTC)

    db_session.add(live)
    db_session.add(trashed)
    await db_session.flush()

    db_mgr = _TestSessionDbManager(db_session)
    result = await get_agent_templates(
        product_id="",
        tenant_key=test_tenant_key,
        detail="basic",
        db_manager=db_mgr,
    )

    templates_data = result.get("data", [])
    names_in_result = {t.get("name") for t in templates_data}

    assert live.name in names_in_result, "Live template must appear in get_agent_templates"
    assert trashed.name not in names_in_result, "Soft-deleted template must NOT appear in get_agent_templates"


async def test_list_agent_templates_shows_restored(db_session, test_tenant_key):
    from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates

    tpl = _make_template(test_tenant_key)
    tpl.deleted_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.add(tpl)
    await db_session.flush()

    db_mgr = _TestSessionDbManager(db_session)

    result_before = await get_agent_templates(
        product_id="", tenant_key=test_tenant_key, detail="basic", db_manager=db_mgr
    )
    names_before = {t.get("name") for t in result_before.get("data", [])}
    assert tpl.name not in names_before

    await db_session.execute(update(AgentTemplate).where(AgentTemplate.id == tpl.id).values(deleted_at=None))
    await db_session.flush()

    result_after = await get_agent_templates(
        product_id="", tenant_key=test_tenant_key, detail="basic", db_manager=db_mgr
    )
    names_after = {t.get("name") for t in result_after.get("data", [])}
    assert tpl.name in names_after, "Restored template must re-appear in get_agent_templates"




async def test_get_self_identity_excludes_soft_deleted(db_session, test_tenant_key):
    from giljo_mcp.tools.context_tools.get_self_identity import get_self_identity

    name = f"be6137-si-{uuid4().hex[:8]}"
    tpl = _make_template(test_tenant_key, name=name)
    tpl.deleted_at = datetime.now(UTC)
    db_session.add(tpl)
    await db_session.flush()

    result = await get_self_identity(
        agent_name=name,
        tenant_key=test_tenant_key,
        session=db_session,
    )

    meta_error = result.get("metadata", {}).get("error")
    data = result.get("data", {})
    assert data == {} or meta_error == "template_not_found", (
        f"Expected not-found response for soft-deleted template, got: {result}"
    )


async def test_get_self_identity_shows_restored(db_session, test_tenant_key):
    from giljo_mcp.tools.context_tools.get_self_identity import get_self_identity

    name = f"be6137-si-{uuid4().hex[:8]}"
    tpl = _make_template(test_tenant_key, name=name)
    tpl.deleted_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.add(tpl)
    await db_session.flush()

    result_before = await get_self_identity(agent_name=name, tenant_key=test_tenant_key, session=db_session)
    assert result_before.get("data") == {} or result_before.get("metadata", {}).get("error") == "template_not_found"

    await db_session.execute(update(AgentTemplate).where(AgentTemplate.id == tpl.id).values(deleted_at=None))
    await db_session.flush()

    result_after = await get_self_identity(agent_name=name, tenant_key=test_tenant_key, session=db_session)
    data = result_after.get("data", {})
    assert data.get("name") == name, f"Restored template must appear in get_self_identity, got: {result_after}"
