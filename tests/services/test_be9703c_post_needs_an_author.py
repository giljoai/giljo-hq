# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.tasks import Message
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def test_post_without_author_is_refused_and_writes_nothing(db_manager, db_session):
    tenant = "tk_be9703c_b08_anon"
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    thread = await svc.create_thread(subject="t", creator_id="lane-a", tenant_key=tenant)

    with pytest.raises(ValidationError, match="from_agent"):
        await svc.post_to_thread(thread_id=thread["thread_id"], content="hi", user_id="user-1", tenant_key=tenant)

    with tenant_session_context(db_session, tenant):
        count = await db_session.scalar(
            select(func.count()).select_from(Message).where(Message.thread_id == thread["thread_id"])
        )
    assert count == 0
