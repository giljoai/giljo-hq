# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


from giljo_mcp.database import DatabaseManager
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.message_routing_service import MessageRoutingService
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.roadmap_service import RoadmapService
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.services.user_approval_service import UserApprovalService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor._chain_tools import ChainToolsMixin
from giljo_mcp.tools.tool_accessor._comm_tools import CommToolsMixin
from giljo_mcp.tools.tool_accessor._context_tools import ContextToolsMixin
from giljo_mcp.tools.tool_accessor._job_tools import JobLifecycleMixin
from giljo_mcp.tools.tool_accessor._memory_tools import MemoryToolsMixin
from giljo_mcp.tools.tool_accessor._message_tools import MessageToolsMixin
from giljo_mcp.tools.tool_accessor._project_tools import ProjectToolsMixin
from giljo_mcp.tools.tool_accessor._setup_tools import SetupMiscMixin


logger = logging.getLogger(__name__)


class ToolAccessor(
    ProjectToolsMixin,
    MessageToolsMixin,
    CommToolsMixin,
    ChainToolsMixin,
    JobLifecycleMixin,
    MemoryToolsMixin,
    ContextToolsMixin,
    SetupMiscMixin,
):

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        websocket_manager: Any | None = None,
        test_session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._websocket_manager = websocket_manager
        self._test_session = test_session

        self._product_service = None
        self._project_service = ProjectService(
            db_manager,
            tenant_manager,
            test_session=test_session,
            websocket_manager=websocket_manager,
        )
        self._task_service = TaskService(
            db_manager,
            tenant_manager,
            websocket_manager=websocket_manager,
        )
        self._roadmap_service = RoadmapService(
            db_manager,
            tenant_manager,
            session=test_session,
            websocket_manager=websocket_manager,
        )
        self._message_routing_service = MessageRoutingService(
            db_manager,
            tenant_manager,
            websocket_manager=websocket_manager,
        )
        self._comm_thread_service = CommThreadService(
            db_manager,
            tenant_manager,
            session=test_session,
        )
        self._orchestration_service = OrchestrationService(
            db_manager,
            tenant_manager,
            test_session=test_session,
            websocket_manager=websocket_manager,
        )

        self._user_approval_service = UserApprovalService(
            db_manager,
            tenant_manager,
            websocket_manager=websocket_manager,
            test_session=test_session,
            comm_thread_service=self._comm_thread_service,
        )

        self._mission_service = self._orchestration_service._mission
        self._progress_service = self._orchestration_service._progress
        self._agent_state_service = self._orchestration_service._agent_state
        self._workflow_status_service = self._orchestration_service._workflow_status
        self._job_completion_service = self._orchestration_service._job_completion

    def get_session_async(self):
        if self._test_session is not None:
            import contextlib

            @contextlib.asynccontextmanager
            async def _test_session_wrapper():
                yield self._test_session

            return _test_session_wrapper()
        return self.db_manager.get_session_async()
