# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for JSONB validation models and convenience functions.

Validates Pydantic models enforce schema consistency for remaining JSONB columns.
Pure unit tests — no database access required.

Created: Handover 0840
"""

import pytest
from pydantic import ValidationError

from giljo_mcp.schemas.jsonb_validators import (
    AgentJobMetadata,
    GitCommitEntry,
    GitCommitTitleRequiredError,
    OrganizationSettings,
    ProductMemoryConfig,
    ProductTuningState,
    SettingsData,
    validate_git_commits,
    validate_product_memory,
    validate_tuning_state,
)


# ============================================================================
# AgentJobMetadata
# ============================================================================


class TestAgentJobMetadata:
    """Tests for AgentJobMetadata model (BE-9000h real key inventory)."""

    def test_valid_full_data(self):
        data = {
            "field_toggles": {"tech_stack": 1},
            "depth_config": {"memory_last_n_projects": 5},
            "user_id": "u-123",
            "tool": "claude",
            "created_via": "thin_client_spawn",
        }
        model = AgentJobMetadata(**data)
        assert model.field_toggles == {"tech_stack": 1}
        assert model.tool == "claude"

    def test_empty_data_uses_defaults(self):
        model = AgentJobMetadata()
        assert model.field_toggles is None
        assert model.depth_config is None
        assert model.todo_steps is None

    def test_extra_keys_allowed(self):
        data = {"custom_runtime_key": "some_value", "another_key": 42}
        model = AgentJobMetadata(**data)
        assert model.custom_runtime_key == "some_value"
        assert model.another_key == 42

    def test_invalid_tool_type(self):
        with pytest.raises(ValidationError):
            AgentJobMetadata(tool=["not", "a", "string"])

    def test_oversize_current_step_rejected(self):
        with pytest.raises(ValidationError):
            AgentJobMetadata(todo_steps={"current_step": "x" * 5000})


# ============================================================================
# GitCommitEntry
# ============================================================================


class TestGitCommitEntry:
    """Tests for GitCommitEntry model."""

    def test_valid_entry(self):
        entry = GitCommitEntry(sha="abc123", message="fix bug")
        assert entry.sha == "abc123"
        assert entry.message == "fix bug"
        assert entry.author is None

    def test_valid_entry_with_author(self):
        entry = GitCommitEntry(sha="abc123", message="fix bug", author="dev@example.com")
        assert entry.author == "dev@example.com"

    def test_missing_sha_raises(self):
        with pytest.raises(ValidationError):
            GitCommitEntry(message="fix bug")

    def test_missing_message_raises(self):
        with pytest.raises(ValidationError):
            GitCommitEntry(sha="abc123")

    def test_both_required_missing(self):
        with pytest.raises(ValidationError):
            GitCommitEntry()


# ============================================================================
# SettingsData & OrganizationSettings (flexible containers)
# ============================================================================


class TestSettingsData:
    """Tests for SettingsData model."""

    def test_accepts_any_keys(self):
        data = {"general": {"theme": "dark"}, "network": {"port": 8080}}
        model = SettingsData(**data)
        assert model.general == {"theme": "dark"}

    def test_empty_is_valid(self):
        model = SettingsData()
        assert model.model_dump() == {}


class TestOrganizationSettings:
    """Tests for OrganizationSettings model."""

    def test_accepts_any_keys(self):
        model = OrganizationSettings(max_users=50, plan="enterprise")
        assert model.max_users == 50

    def test_empty_is_valid(self):
        model = OrganizationSettings()
        assert model.model_dump() == {}


# ============================================================================
# ProductMemoryConfig
# ============================================================================


class TestProductMemoryConfig:
    """Tests for ProductMemoryConfig model."""

    def test_legacy_github_key_still_loads(self):
        # BE-9261: "github" is the pre-rename seed key. Rows written before the
        # rename must still validate and load their data.
        data = {
            "github": {"enabled": True, "commit_limit": 25},
            "context": {"last_updated": "2026-03-25"},
        }
        model = ProductMemoryConfig(**data)
        assert model.github["enabled"] is True

    def test_git_integration_key_accepted(self):
        # BE-9261: "git_integration" is the current seed key.
        data = {
            "git_integration": {"enabled": True, "commit_limit": 25},
            "context": {"last_updated": "2026-03-25"},
        }
        model = ProductMemoryConfig(**data)
        assert model.git_integration["enabled"] is True
        assert model.github is None

    def test_empty_data(self):
        model = ProductMemoryConfig()
        assert model.git_integration is None
        assert model.github is None
        assert model.context is None

    def test_empty_dicts_allowed(self):
        model = ProductMemoryConfig(git_integration={}, github={}, context={})
        assert model.git_integration == {}
        assert model.github == {}


# ============================================================================
# ProductTuningState
# ============================================================================


class TestProductTuningState:
    """Tests for ProductTuningState model."""

    def test_valid_data(self):
        data = {
            "last_tuned_at": "2026-03-20T10:00:00Z",
            "last_tuned_at_sequence": 5,
        }
        model = ProductTuningState(**data)
        assert model.last_tuned_at_sequence == 5

    def test_empty_data(self):
        model = ProductTuningState()
        assert model.last_tuned_at is None
        assert model.last_tuned_at_sequence is None

    def test_extra_keys_allowed(self):
        model = ProductTuningState(custom_flag=True)
        assert model.custom_flag is True


# ============================================================================
# Convenience validator functions
# ============================================================================


class TestValidateGitCommits:
    """Tests for validate_git_commits convenience function."""

    def test_none_returns_none(self):
        assert validate_git_commits(None) is None

    def test_valid_list(self):
        commits = [
            {"sha": "abc123", "message": "fix bug"},
            {"sha": "def456", "message": "add feature", "author": "dev"},
        ]
        result = validate_git_commits(commits)
        assert len(result) == 2
        assert result[0]["sha"] == "abc123"
        assert result[1]["author"] == "dev"

    def test_missing_required_field_raises(self):
        # BE-9256: a missing message (no commit title) raises the dedicated
        # fail-closed error, not a generic pydantic ValidationError.
        with pytest.raises(GitCommitTitleRequiredError):
            validate_git_commits([{"sha": "abc123"}])

    def test_bare_sha_string_rejected(self):
        # BE-9256 (flips BE-6208a): a bare SHA has no title and is rejected.
        with pytest.raises(GitCommitTitleRequiredError):
            validate_git_commits(["abc123"])

    def test_empty_list(self):
        result = validate_git_commits([])
        assert result == []


class TestValidateProductMemory:
    """Tests for validate_product_memory convenience function."""

    def test_none_returns_none(self):
        assert validate_product_memory(None) is None

    def test_valid_data(self):
        result = validate_product_memory({"git_integration": {"enabled": True}})
        assert result["git_integration"]["enabled"] is True

    def test_legacy_github_key_tolerated(self):
        # BE-9261: "github" is a declared field kept for read-tolerance, not
        # folded into extra="allow" -- a legacy-shaped row must still validate
        # and round-trip its data.
        result = validate_product_memory({"github": {"enabled": True}, "context": {}})
        assert result["github"] == {"enabled": True}


class TestValidateTuningState:
    """Tests for validate_tuning_state convenience function."""

    def test_none_returns_none(self):
        assert validate_tuning_state(None) is None

    def test_valid_data(self):
        result = validate_tuning_state({"last_tuned_at": "2026-03-25T00:00:00Z"})
        assert result["last_tuned_at"] == "2026-03-25T00:00:00Z"

    def test_empty_dict(self):
        result = validate_tuning_state({})
        assert result["last_tuned_at"] is None
        assert result["last_tuned_at_sequence"] is None


class TestNotificationPayloadValidators:
    """IMP-5037b: system banner payload schemas + registry dispatch."""

    def test_pending_migrations_valid(self):
        from giljo_mcp.schemas.jsonb_validators import validate_notification_payload

        out = validate_notification_payload("system.pending_migrations", {"pending": 3, "head": "ce_0040"})
        assert out == {"pending": 3, "head": "ce_0040"}

    def test_pending_migrations_rejects_extra_key(self):
        from giljo_mcp.schemas.jsonb_validators import validate_notification_payload

        with pytest.raises(ValidationError):
            validate_notification_payload("system.pending_migrations", {"pending": 3, "head": "ce_0040", "x": 1})

    def test_update_available_optional_fields(self):
        from giljo_mcp.schemas.jsonb_validators import validate_notification_payload

        out = validate_notification_payload("system.update_available", {"commits_behind": 5})
        assert out["commits_behind"] == 5
        assert out["release_url"] is None

    def test_skills_drift_valid(self):
        from giljo_mcp.schemas.jsonb_validators import validate_notification_payload

        out = validate_notification_payload(
            "system.skills_drift", {"current": "1.2.0", "announced": "1.1.0", "message": "drift"}
        )
        assert out["current"] == "1.2.0"

    def test_unknown_type_raises_keyerror(self):
        from giljo_mcp.schemas.jsonb_validators import validate_notification_payload

        with pytest.raises(KeyError):
            validate_notification_payload("system.does_not_exist", {})

    def test_register_adds_to_registry(self):
        from pydantic import BaseModel

        from giljo_mcp.schemas.jsonb_validators import (
            NOTIFICATION_PAYLOAD_VALIDATORS,
            register_notification_payload_validators,
            validate_notification_payload,
        )

        class _DummyPayload(BaseModel):
            foo: str

        try:
            register_notification_payload_validators({"test.dummy_register": _DummyPayload})
            out = validate_notification_payload("test.dummy_register", {"foo": "bar"})
            assert out == {"foo": "bar"}
        finally:
            NOTIFICATION_PAYLOAD_VALIDATORS.pop("test.dummy_register", None)
