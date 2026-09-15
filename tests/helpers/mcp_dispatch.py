# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import functools
from typing import Any
from unittest.mock import create_autospec

from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.message_routing_service import MessageRoutingService
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.progress_service import ProgressService
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.roadmap_service import RoadmapService
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.services.workflow_status_service import WorkflowStatusService


_SERVICE_SPECS: dict[str, type] = {
    "_project_service": ProjectService,
    "_task_service": TaskService,
    "_roadmap_service": RoadmapService,
    "_message_routing_service": MessageRoutingService,
    "_comm_thread_service": CommThreadService,
    "_mission_service": MissionService,
    "_progress_service": ProgressService,
    "_agent_state_service": OrchestrationAgentStateService,
    "_workflow_status_service": WorkflowStatusService,
    "_job_completion_service": JobCompletionService,
    "_orchestration_service": OrchestrationService,
}


def attach_registry_service_autospecs(accessor: Any, return_value: Any) -> Any:
    from api.endpoints.mcp_tools._base import TOOL_DISPATCH

    for attr, cls in _SERVICE_SPECS.items():
        setattr(accessor, attr, create_autospec(cls, instance=True))
    accessor._websocket_manager = None
    accessor.db_manager = None

    for resolver in TOOL_DISPATCH.values():
        fn = resolver(accessor)
        target = fn.func if isinstance(fn, functools.partial) else fn
        target.return_value = return_value

    return accessor
