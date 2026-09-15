# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from pydantic import ValidationError

from giljo_mcp.events.schemas import (
    EventFactory,
    SetupCommandsInstalledData,
    SetupCommandsInstalledEvent,
    SetupToolConnectedData,
    SetupToolConnectedEvent,
    WebSocketEvent,
)




class TestSetupToolConnectedData:

    def test_valid_data(self):
        data = SetupToolConnectedData(
            tenant_key="tenant_123",
            user_id="user_456",
            tool_name="claude_code",
            connected_at="2026-03-29T10:00:00Z",
        )
        assert data.tenant_key == "tenant_123"
        assert data.user_id == "user_456"
        assert data.tool_name == "claude_code"
        assert data.connected_at == "2026-03-29T10:00:00Z"

    def test_rejects_empty_tenant_key(self):
        with pytest.raises(ValidationError):
            SetupToolConnectedData(
                tenant_key="",
                user_id="user_456",
                tool_name="claude_code",
                connected_at="2026-03-29T10:00:00Z",
            )

    def test_rejects_empty_user_id(self):
        with pytest.raises(ValidationError):
            SetupToolConnectedData(
                tenant_key="tenant_123",
                user_id="",
                tool_name="claude_code",
                connected_at="2026-03-29T10:00:00Z",
            )

    def test_rejects_empty_tool_name(self):
        with pytest.raises(ValidationError):
            SetupToolConnectedData(
                tenant_key="tenant_123",
                user_id="user_456",
                tool_name="",
                connected_at="2026-03-29T10:00:00Z",
            )

    def test_rejects_missing_connected_at(self):
        with pytest.raises(ValidationError):
            SetupToolConnectedData(
                tenant_key="tenant_123",
                user_id="user_456",
                tool_name="claude_code",
            )


class TestSetupToolConnectedEvent:

    def test_correct_type_literal(self):
        event = SetupToolConnectedEvent(
            timestamp="2026-03-29T10:00:00Z",
            data=SetupToolConnectedData(
                tenant_key="t1",
                user_id="u1",
                tool_name="claude_code",
                connected_at="2026-03-29T10:00:00Z",
            ),
        )
        assert event.type == "setup:tool_connected"

    def test_default_schema_version(self):
        event = SetupToolConnectedEvent(
            timestamp="2026-03-29T10:00:00Z",
            data=SetupToolConnectedData(
                tenant_key="t1",
                user_id="u1",
                tool_name="gemini_cli",
                connected_at="2026-03-29T10:00:00Z",
            ),
        )
        assert event.schema_version == "1.0"

    def test_type_is_immutable_literal(self):
        with pytest.raises(ValidationError):
            SetupToolConnectedEvent(
                type="wrong:type",
                timestamp="2026-03-29T10:00:00Z",
                data=SetupToolConnectedData(
                    tenant_key="t1",
                    user_id="u1",
                    tool_name="claude_code",
                    connected_at="2026-03-29T10:00:00Z",
                ),
            )




class TestSetupCommandsInstalledData:

    def test_valid_data(self):
        data = SetupCommandsInstalledData(
            tenant_key="tenant_123",
            user_id="user_456",
            tool_name="codex_cli",
            command_count=7,
        )
        assert data.tenant_key == "tenant_123"
        assert data.command_count == 7

    def test_zero_command_count_allowed(self):
        data = SetupCommandsInstalledData(
            tenant_key="t1",
            user_id="u1",
            tool_name="claude_code",
            command_count=0,
        )
        assert data.command_count == 0

    def test_rejects_negative_command_count(self):
        with pytest.raises(ValidationError):
            SetupCommandsInstalledData(
                tenant_key="t1",
                user_id="u1",
                tool_name="claude_code",
                command_count=-1,
            )

    def test_rejects_empty_tenant_key(self):
        with pytest.raises(ValidationError):
            SetupCommandsInstalledData(
                tenant_key="",
                user_id="u1",
                tool_name="claude_code",
                command_count=5,
            )

    def test_rejects_empty_user_id(self):
        with pytest.raises(ValidationError):
            SetupCommandsInstalledData(
                tenant_key="t1",
                user_id="",
                tool_name="claude_code",
                command_count=5,
            )


class TestSetupCommandsInstalledEvent:

    def test_correct_type_literal(self):
        event = SetupCommandsInstalledEvent(
            timestamp="2026-03-29T10:00:00Z",
            data=SetupCommandsInstalledData(
                tenant_key="t1",
                user_id="u1",
                tool_name="claude_code",
                command_count=5,
            ),
        )
        assert event.type == "setup:commands_installed"

    def test_default_schema_version(self):
        event = SetupCommandsInstalledEvent(
            timestamp="2026-03-29T10:00:00Z",
            data=SetupCommandsInstalledData(
                tenant_key="t1",
                user_id="u1",
                tool_name="claude_code",
                command_count=3,
            ),
        )
        assert event.schema_version == "1.0"




