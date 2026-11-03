# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest

from giljo_mcp.models.sequence_runs import SequenceRun
from tests.helpers.test_db_helper import purge_tenant_rows
from tests.integration.test_be9384_mcp_completion_archive_lifecycle import (  # noqa: F401 -- fixture import
    _call_update_project,
    _content_text,
    _payload,
    _read_back,
    _seed_project_with_completed_agent,
    mcp_client,
)


pytestmark = pytest.mark.asyncio


async def _call_closeout(client, project_id: str) -> object:
    async with client() as mcp_session:
        return await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project_id,
                "key_outcomes": ["BE-0031 fixture outcome"],
                "decisions_made": ["BE-0031 fixture decision"],
                "no_code_changes": "BE-0031 test fixture: nothing was committed.",
                "summary": "BE-0031 fixture closeout.",
            },
        )


class TestCloseoutCompletesASoloProject:
    async def test_closeout_completes_a_solo_project(self, mcp_client, db_manager):  # noqa: F811 -- imported fixture
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(db_manager, tenant_key)

        try:
            result = await _call_closeout(client, project_id)
            assert not result.is_error, _content_text(result)
            payload = _payload(result)
            assert payload.get("entry_id"), f"the closeout must still write its 360 entry: {payload!r}"

            project, execution = await _read_back(db_manager, tenant_key, project_id, execution_id)
            assert project.status == "completed", "a solo closeout must finish the project itself"
            assert project.completed_at is not None
            assert execution.status == "closed", "the archive lifecycle closes agents left at 'complete'"

            message = payload.get("message", "")
            assert "completed" in message and "update_project" not in message, (
                f"the reply must say the project is completed, not send the agent to update_project: {message!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_later_update_project_completed_stays_harmless(self, mcp_client, db_manager):  # noqa: F811 -- imported fixture
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(db_manager, tenant_key)

        try:
            closeout = await _call_closeout(client, project_id)
            assert not closeout.is_error, _content_text(closeout)

            result = await _call_update_project(client, project_id, "completed")
            assert not result.is_error, _content_text(result)
            assert _payload(result).get("success") is True, _content_text(result)

            project, _ = await _read_back(db_manager, tenant_key, project_id, execution_id)
            assert project.status == "completed"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_chain_member_closeout_does_not_run_the_archive_lifecycle(self, mcp_client, db_manager):  # noqa: F811 -- imported fixture
        client, tenant_key = mcp_client
        project_id, execution_id = await _seed_project_with_completed_agent(db_manager, tenant_key)

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            session.add(
                SequenceRun(
                    id=str(uuid.uuid4()),
                    tenant_key=tenant_key,
                    project_ids=[project_id],
                    resolved_order=[project_id],
                    current_index=0,
                    execution_mode="claude_code_cli",
                    status="running",
                    locked=True,
                    project_statuses={project_id: "implementing"},
                )
            )
            await session.commit()

        try:
            result = await _call_closeout(client, project_id)
            assert not result.is_error, _content_text(result)
            assert "archive lifecycle" not in _payload(result).get("message", "")

            _, execution = await _read_back(db_manager, tenant_key, project_id, execution_id)
            assert execution.status == "complete", "a chain member must not run the archive lifecycle"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)
