# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import purge_tenant_rows
from tests.integration.test_be9744a_split_stage_undo_mcp_boundary import (  # noqa: F401 -- fixture import
    _seed,
    be9744a_client,
)


pytestmark = pytest.mark.asyncio

TITLE = "Webhook retry backoff handler"


def _entry(tenant_key: str, product_id: str, sequence: int, name: str, summary: str, *, project_id=None, age_days=0):
    return ProductMemoryEntry(
        id=uuid4(),
        tenant_key=tenant_key,
        product_id=product_id,
        project_id=project_id,
        sequence=sequence,
        entry_type="project_completion",
        source="closeout_v1",
        timestamp=datetime.now(UTC) - timedelta(days=age_days),
        project_name=name,
        summary=summary,
    )


async def _stage(client, project_id: str) -> str:
    async with client() as session:
        staged = await session.call_tool("stage_project", {"project_id": project_id, "mode": "subagent"})
        assert not staged.is_error, staged.content
        orch_job = json.loads(staged.content[0].text)["orchestrator_id"]
        reply = await session.call_tool("get_staging_instructions", {"job_id": orch_job})
        assert not reply.is_error, reply.content
        return reply.content[0].text


async def _seed_titled(db_manager, tenant_key: str) -> tuple[str, str]:
    project_id = await _seed(db_manager, tenant_key)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(update(Project).where(Project.id == project_id).values(name=TITLE))
        product_id = (
            (await session.execute(Project.__table__.select().where(Project.id == project_id))).first().product_id
        )
        await session.commit()
    return project_id, product_id


async def test_old_matching_entry_is_inline_own_and_foreign_entries_are_not(be9744a_client, db_manager):  # noqa: F811
    client, tenant_key, _ws = be9744a_client
    project_id, product_id = await _seed_titled(db_manager, tenant_key)
    other_tenant = TenantManager.generate_tenant_key()
    _other_project_id, other_product_id = await _seed_titled(db_manager, other_tenant)
    try:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            session.add_all(
                [
                    _entry(
                        tenant_key,
                        product_id,
                        1,
                        "Old webhook work",
                        "Added webhook retry backoff. " + "Long body. " * 100,
                        age_days=90,
                    ),
                    _entry(tenant_key, product_id, 2, "Unrelated A", "Tuned the dashboard colours.", age_days=3),
                    _entry(tenant_key, product_id, 3, "Unrelated B", "Fixed a typo in the installer.", age_days=2),
                    _entry(tenant_key, product_id, 4, "Unrelated C", "Bumped a dependency.", age_days=1),
                    _entry(
                        tenant_key,
                        product_id,
                        5,
                        TITLE,
                        "Webhook retry backoff handler own entry.",
                        project_id=project_id,
                    ),
                ]
            )
            await session.commit()
        async with db_manager.get_session_async(tenant_key=other_tenant) as session:
            session.add(
                _entry(other_tenant, other_product_id, 1, "Foreign webhook", "Foreign webhook retry backoff secret.")
            )
            await session.commit()

        text = await _stage(client, project_id)
        related = json.loads(text)["related_past_work"]

        sequences = [item["sequence"] for item in related]
        assert 1 in sequences, f"the old matching entry must be inline: {related!r}"
        assert 5 not in sequences, "the project's own entry must be excluded"
        assert len(related) <= 3
        assert "Foreign webhook" not in text and "secret" not in text, "another tenant's entry must never appear"
        first = next(item for item in related if item["sequence"] == 1)
        assert first["project_name"] == "Old webhook work"
        assert first["summary"] and first["date"]
        assert len(first["summary"]) <= 240, "headline only, never the full body"
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
        await purge_tenant_rows(db_manager, other_tenant)


async def test_empty_memory_gives_an_empty_list_and_a_working_reply(be9744a_client, db_manager):  # noqa: F811
    client, tenant_key, _ws = be9744a_client
    project_id, _product_id = await _seed_titled(db_manager, tenant_key)
    try:
        text = await _stage(client, project_id)
        payload = json.loads(text)
        assert payload["related_past_work"] == []
        assert "orchestrator_protocol" in payload
    finally:
        await purge_tenant_rows(db_manager, tenant_key)


async def test_a_failing_search_does_not_break_staging(be9744a_client, db_manager, monkeypatch):  # noqa: F811
    from sqlalchemy.exc import SQLAlchemyError

    from giljo_mcp.services.product_memory_service import ProductMemoryService

    async def _boom(self, *args, **kwargs):
        raise SQLAlchemyError("search down")

    monkeypatch.setattr(ProductMemoryService, "search_memory", _boom)
    client, tenant_key, _ws = be9744a_client
    project_id, _product_id = await _seed_titled(db_manager, tenant_key)
    try:
        payload = json.loads(await _stage(client, project_id))
        assert payload["related_past_work"] == []
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
