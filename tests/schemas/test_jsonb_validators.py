# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for JSONB validator functions and Pydantic models.

Covers: new validators added in Handover 0962c, fixes to ProductMemoryConfig
field names, and the BE-9000h rewrite of AgentJobMetadata to the real key
inventory (declared todo_steps nested cache + agent-string length caps).
Updated: settings category validators added for config.yaml -> DB migration.

Created: Handover 0962c
"""

import pytest
from pydantic import ValidationError

from giljo_mcp.schemas.jsonb_validators import (
    SETTINGS_CATEGORY_VALIDATORS,
    AgentExecutionResult,
    AgentJobMetadata,
    GitCommitTitleRequiredError,
    GitIntegrationSettings,
    IntegrationsSettingsData,
    ProductMemoryConfig,
    SecuritySettingsData,
    SerenaMcpSettings,
    validate_agent_execution_result,
    validate_behavioral_rules,
    validate_git_commits,
    validate_settings_by_category,
    validate_success_criteria,
)


# ---------------------------------------------------------------------------
# AgentJobMetadata — rewritten to the real key inventory (BE-9000h)
# ---------------------------------------------------------------------------


class TestAgentJobMetadata:
    def test_valid_real_keys(self):
        meta = AgentJobMetadata(field_toggles={"foo": 1}, depth_config={"level": 2})
        assert meta.field_toggles == {"foo": 1}
        assert meta.depth_config == {"level": 2}

    def test_extra_fields_allowed(self):
        meta = AgentJobMetadata(unknown_key="value")
        assert meta.model_dump()["unknown_key"] == "value"

    def test_todo_steps_is_a_declared_field(self):
        fields = AgentJobMetadata.model_fields
        assert "todo_steps" in fields, "BE-9000h re-declared todo_steps as a validated nested cache"

    def test_todo_steps_validated_as_nested_model(self):
        meta = AgentJobMetadata(
            todo_steps={"total_steps": 3, "completed_steps": 1, "skipped_steps": 0, "current_step": "step 1"}
        )
        assert meta.todo_steps.current_step == "step 1"
        assert meta.todo_steps.total_steps == 3

    def test_oversize_current_step_rejected(self):
        with pytest.raises(ValidationError):
            AgentJobMetadata(todo_steps={"current_step": "x" * 5000})

    def test_oversize_tool_rejected(self):
        with pytest.raises(ValidationError):
            AgentJobMetadata(tool="x" * 500)


# ---------------------------------------------------------------------------
# ProductMemoryConfig — seed key renamed github -> git_integration (BE-9261)
# ---------------------------------------------------------------------------


class TestProductMemoryConfig:
    def test_canonical_keys_accepted(self):
        cfg = ProductMemoryConfig(git_integration={"enabled": True}, context={"summary": "test"})
        assert cfg.git_integration == {"enabled": True}
        assert cfg.context == {"summary": "test"}

    def test_empty_dict_accepted(self):
        cfg = ProductMemoryConfig(git_integration={}, context={})
        assert cfg.git_integration == {}

    def test_legacy_github_key_still_accepted(self):
        # BE-9261: "github" is the pre-rename seed key -- kept as a declared
        # field (not folded into extra) purely for read tolerance so rows
        # written before the rename keep loading.
        cfg = ProductMemoryConfig(github={"repo_url": "https://github.com/x/y"})
        dumped = cfg.model_dump()
        assert dumped.get("github") == {"repo_url": "https://github.com/x/y"}

    def test_declared_fields_are_git_integration_github_and_context(self):
        fields = set(ProductMemoryConfig.model_fields.keys())
        assert "git_integration" in fields
        assert "github" in fields
        assert "context" in fields
        assert "context_metadata" not in fields


# ---------------------------------------------------------------------------
# AgentExecutionResult — new validator
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AgentExecutionResult — model tests (validator function removed, model kept)
# ---------------------------------------------------------------------------


class TestAgentExecutionResult:
    def test_valid_full(self):
        result = AgentExecutionResult(
            summary="Done",
            artifacts=["path/to/file.py"],
            commits=["abc123"],
        )
        assert result.summary == "Done"
        assert result.artifacts == ["path/to/file.py"]
        assert result.commits == ["abc123"]

    def test_all_fields_optional(self):
        result = AgentExecutionResult()
        assert result.summary is None
        assert result.artifacts is None
        assert result.commits is None

    def test_extra_fields_allowed(self):
        result = AgentExecutionResult(summary="Done", extra_field="extra_value")
        assert result.model_dump()["extra_field"] == "extra_value"

    # BE-8003j: branch / pr_url are first-class web-coding hand-off fields.
    def test_branch_and_pr_url_are_first_class(self):
        result = AgentExecutionResult(branch="feat/x", pr_url="https://git.example/pr/1")
        assert result.branch == "feat/x"
        assert result.pr_url == "https://git.example/pr/1"

    def test_branch_and_pr_url_default_none(self):
        result = AgentExecutionResult(summary="Done")
        assert result.branch is None
        assert result.pr_url is None

    def test_validate_execution_result_preserves_branch_and_pr_url(self):
        payload = {"summary": "Done", "branch": "feat/x", "pr_url": "https://git.example/pr/1"}
        # returns the ORIGINAL payload unchanged on success (no reshaping/dropping)
        assert validate_agent_execution_result(payload) == payload

    def test_branch_over_cap_rejected(self):
        with pytest.raises(ValidationError):
            validate_agent_execution_result({"branch": "b" * 256})

    def test_pr_url_over_cap_rejected(self):
        with pytest.raises(ValidationError):
            validate_agent_execution_result({"pr_url": "https://x/" + "a" * 2048})

    def test_branch_wrong_type_rejected(self):
        with pytest.raises(ValidationError):
            validate_agent_execution_result({"branch": 123})


# ---------------------------------------------------------------------------
# validate_behavioral_rules
# ---------------------------------------------------------------------------


class TestValidateBehavioralRules:
    def test_none_returns_none(self):
        assert validate_behavioral_rules(None) is None

    def test_empty_list(self):
        assert validate_behavioral_rules([]) == []

    def test_valid_string_list(self):
        rules = ["Always respond in JSON", "Never hardcode credentials"]
        assert validate_behavioral_rules(rules) == rules

    def test_rejects_non_string_item(self):
        with pytest.raises(TypeError, match="behavioral_rules items must be strings"):
            validate_behavioral_rules(["valid rule", 42])

    def test_rejects_dict_item(self):
        with pytest.raises(TypeError, match="behavioral_rules items must be strings"):
            validate_behavioral_rules([{"rule": "something"}])


# ---------------------------------------------------------------------------
# validate_success_criteria
# ---------------------------------------------------------------------------


class TestValidateSuccessCriteria:
    def test_none_returns_none(self):
        assert validate_success_criteria(None) is None

    def test_empty_list(self):
        assert validate_success_criteria([]) == []

    def test_valid_string_list(self):
        criteria = ["All tests pass", "Code review approved"]
        assert validate_success_criteria(criteria) == criteria

    def test_rejects_non_string_item(self):
        with pytest.raises(TypeError, match="success_criteria items must be strings"):
            validate_success_criteria(["valid", None])

    def test_rejects_int_item(self):
        with pytest.raises(TypeError, match="success_criteria items must be strings"):
            validate_success_criteria([100])


# ---------------------------------------------------------------------------
# validate_git_commits — wired-up validator (existing; verify still works)
# ---------------------------------------------------------------------------


class TestValidateGitCommits:
    """BE-9256: fail-closed on a missing commit title.

    BE-6208a's bare-SHA acceptance is FLIPPED here (contract change, not test
    weakening): a bare SHA silently normalized to an empty-titled entry, and
    every UI surface rendered that as a blank commit title. The validator now
    rejects bare SHAs and requires either a titled dict or a tab-delimited
    porcelain string.
    """

    def test_none_returns_none(self):
        assert validate_git_commits(None) is None

    def test_valid_commits(self):
        commits = [{"sha": "abc123", "message": "Initial commit", "author": "Alice"}]
        out = validate_git_commits(commits)
        assert out[0]["sha"] == "abc123"

    def test_rejects_missing_sha(self):
        with pytest.raises(ValidationError):
            validate_git_commits([{"message": "no sha"}])

    def test_rejects_missing_message(self):
        # Missing message key entirely is treated the same as an empty title.
        with pytest.raises(GitCommitTitleRequiredError):
            validate_git_commits([{"sha": "abc123"}])

    def test_rejects_bare_sha_strings(self):
        # BE-9256 (flips BE-6208a): a bare SHA has no title and is rejected,
        # not silently normalized to {"message": ""}.
        with pytest.raises(GitCommitTitleRequiredError):
            validate_git_commits(["abc123def456"])

    def test_rejects_bare_sha_error_carries_git_command_hint(self):
        with pytest.raises(GitCommitTitleRequiredError) as exc_info:
            validate_git_commits(["abc123def456"])
        assert "git log --format=" in exc_info.value.hint

    def test_rejects_mixed_dicts_and_bare_shas(self):
        # The one bad entry (bare SHA) fails the whole batch closed.
        with pytest.raises(GitCommitTitleRequiredError):
            validate_git_commits([{"sha": "a1", "message": "m"}, "b2"])

    def test_rejects_empty_bare_sha(self):
        with pytest.raises(ValueError):
            validate_git_commits(["   "])

    def test_rejects_dict_with_empty_message(self):
        with pytest.raises(GitCommitTitleRequiredError):
            validate_git_commits([{"sha": "abc123", "message": "   "}])

    def test_rejects_non_str_non_dict_entry(self):
        with pytest.raises(TypeError):
            validate_git_commits([123])

    def test_accepts_titled_porcelain_string(self):
        # The output of: git log --format='%H%x09%s%x09%an' -1
        out = validate_git_commits(["abc123\tFix the widget\tAlice"])
        assert out == [
            {
                "sha": "abc123",
                "message": "Fix the widget",
                "author": "Alice",
                "date": None,
                "files_changed": 0,
                "lines_added": 0,
                "pr_url": None,
            }
        ]

    def test_accepts_porcelain_string_without_author(self):
        out = validate_git_commits(["abc123\tFix the widget"])
        assert out[0]["sha"] == "abc123"
        assert out[0]["message"] == "Fix the widget"
        assert out[0]["author"] is None

    def test_rejects_porcelain_string_with_empty_subject(self):
        with pytest.raises(GitCommitTitleRequiredError):
            validate_git_commits(["abc123\t\tAlice"])

    def test_rejects_leading_tab_empty_sha_segment(self):
        """BE-9256 audit Finding #2: a leading tab (empty sha segment) must be
        REJECTED, not misparsed. Pre-fix, ``.strip()`` ran before the tab-split and
        ate the leading tab, shifting every field left: 'Fix the widget' landed in
        sha and 'Alice' landed in message -- accepted with swapped/wrong data."""
        with pytest.raises(GitCommitTitleRequiredError):
            validate_git_commits(["\tFix the widget\tAlice"])

    def test_rejects_whitespace_only_sha_segment(self):
        """A sha segment that is present but whitespace-only is still empty after
        trim -- must reject, not treat the whitespace as a valid sha."""
        with pytest.raises(GitCommitTitleRequiredError):
            validate_git_commits(["   \tFix the widget\tAlice"])

    def test_accepts_crlf_terminated_porcelain_line(self):
        """A porcelain line terminated with \\r\\n (as raw git log output may be,
        depending on platform/pipe) must still parse correctly -- only the
        trailing newline/CR is stripped, not leading whitespace/tabs."""
        out = validate_git_commits(["abc123\tFix the widget\tAlice\r\n"])
        assert out[0]["sha"] == "abc123"
        assert out[0]["message"] == "Fix the widget"
        assert out[0]["author"] == "Alice"

    def test_pr_url_stored_verbatim(self):
        out = validate_git_commits(
            [{"sha": "abc123", "message": "Fix the widget", "pr_url": "https://example.com/pr/1"}]
        )
        assert out[0]["pr_url"] == "https://example.com/pr/1"

    def test_pr_url_defaults_to_none(self):
        out = validate_git_commits([{"sha": "abc123", "message": "Fix the widget"}])
        assert out[0]["pr_url"] is None

    def test_empty_list_stays_valid(self):
        # Non-git-repo escape hatch: empty list / omission is untouched by BE-9256.
        assert validate_git_commits([]) == []


class TestValidateGitCommitsLengthCaps:
    """BE-9256 audit Finding #3 (advisory): the old bare-SHA path capped sha at
    64 chars; the titled-dict/porcelain shapes introduced by BE-9256 accepted
    unbounded sha/message/author/pr_url. Caps restored: sha<=64, message<=500,
    author<=200, pr_url<=500. Applied once on ``GitCommitEntry`` so BOTH the
    dict shape and the porcelain shape (which also constructs a
    ``GitCommitEntry``) are covered by a single enforcement point."""

    def test_accepts_sha_at_64_chars(self):
        sha = "a" * 64
        out = validate_git_commits([{"sha": sha, "message": "Fix the widget"}])
        assert out[0]["sha"] == sha

    def test_rejects_dict_sha_over_64_chars(self):
        with pytest.raises(ValidationError):
            validate_git_commits([{"sha": "a" * 65, "message": "Fix the widget"}])

    def test_rejects_porcelain_sha_over_64_chars(self):
        with pytest.raises(ValidationError):
            validate_git_commits([f"{'a' * 65}\tFix the widget\tAlice"])

    def test_accepts_message_at_500_chars(self):
        message = "m" * 500
        out = validate_git_commits([{"sha": "abc123", "message": message}])
        assert out[0]["message"] == message

    def test_rejects_dict_message_over_500_chars(self):
        with pytest.raises(ValidationError):
            validate_git_commits([{"sha": "abc123", "message": "m" * 501}])

    def test_rejects_porcelain_message_over_500_chars(self):
        with pytest.raises(ValidationError):
            validate_git_commits([f"abc123\t{'m' * 501}\tAlice"])

    def test_rejects_dict_author_over_200_chars(self):
        with pytest.raises(ValidationError):
            validate_git_commits([{"sha": "abc123", "message": "Fix the widget", "author": "a" * 201}])

    def test_rejects_porcelain_author_over_200_chars(self):
        with pytest.raises(ValidationError):
            validate_git_commits([f"abc123\tFix the widget\t{'a' * 201}"])

    def test_rejects_pr_url_over_500_chars(self):
        with pytest.raises(ValidationError):
            validate_git_commits(
                [{"sha": "abc123", "message": "Fix the widget", "pr_url": "https://example.com/" + "p" * 500}]
            )


# ---------------------------------------------------------------------------
# GitIntegrationSettings — config.yaml -> DB migration validator
# ---------------------------------------------------------------------------


class TestGitIntegrationSettings:
    def test_defaults_produce_disabled_git(self):
        s = GitIntegrationSettings()
        assert s.enabled is False
        assert s.use_in_prompts is False

    def test_valid_full_settings(self):
        s = GitIntegrationSettings(
            enabled=True,
            use_in_prompts=True,
        )
        assert s.enabled is True
        assert s.use_in_prompts is True

    def test_string_for_enabled_is_coerced_by_pydantic(self):
        # Pydantic v2 coerces "true"/"false" strings to bool; that is acceptable behavior.
        # The validator still rejects non-boolean-like strings such as arbitrary words.
        with pytest.raises(ValidationError):
            GitIntegrationSettings(enabled="not_a_bool_at_all_xyz")

    def test_stale_retired_keys_are_tolerated_and_dropped(self):
        # BE-9103/BE-9148: max_commits, include_commit_history and branch_strategy were
        # removed from the schema. Stale keys on an existing row must NOT raise
        # (tolerance) and must be dropped on validation (never read).
        s = GitIntegrationSettings(
            enabled=True, max_commits=50, include_commit_history=False, branch_strategy="develop"
        )
        assert s.enabled is True
        dumped = s.model_dump()
        assert "max_commits" not in dumped
        assert "include_commit_history" not in dumped
        assert "branch_strategy" not in dumped


# ---------------------------------------------------------------------------
# SerenaMcpSettings
# ---------------------------------------------------------------------------


class TestSerenaMcpSettings:
    def test_defaults_to_disabled(self):
        s = SerenaMcpSettings()
        assert s.use_in_prompts is False

    def test_enabled_state(self):
        s = SerenaMcpSettings(use_in_prompts=True)
        assert s.use_in_prompts is True

    def test_non_bool_string_for_use_in_prompts_raises(self):
        # Pydantic v2 coerces "true"/"false" but rejects arbitrary strings.
        with pytest.raises(ValidationError):
            SerenaMcpSettings(use_in_prompts="not_a_boolean_xyz")


# ---------------------------------------------------------------------------
# IntegrationsSettingsData
# ---------------------------------------------------------------------------


class TestIntegrationsSettingsData:
    def test_defaults_produce_valid_structure(self):
        data = IntegrationsSettingsData()
        assert isinstance(data.git_integration, GitIntegrationSettings)
        assert isinstance(data.serena_mcp, SerenaMcpSettings)
        assert data.git_integration.enabled is False

    def test_accepts_nested_git_settings(self):
        data = IntegrationsSettingsData(
            git_integration={"enabled": True, "use_in_prompts": True},
            serena_mcp={"use_in_prompts": True},
        )
        assert data.git_integration.enabled is True
        assert data.git_integration.use_in_prompts is True
        assert data.serena_mcp.use_in_prompts is True

    def test_rejects_invalid_git_integration_type(self):
        with pytest.raises(ValidationError):
            IntegrationsSettingsData(git_integration="not_a_dict")

    def test_stale_nested_retired_keys_are_tolerated(self):
        # BE-9103/BE-9148: stale nested max_commits/include_commit_history/branch_strategy
        # are tolerated (dropped), never rejected.
        data = IntegrationsSettingsData(
            git_integration={"enabled": True, "max_commits": 25, "branch_strategy": "develop"}
        )
        assert data.git_integration.enabled is True
        dumped_git = data.model_dump()["git_integration"]
        assert "max_commits" not in dumped_git
        assert "branch_strategy" not in dumped_git

    def test_model_dump_produces_serializable_dict(self):
        data = IntegrationsSettingsData()
        dumped = data.model_dump()
        assert "git_integration" in dumped
        assert "serena_mcp" in dumped
        assert dumped["git_integration"]["enabled"] is False


# ---------------------------------------------------------------------------
# SecuritySettingsData
# ---------------------------------------------------------------------------


class TestSecuritySettingsData:
    def test_defaults_produce_valid_structure(self):
        data = SecuritySettingsData()
        assert data.cookie_domain_whitelist == []
        assert data.allow_headless_launch is False

    def test_accepts_full_settings(self):
        data = SecuritySettingsData(
            cookie_domain_whitelist=["example.com", "app.example.com"],
            allow_headless_launch=True,
        )
        assert len(data.cookie_domain_whitelist) == 2
        assert data.allow_headless_launch is True

    def test_cookie_domain_whitelist_accepts_empty_list(self):
        data = SecuritySettingsData(cookie_domain_whitelist=[])
        assert data.cookie_domain_whitelist == []

    def test_cookie_domain_whitelist_accepts_multiple_domains(self):
        domains = ["a.com", "b.com", "c.com"]
        data = SecuritySettingsData(cookie_domain_whitelist=domains)
        assert data.cookie_domain_whitelist == domains

    def test_stale_retired_security_keys_are_tolerated_and_dropped(self):
        # BE-9148: ssl_*/rate_limiting were retired. A legacy security row carrying
        # them must NOT raise (tolerance) and must be dropped on validation (never
        # read); the live cookie_domain_whitelist/allow_headless_launch keys survive.
        data = SecuritySettingsData(
            ssl_enabled=True,
            ssl_cert_path="/etc/certs/cert.pem",
            ssl_key_path="/etc/certs/key.pem",
            rate_limiting={"enabled": True, "requests_per_minute": 120},
            cookie_domain_whitelist=["example.com"],
            allow_headless_launch=True,
        )
        dumped = data.model_dump()
        assert dumped["cookie_domain_whitelist"] == ["example.com"]
        assert dumped["allow_headless_launch"] is True
        for retired in ("ssl_enabled", "ssl_cert_path", "ssl_key_path", "rate_limiting"):
            assert retired not in dumped


# ---------------------------------------------------------------------------
# SETTINGS_CATEGORY_VALIDATORS map
# ---------------------------------------------------------------------------


class TestSettingsCategoryValidatorsMap:
    def test_map_contains_expected_categories(self):
        assert "integrations" in SETTINGS_CATEGORY_VALIDATORS
        assert "security" in SETTINGS_CATEGORY_VALIDATORS
        # BE-9148: "runtime" retired.
        assert "runtime" not in SETTINGS_CATEGORY_VALIDATORS

    def test_map_points_to_correct_validators(self):
        assert SETTINGS_CATEGORY_VALIDATORS["integrations"] is IntegrationsSettingsData
        assert SETTINGS_CATEGORY_VALIDATORS["security"] is SecuritySettingsData


# ---------------------------------------------------------------------------
# validate_settings_by_category — routing function
# ---------------------------------------------------------------------------


class TestValidateSettingsByCategory:
    def test_integrations_category_validates_git_structure(self):
        result = validate_settings_by_category(
            "integrations",
            {
                "git_integration": {"enabled": True, "use_in_prompts": True},
                "serena_mcp": {"use_in_prompts": False},
            },
        )
        assert result["git_integration"]["enabled"] is True
        assert result["git_integration"]["use_in_prompts"] is True

    def test_security_category_validates_fields(self):
        result = validate_settings_by_category(
            "security",
            {"cookie_domain_whitelist": ["x.com"], "allow_headless_launch": True},
        )
        assert result["cookie_domain_whitelist"] == ["x.com"]
        assert result["allow_headless_launch"] is True

    def test_security_category_tolerates_retired_ssl_fields(self):
        # BE-9148: legacy ssl_*/rate_limiting keys are tolerated (dropped), never rejected.
        result = validate_settings_by_category(
            "security",
            {"ssl_enabled": True, "ssl_cert_path": "/cert.pem", "cookie_domain_whitelist": ["x.com"]},
        )
        assert result["cookie_domain_whitelist"] == ["x.com"]
        assert "ssl_enabled" not in result
        assert "ssl_cert_path" not in result

    def test_retired_runtime_category_falls_back_to_generic_passthrough(self):
        # BE-9148: "runtime" has no dedicated validator anymore, so it routes through the
        # generic SettingsData (extra="allow") — a stray runtime write is tolerated, not rejected.
        result = validate_settings_by_category(
            "runtime",
            {"agent": {"max_agents": 5}, "session": {"timeout_seconds": 7200}},
        )
        assert result["agent"]["max_agents"] == 5
        assert result["session"]["timeout_seconds"] == 7200

    def test_unknown_category_passes_through_as_generic_settings_data(self):
        result = validate_settings_by_category("general", {"any_key": "any_value"})
        assert result["any_key"] == "any_value"

    def test_integrations_rejects_non_bool_enabled(self):
        with pytest.raises(ValidationError):
            validate_settings_by_category(
                "integrations",
                {"git_integration": {"enabled": "not_a_bool_at_all_xyz"}},
            )

    def test_empty_dict_produces_defaults_for_integrations(self):
        result = validate_settings_by_category("integrations", {})
        assert "git_integration" in result
        assert result["git_integration"]["enabled"] is False

    def test_empty_dict_produces_defaults_for_security(self):
        result = validate_settings_by_category("security", {})
        assert result["cookie_domain_whitelist"] == []
        assert result["allow_headless_launch"] is False