class TestEventFactorySetupToolConnected:

    def test_returns_dict_with_correct_type(self):
        result = EventFactory.setup_tool_connected(
            tenant_key="tenant_123",
            user_id="user_456",
            tool_name="claude_code",
        )
        assert isinstance(result, dict)
        assert result["type"] == "setup:tool_connected"

    def test_has_timestamp(self):
        result = EventFactory.setup_tool_connected(tenant_key="t1", user_id="u1", tool_name="codex_cli")
        assert "timestamp" in result
        assert result["timestamp"].endswith("Z")

    def test_data_contains_all_fields(self):
        result = EventFactory.setup_tool_connected(
            tenant_key="tenant_abc",
            user_id="user_xyz",
            tool_name="gemini_cli",
        )
        data = result["data"]
        assert data["tenant_key"] == "tenant_abc"
        assert data["user_id"] == "user_xyz"
        assert data["tool_name"] == "gemini_cli"
        assert "connected_at" in data
        assert data["connected_at"].endswith("Z")

    def test_schema_version_present(self):
        result = EventFactory.setup_tool_connected(tenant_key="t1", user_id="u1", tool_name="claude_code")
        assert result["schema_version"] == "1.0"


class TestEventFactorySetupCommandsInstalled:

    def test_returns_dict_with_correct_type(self):
        result = EventFactory.setup_commands_installed(
            tenant_key="t1", user_id="u1", tool_name="claude_code", command_count=7
        )
        assert isinstance(result, dict)
        assert result["type"] == "setup:commands_installed"

    def test_command_count_in_data(self):
        result = EventFactory.setup_commands_installed(
            tenant_key="t1", user_id="u1", tool_name="codex_cli", command_count=12
        )
        assert result["data"]["command_count"] == 12

    def test_has_timestamp(self):
        result = EventFactory.setup_commands_installed(
            tenant_key="t1", user_id="u1", tool_name="claude_code", command_count=0
        )
        assert result["timestamp"].endswith("Z")

    def test_data_contains_tool_name(self):
        result = EventFactory.setup_commands_installed(
            tenant_key="t1", user_id="u1", tool_name="gemini_cli", command_count=5
        )
        assert result["data"]["tool_name"] == "gemini_cli"




class TestWebSocketEventUnion:

    def test_setup_tool_connected_in_union(self):
        event = SetupToolConnectedEvent(
            timestamp="2026-03-29T10:00:00Z",
            data=SetupToolConnectedData(
                tenant_key="t1",
                user_id="u1",
                tool_name="claude_code",
                connected_at="2026-03-29T10:00:00Z",
            ),
        )
        assert isinstance(event, SetupToolConnectedEvent)

    def test_setup_commands_installed_in_union(self):
        event = SetupCommandsInstalledEvent(
            timestamp="2026-03-29T10:00:00Z",
            data=SetupCommandsInstalledData(
                tenant_key="t1",
                user_id="u1",
                tool_name="claude_code",
                command_count=5,
            ),
        )
        assert isinstance(event, SetupCommandsInstalledEvent)

    def test_all_setup_types_in_union_args(self):
        import typing

        union_args = typing.get_args(WebSocketEvent)
        assert SetupToolConnectedEvent in union_args
        assert SetupCommandsInstalledEvent in union_args




class TestExistingEventFactoryRegression:

    def test_project_mission_updated(self):
        result = EventFactory.project_mission_updated(
            project_id="550e8400-e29b-41d4-a716-446655440000",
            tenant_key="tenant_123",
            mission="Build feature X",
            field_toggles={},
        )
        assert result["type"] == "project:mission_updated"
        assert result["data"]["tenant_key"] == "tenant_123"

    def test_agent_created(self):
        result = EventFactory.agent_created(
            project_id="550e8400-e29b-41d4-a716-446655440000",
            tenant_key="tenant_123",
            agent={"id": "abc", "agent_display_name": "orchestrator", "status": "waiting"},
        )
        assert result["type"] == "agent:created"

    def test_agent_status_changed(self):
        result = EventFactory.agent_status_changed(
            job_id="660e8400-e29b-41d4-a716-446655440000",
            tenant_key="tenant_123",
            old_status="waiting",
            new_status="working",
            agent_display_name="implementor",
        )
        assert result["type"] == "agent:status_changed"

    def test_agent_silent(self):
        result = EventFactory.agent_silent(
            job_id="660e8400-e29b-41d4-a716-446655440000",
            tenant_key="tenant_123",
            agent_display_name="implementor",
            reason="Agent stopped communicating",
        )
        assert result["type"] == "agent:silent"
