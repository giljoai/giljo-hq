# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.progress_service import ProgressService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("field", ["todo_items", "todo_append"])
async def test_unknown_todo_status_is_refused_not_stored_as_pending(db_manager, db_session, field):
    svc = ProgressService(db_manager, TenantManager(), test_session=db_session)
    with pytest.raises(ValidationError, match="status"):
        await svc.report_progress(
            job_id="job-b14",
            tenant_key="tk_be9703c_b14",
            **{field: [{"content": "ship it", "status": "done"}]},
        )


async def test_unknown_creator_type_is_refused_not_stored_as_agent(db_manager, db_session):
    tenant = "tk_be9703c_b14_thread"
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
    svc = CommThreadService(db_manager, TenantManager(), session=db_session)
    with pytest.raises(ValidationError, match="creator_type"):
        await svc.create_thread(subject="t", creator_id="lane-a", creator_type="robot", tenant_key=tenant)


async def test_agent_result_without_a_tenant_is_refused_not_answered_as_missing(db_manager, db_session):
    svc = OrchestrationService(db_manager, TenantManager(), test_session=db_session)
    TenantManager.clear_current_tenant()
    with pytest.raises(ValidationError, match="tenant"):
        await svc.get_agent_result(job_id="job-b14")
