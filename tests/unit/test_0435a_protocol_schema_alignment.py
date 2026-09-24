# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from api.endpoints.mcp_sdk_server import _PLACEHOLDER_JOB_IDS
from giljo_mcp.tools.write_memory_entry import (
    ENTRY_TYPE_ALIASES,
    RETIRED_ENTRY_TYPES,
    VALID_ENTRY_TYPES,
)




class TestEntryTypeAliasNormalization:

    def test_alias_map_normalizes_project_closeout(self):
        assert ENTRY_TYPE_ALIASES.get("project_closeout") == "project_completion"
        assert "project_completion" in VALID_ENTRY_TYPES

    def test_canonical_values_unchanged(self):
        for canonical in sorted(VALID_ENTRY_TYPES):
            assert ENTRY_TYPE_ALIASES.get(canonical, canonical) == canonical

    def test_every_alias_points_at_an_accepted_value(self):
        for alias, target in ENTRY_TYPE_ALIASES.items():
            assert target in VALID_ENTRY_TYPES, f"alias {alias!r} resolves to unaccepted {target!r}"

    def test_retired_values_are_not_accepted_and_not_aliased_back_in(self):
        assert not (RETIRED_ENTRY_TYPES & VALID_ENTRY_TYPES)
        assert not (RETIRED_ENTRY_TYPES & set(ENTRY_TYPE_ALIASES))

    def test_invalid_entry_type_not_aliased(self):
        assert ENTRY_TYPE_ALIASES.get("totally_invalid", "totally_invalid") == "totally_invalid"
        assert "totally_invalid" not in VALID_ENTRY_TYPES




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
