# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from pydantic import ValidationError

from giljo_mcp.schemas.jsonb_validators import (
    APIKeyPermissions,
    ContextIndexKeywords,
    NotificationPreferences,
    SetupSelectedTools,
    validate_api_key_permissions,
    validate_context_keywords,
    validate_notification_preferences,
    validate_setup_selected_tools,
    validate_string_list,
)


class TestSetupSelectedTools:

    def test_valid_tool_list(self):
        model = SetupSelectedTools(items=["claude", "codex", "gemini"])
        assert model.items == ["claude", "codex", "gemini"]

    def test_empty_list_valid(self):
        model = SetupSelectedTools(items=[])
        assert model.items == []

    def test_rejects_non_string_items(self):
        with pytest.raises(ValidationError):
            SetupSelectedTools(items=[1, 2, 3])

    def test_rejects_too_many_items(self):
        with pytest.raises(ValidationError):
            SetupSelectedTools(items=[f"tool_{i}" for i in range(51)])

    def test_rejects_item_too_long(self):
        with pytest.raises(ValidationError):
            SetupSelectedTools(items=["x" * 201])

    def test_rejects_non_list_type(self):
        with pytest.raises(ValidationError):
            SetupSelectedTools(items="claude")


class TestValidateSetupSelectedTools:

    def test_none_returns_none(self):
        assert validate_setup_selected_tools(None) is None

    def test_valid_list_returns_list(self):
        result = validate_setup_selected_tools(["claude", "codex"])
        assert result == ["claude", "codex"]

    def test_rejects_invalid_items(self):
        with pytest.raises(ValidationError):
            validate_setup_selected_tools([123])

    def test_empty_list(self):
        result = validate_setup_selected_tools([])
        assert result == []


class TestNotificationPreferences:

    def test_valid_full_data(self):
        model = NotificationPreferences(
            context_tuning_reminder=True,
            tuning_reminder_threshold=10,
        )
        assert model.context_tuning_reminder is True
        assert model.tuning_reminder_threshold == 10

    def test_defaults(self):
        model = NotificationPreferences()
        assert model.context_tuning_reminder is True
        assert model.tuning_reminder_threshold == 10

    def test_threshold_minimum_enforced(self):
        with pytest.raises(ValidationError):
            NotificationPreferences(tuning_reminder_threshold=2)

    def test_threshold_maximum_enforced(self):
        with pytest.raises(ValidationError):
            NotificationPreferences(tuning_reminder_threshold=1001)

    def test_threshold_boundary_values(self):
        NotificationPreferences(tuning_reminder_threshold=3)
        NotificationPreferences(tuning_reminder_threshold=1000)

    def test_rejects_non_bool_reminder(self):
        with pytest.raises(ValidationError):
            NotificationPreferences(context_tuning_reminder="not_a_bool_xyz")

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            NotificationPreferences(unknown_field="value")


class TestValidateNotificationPreferences:

    def test_none_returns_none(self):
        assert validate_notification_preferences(None) is None

    def test_valid_data_returns_dict(self):
        result = validate_notification_preferences({"context_tuning_reminder": False, "tuning_reminder_threshold": 5})
        assert result["context_tuning_reminder"] is False
        assert result["tuning_reminder_threshold"] == 5

    def test_rejects_invalid_threshold(self):
        with pytest.raises(ValidationError):
            validate_notification_preferences({"tuning_reminder_threshold": 0})

    def test_empty_dict_uses_defaults(self):
        result = validate_notification_preferences({})
        assert result["context_tuning_reminder"] is True
        assert result["tuning_reminder_threshold"] == 10


class TestAPIKeyPermissions:

    def test_valid_permissions(self):
        model = APIKeyPermissions(items=["*"])
        assert model.items == ["*"]

    def test_multiple_permissions(self):
        model = APIKeyPermissions(items=["read", "write", "admin"])
        assert len(model.items) == 3

    def test_empty_list_valid(self):
        model = APIKeyPermissions(items=[])
        assert model.items == []

    def test_rejects_non_string_items(self):
        with pytest.raises(ValidationError):
            APIKeyPermissions(items=[True, False])

    def test_rejects_too_many_items(self):
        with pytest.raises(ValidationError):
            APIKeyPermissions(items=[f"perm_{i}" for i in range(51)])

    def test_rejects_item_too_long(self):
        with pytest.raises(ValidationError):
            APIKeyPermissions(items=["x" * 201])


