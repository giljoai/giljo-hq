# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.template_validation import (
    get_role_color,
    slugify_name,
)


class TestSlugifyName:

    def test_role_only(self):
        assert slugify_name("orchestrator") == "orchestrator"

    def test_role_with_suffix(self):
        assert slugify_name("orchestrator", "AmazingGuy") == "orchestrator-amazingguy"

    def test_spaces_in_suffix(self):
        assert slugify_name("tester", "Fast Runner") == "tester-fast-runner"

    def test_underscores_in_suffix(self):
        assert slugify_name("implementer", "API_Handler") == "implementer-api-handler"

    def test_special_chars_removed(self):
        assert slugify_name("analyzer", "Code@Guru!") == "analyzer-codeguru"

    def test_empty_suffix(self):
        assert slugify_name("reviewer", "") == "reviewer"

    def test_none_suffix(self):
        assert slugify_name("documenter", None) == "documenter"

    def test_multiple_spaces_consolidated(self):
        result = slugify_name("tester", "Super  Fast   Runner")
        assert result == "tester-super-fast-runner"

    def test_mixed_case_suffix(self):
        assert slugify_name("backend", "APIHandlerV2") == "backend-apihandlerv2"

    def test_suffix_with_numbers(self):
        assert slugify_name("orchestrator", "Version123") == "orchestrator-version123"


class TestGetRoleColor:

    def test_orchestrator_color(self):
        assert get_role_color("orchestrator") == "#D4A574"

    def test_analyzer_color(self):
        assert get_role_color("analyzer") == "#E74C3C"

    def test_implementer_color(self):
        assert get_role_color("implementer") == "#3498DB"

    def test_tester_color(self):
        assert get_role_color("tester") == "#FFC300"

    def test_reviewer_color(self):
        assert get_role_color("reviewer") == "#9B59B6"

    def test_documenter_color(self):
        assert get_role_color("documenter") == "#27AE60"

    def test_designer_color(self):
        assert get_role_color("designer") == "#9B59B6"

    def test_frontend_color(self):
        assert get_role_color("frontend") == "#3498DB"

    def test_backend_color(self):
        assert get_role_color("backend") == "#2ECC71"

    def test_unknown_role_returns_default(self):
        assert get_role_color("unknown_role") == "#90A4AE"

    def test_empty_role_returns_default(self):
        assert get_role_color("") == "#90A4AE"

    def test_case_sensitive(self):
        assert get_role_color("Orchestrator") == "#90A4AE"

    def test_all_documented_roles(self):
        documented_roles = [
            "orchestrator",
            "analyzer",
            "designer",
            "frontend",
            "backend",
            "implementer",
            "tester",
            "reviewer",
            "documenter",
        ]

        for role in documented_roles:
            color = get_role_color(role)
            assert color.startswith("#")
            assert len(color) == 7
            assert color != "#90A4AE"
