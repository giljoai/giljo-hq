# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.template_seeder import _get_template_metadata


EXPECTED_ROLES = {"orchestrator", "analyzer", "implementer", "tester", "reviewer", "documenter"}


class TestLayer3TemplateSeparation:

    def test_all_standard_roles_present(self):
        templates = _get_template_metadata()
        assert set(templates.keys()) == EXPECTED_ROLES

    def test_metadata_fields_present_for_each_role(self):
        templates = _get_template_metadata()
        required_keys = {"category", "behavioral_rules", "success_criteria", "variables"}

        for role_name, template_def in templates.items():
            assert required_keys.issubset(template_def.keys()), (
                f"{role_name} is missing metadata keys: {required_keys - template_def.keys()}"
            )
            assert template_def["category"] == "role", f"{role_name} should have category 'role'"

    def test_rules_and_criteria_are_empty(self):
        templates = _get_template_metadata()

        for role_name, template_def in templates.items():
            assert template_def["behavioral_rules"] == [], (
                f"{role_name} should have empty behavioral_rules (content is in user_instructions)"
            )
            assert template_def["success_criteria"] == [], (
                f"{role_name} should have empty success_criteria (content is in user_instructions)"
            )

    def test_orchestrator_has_extended_variables(self):
        templates = _get_template_metadata()
        orchestrator = templates["orchestrator"]
        assert "project_mission" in orchestrator["variables"]
        assert "project_name" in orchestrator["variables"]
