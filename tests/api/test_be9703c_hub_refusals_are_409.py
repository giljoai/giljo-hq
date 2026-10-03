# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommParticipant, CommThread
from tests.api.test_comm_threads_endpoints import _create_thread, _seed_tenant


@pytest.mark.asyncio
async def test_post_to_a_display_name_answers_409_with_the_hint(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    async with db_manager.get_session_async() as session:
        session.add(
            CommParticipant(
                tenant_key=seed["tenant_key"],
                thread_id=thread["thread_id"],
                participant_id="36eac157-uuid",
                participant_type="agent",
                display_name="Ledger Zero Conductor",
            )
        )
        await session.commit()

    resp = await api_client.post(
        f"/api/v1/threads/{thread['thread_id']}/post",
        headers=seed["headers"],
        json={"content": "decision needed", "to_participant": "Ledger Zero Conductor", "requires_action": True},
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "TARGET_IS_A_DISPLAY_NAME"
    assert "36eac157-uuid" in body["message"]
    assert body["context"]["registered_id"] == "36eac157-uuid"


@pytest.mark.asyncio
async def test_baton_to_an_unknown_participant_answers_409_and_moves_nothing(
    api_client: AsyncClient, db_manager
) -> None:
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])

    resp = await api_client.post(
        f"/api/v1/threads/{thread['thread_id']}/baton", headers=seed["headers"], json={"to": "nobody-here"}
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "BATON_TARGET_NOT_A_PARTICIPANT"
    assert "nobody-here" in body["message"]
    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, seed["tenant_key"]):
            owner = await session.scalar(
                select(CommThread.next_action_owner).where(CommThread.id == thread["thread_id"])
            )
    assert owner == thread["next_action_owner"]