class TestValidateAPIKeyPermissions:

    def test_none_returns_none(self):
        assert validate_api_key_permissions(None) is None

    def test_valid_list(self):
        result = validate_api_key_permissions(["*"])
        assert result == ["*"]

    def test_rejects_invalid(self):
        with pytest.raises(ValidationError):
            validate_api_key_permissions([42])


class TestContextIndexKeywords:

    def test_valid_keywords(self):
        model = ContextIndexKeywords(items=["python", "fastapi", "sqlalchemy"])
        assert len(model.items) == 3

    def test_empty_list_valid(self):
        model = ContextIndexKeywords(items=[])
        assert model.items == []

    def test_rejects_non_string_items(self):
        with pytest.raises(ValidationError):
            ContextIndexKeywords(items=[1, 2, 3])

    def test_rejects_too_many_items(self):
        with pytest.raises(ValidationError):
            ContextIndexKeywords(items=[f"kw_{i}" for i in range(201)])

    def test_rejects_item_too_long(self):
        with pytest.raises(ValidationError):
            ContextIndexKeywords(items=["x" * 501])


class TestValidateContextKeywords:

    def test_none_returns_none(self):
        assert validate_context_keywords(None) is None

    def test_valid_list(self):
        result = validate_context_keywords(["python", "api"])
        assert result == ["python", "api"]

    def test_rejects_invalid(self):
        with pytest.raises(ValidationError):
            validate_context_keywords([None])


class TestValidateStringList:

    def test_none_returns_none(self):
        assert validate_string_list(None, "test_field") is None

    def test_valid_list(self):
        result = validate_string_list(["a", "b", "c"], "test_field")
        assert result == ["a", "b", "c"]

    def test_empty_list(self):
        result = validate_string_list([], "test_field")
        assert result == []

    def test_rejects_non_string_items(self):
        with pytest.raises(TypeError, match="test_field items must be strings"):
            validate_string_list([1, 2], "test_field")

    def test_rejects_too_many_items(self):
        with pytest.raises(ValueError, match="test_field"):
            validate_string_list([f"item_{i}" for i in range(1001)], "test_field", max_items=1000)

    def test_rejects_item_too_long(self):
        with pytest.raises(ValueError, match="test_field"):
            validate_string_list(["x" * 5001], "test_field", max_length=5000)

    def test_custom_limits(self):
        result = validate_string_list(["ok"], "test_field", max_items=1, max_length=10)
        assert result == ["ok"]

    def test_custom_limits_exceeded(self):
        with pytest.raises(ValueError, match="test_field"):
            validate_string_list(["a", "b"], "test_field", max_items=1)


class TestTemplateUpdateAllowlist:

    def test_allowlist_exists(self):
        from giljo_mcp.services.template_service import _ALLOWED_TEMPLATE_UPDATE_FIELDS

        assert isinstance(_ALLOWED_TEMPLATE_UPDATE_FIELDS, (set, frozenset))

    def test_allowlist_contains_expected_fields(self):
        from giljo_mcp.services.template_service import _ALLOWED_TEMPLATE_UPDATE_FIELDS

        expected_fields = {"name", "description", "role", "category", "is_active", "is_default"}
        assert expected_fields.issubset(_ALLOWED_TEMPLATE_UPDATE_FIELDS)

    def test_allowlist_excludes_dangerous_fields(self):
        from giljo_mcp.services.template_service import _ALLOWED_TEMPLATE_UPDATE_FIELDS

        dangerous = {"id", "tenant_key", "created_at", "org_id"}
        assert not dangerous.intersection(_ALLOWED_TEMPLATE_UPDATE_FIELDS)


class TestTaskUpdateAllowlist:

    def test_allowlist_exists(self):
        from giljo_mcp.services.task_service import _ALLOWED_TASK_UPDATE_FIELDS

        assert isinstance(_ALLOWED_TASK_UPDATE_FIELDS, (set, frozenset))

    def test_allowlist_contains_expected_fields(self):
        from giljo_mcp.services.task_service import _ALLOWED_TASK_UPDATE_FIELDS

        expected_fields = {"title", "description", "status", "priority"}
        assert expected_fields.issubset(_ALLOWED_TASK_UPDATE_FIELDS)
        assert "task_type_id" not in _ALLOWED_TASK_UPDATE_FIELDS

    def test_allowlist_excludes_dangerous_fields(self):
        from giljo_mcp.services.task_service import _ALLOWED_TASK_UPDATE_FIELDS

        dangerous = {"id", "tenant_key", "created_at", "org_id", "product_id"}
        assert not dangerous.intersection(_ALLOWED_TASK_UPDATE_FIELDS)
