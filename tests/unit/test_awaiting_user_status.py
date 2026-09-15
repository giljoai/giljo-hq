# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from pydantic import ValidationError as PydanticValidationError

from giljo_mcp.events.models import AgentStatusChangedData
from giljo_mcp.services.orchestration_agent_state_service import (
    OrchestrationAgentStateService,
)


def test_awaiting_user_is_a_valid_websocket_status():
    event = AgentStatusChangedData(
        job_id="j",
        project_id=None,
        tenant_key="t",
        old_status="working",
        status="awaiting_user",
        agent_display_name="implementer",
    )
    assert event.status == "awaiting_user"
    assert event.old_status == "working"


def test_unknown_status_still_rejected():
    with pytest.raises(PydanticValidationError):
        AgentStatusChangedData(
            job_id="j",
            project_id=None,
            tenant_key="t",
            old_status="working",
            status="not_a_status",
            agent_display_name="implementer",
        )


def test_awaiting_user_is_not_agent_settable():
    assert "awaiting_user" not in OrchestrationAgentStateService._AGENT_SETTABLE_STATUSES
