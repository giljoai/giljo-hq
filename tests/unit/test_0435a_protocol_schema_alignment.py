# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from api.endpoints.mcp_sdk_server import _PLACEHOLDER_JOB_IDS




class TestEntryTypeAliasNormalization:

    def test_alias_map_normalizes_project_closeout(self):

        aliases = {"project_closeout": "project_completion"}
        valid = {
            "project_completion",
            "handover_closeout",
            "session_handover",
            "baseline",
            "decision",
            "architecture",
            "discovery",
        }

        entry_type = "project_closeout"
        entry_type = aliases.get(entry_type, entry_type)
        assert entry_type == "project_completion"
        assert entry_type in valid

    def test_canonical_values_unchanged(self):
        aliases = {"project_closeout": "project_completion"}
        valid = {
            "project_completion",
            "handover_closeout",
            "session_handover",
            "baseline",
            "decision",
            "architecture",
            "discovery",
        }

        for canonical in valid:
            result = aliases.get(canonical, canonical)
            assert result == canonical
            assert result in valid

    def test_invalid_entry_type_not_aliased(self):
        aliases = {"project_closeout": "project_completion"}
        entry_type = "totally_invalid"
        result = aliases.get(entry_type, entry_type)
        assert result == "totally_invalid"




class TestFetchContextCategoriesCoercion:

    def test_string_coerced_to_list(self):
        categories = "tech_stack"
        if isinstance(categories, str):
            categories = [categories]
        assert categories == ["tech_stack"]

    def test_list_unchanged(self):
        categories = ["tech_stack", "architecture"]
        if isinstance(categories, str):
            categories = [categories]
        assert categories == ["tech_stack", "architecture"]

    def test_none_unchanged(self):
        categories = None
        if isinstance(categories, str):
            categories = [categories]
        assert categories is None




class TestGetAgentMissionPlaceholderGuard:

    @pytest.mark.parametrize(
        "placeholder",
        ["unknown", "none", "null", "", "undefined", "placeholder", "UNKNOWN", "None", " unknown ", "  NULL  "],
    )
    def test_placeholder_detected(self, placeholder):
        assert placeholder.strip().lower() in _PLACEHOLDER_JOB_IDS

    def test_valid_uuid_not_placeholder(self):
        job_id = "61d20bb9-d35e-4d9b-bfb6-9d36e5d5f6e6"
        assert job_id.strip().lower() not in _PLACEHOLDER_JOB_IDS

    def test_placeholder_set_contents(self):
        expected = {"unknown", "none", "null", "", "undefined", "placeholder"}
        assert expected == _PLACEHOLDER_JOB_IDS
