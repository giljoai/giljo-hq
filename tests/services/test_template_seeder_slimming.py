# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.template_seeder import (
    _get_check_in_protocol_section,
    _get_default_templates_v103,
    _get_mcp_coordination_section,
)


class TestMCPCoordinationSectionSlimming:

    def test_mcp_section_contains_native_tools_guidance(self):
        section = _get_mcp_coordination_section()
        assert "native" in section.lower()
        assert "mcp" in section.lower()
        assert "CORRECT" in section or "correct" in section.lower()
        assert "WRONG" in section or "wrong" in section.lower()

    def test_mcp_section_contains_get_job_mission_reference(self):
        section = _get_mcp_coordination_section()
        assert "get_job_mission" in section

    def test_mcp_section_contains_full_protocol_reference(self):
        section = _get_mcp_coordination_section()
        assert "full_protocol" in section

    def test_mcp_section_references_full_protocol_for_details(self):
        section = _get_mcp_coordination_section()
        assert "full_protocol" in section.lower() or "tool signatures" in section.lower()

    def test_mcp_section_shows_tool_call_example(self):
        section = _get_mcp_coordination_section()
        assert "get_job_mission" in section
        assert "mcp__giljo_mcp__get_job_mission" not in section
        assert "mcp__<server>__<tool>" in section


class TestCheckInProtocolSectionSlimming:

    def test_check_in_section_does_not_contain_detailed_python_code(self):
        section = _get_check_in_protocol_section()

        assert "import time" not in section, "Check-in section should not contain Python import statements"

        assert "while True:" not in section, "Check-in section should not contain Python while loops"

        detailed_loop_indicators = [
            "for attempt in range",
            "for msg in messages",
        ]
        for indicator in detailed_loop_indicators:
            assert indicator not in section, f"Check-in section should not contain '{indicator}'"

    def test_check_in_section_references_full_protocol_for_behavior(self):
        section = _get_check_in_protocol_section()
        assert "full_protocol" in section or len(section) < 500, (
            "Check-in section should either reference full_protocol or be very brief"
        )




class TestDefaultTemplatesSlimming:

    def test_implementer_template_contains_role_guidance(self):
        templates = _get_default_templates_v103()
        implementer = next((t for t in templates if t["role"] == "implementer"), None)
        assert implementer is not None, "Implementer template must exist"

        content = implementer["user_instructions"]
        assert "implement" in content.lower() or "code" in content.lower()

    def test_tester_template_contains_role_guidance(self):
        templates = _get_default_templates_v103()
        tester = next((t for t in templates if t["role"] == "tester"), None)
        assert tester is not None, "Tester template must exist"

        content = tester["user_instructions"]
        assert "test" in content.lower()

    def test_analyzer_template_contains_role_guidance(self):
        templates = _get_default_templates_v103()
        analyzer = next((t for t in templates if t["role"] == "analyzer"), None)
        assert analyzer is not None, "Analyzer template must exist"

        content = analyzer["user_instructions"]
        assert "analy" in content.lower()

    def test_documenter_template_contains_role_guidance(self):
        templates = _get_default_templates_v103()
        documenter = next((t for t in templates if t["role"] == "documenter"), None)
        assert documenter is not None, "Documenter template must exist"

        content = documenter["user_instructions"]
        assert "document" in content.lower()

    def test_templates_do_not_embed_full_lifecycle_phases(self):
        templates = _get_default_templates_v103()

        for template in templates:
            if template["role"] == "orchestrator":
                continue

            content = template["user_instructions"]

            lifecycle_headers = [
                "### Phase 1:",
                "### Phase 2:",
                "### Phase 3:",
                "### Phase 4:",
                "### Phase 5:",
                "### Phase 6:",
            ]
            for header in lifecycle_headers:
                assert header not in content, (
                    f"Template '{template['role']}' should not contain lifecycle header '{header}'"
                )


class TestTeamContextNote:

    def test_mcp_section_mentions_team_info_from_mission(self):
        section = _get_mcp_coordination_section()

        team_related_phrases = [
            "team",
            "mission",
            "full_protocol",
        ]
        has_team_reference = any(phrase in section.lower() for phrase in team_related_phrases)
        assert has_team_reference, "MCP section should reference mission/team context or full_protocol"
