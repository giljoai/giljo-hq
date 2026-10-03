# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import CodedRefusalError
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _thread_with_conductor(db_manager, db_session, tenant):
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    thread = await svc.create_thread(subject="t", creator_id="lane-a", tenant_key=tenant)
    with tenant_session_context(db_session, tenant):
        db_session.add(
            CommParticipant(
                tenant_key=tenant,
                thread_id=thread["thread_id"],
                participant_id="36eac157-uuid",
                participant_type="agent",
                display_name="Ledger Zero Conductor",
            )
        )
        await db_session.flush()
    return svc, thread


async def test_post_to_a_display_name_raises_a_coded_refusal(db_manager, db_session):
    tenant = "tk_be9703c_b17_post"
    svc, thread = await _thread_with_conductor(db_manager, db_session, tenant)
    with pytest.raises(CodedRefusalError) as caught:
        await svc.post_to_thread(
            thread_id=thread["thread_id"],
            content="x",
            from_agent="lane-a",
            to_participant="Ledger Zero Conductor",
            pass_baton_to="Ledger Zero Conductor",
            tenant_key=tenant,
        )
    refusal = caught.value.as_refusal()
    assert refusal["success"] is False
    assert refusal["error"] == "TARGET_IS_A_DISPLAY_NAME"
    assert refusal["registered_id"] == "36eac157-uuid"


async def test_pass_baton_to_an_unknown_id_raises_a_coded_refusal(db_manager, db_session):
    tenant = "tk_be9703c_b17_baton"
    svc, thread = await _thread_with_conductor(db_manager, db_session, tenant)
    with pytest.raises(CodedRefusalError) as caught:
        await svc.pass_baton(thread_id=thread["thread_id"], to="nobody-here", tenant_key=tenant)
    assert caught.value.as_refusal()["error"] == "BATON_TARGET_NOT_A_PARTICIPANT"


def test_the_unused_closeout_prompt_generator_is_gone():
    from giljo_mcp.services.project_closeout_service import ProjectCloseoutService

    assert not hasattr(ProjectCloseoutService, "generate_closeout_prompt")
