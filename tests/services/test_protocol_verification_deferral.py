# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch3_spawning_rules
from giljo_mcp.services.protocol_sections.chapters_startup import _build_ch1_mission


class TestCH1VerificationDeferral:

    def test_ch1_contains_verification_deferral_heading(self):
        result = _build_ch1_mission()
        assert "VERIFICATION AGENT DEFERRAL" in result

    def test_ch1_deferral_mentions_deliverable_agents(self):
        result = _build_ch1_mission()
        assert "implementer" in result
        assert "analyzer" in result
        assert "documenter" in result

    def test_ch1_deferral_mentions_verification_agents(self):
        result = _build_ch1_mission()
        assert "tester" in result
        assert "reviewer" in result

    def test_ch1_deferral_present_for_all_tools(self):
        for tool in ("claude-code", "codex", "gemini", "multi_terminal"):
            result = _build_ch1_mission(tool=tool)
            assert "VERIFICATION AGENT DEFERRAL" in result, f"Missing for tool={tool}"

    def test_ch1_preserves_existing_structure(self):
        result = _build_ch1_mission()
        assert "CH1: YOUR MISSION" in result
        assert "YOUR ROLE: PROJECT STAGING" in result
        assert "PHASE AWARENESS" in result
        assert "CRITICAL DISTINCTION" in result


class TestCH3VerificationDeferral:

    def test_ch3_contains_verification_deferral_heading(self):
        result = _build_ch3_spawning_rules()
        assert "VERIFICATION AGENT DEFERRAL" in result

    def test_ch3_contains_staging_prohibition(self):
        result = _build_ch3_spawning_rules()
        assert "tester/reviewer are NOT spawned in staging" in result

    def test_ch3_contains_implementation_phase_instructions(self):
        result = _build_ch3_spawning_rules()
        assert "get_agent_result" in result
        assert "spawn_job" in result

    def test_ch3_deferral_present_for_all_tools(self):
        for tool in ("claude-code", "codex", "gemini", "multi_terminal"):
            result = _build_ch3_spawning_rules(tool=tool)
            assert "VERIFICATION AGENT DEFERRAL" in result, f"Missing for tool={tool}"

    def test_ch3_preserves_existing_structure(self):
        result = _build_ch3_spawning_rules()
        assert "CH3: AGENT SPAWNING RULES" in result
        assert "PARAMETER REQUIREMENTS" in result
        assert "VALIDATE BEFORE SPAWNING" in result
        assert "Recommended max" in result


class TestPhase2VerificationSpawnAction:

    def _build_protocol(self, **kwargs):
        defaults = {
            "job_id": "test-job-123",
            "tenant_key": "tk_test",
            "executor_id": "exec-456",
            "execution_mode": "claude-code",
        }
        defaults.update(kwargs)
        return _generate_orchestrator_protocol(**defaults)

    def test_phase2_contains_spawn_verification_action(self):
        result = self._build_protocol()
        assert "Spawn verification agent" in result

    def test_phase2_contains_get_agent_result_call(self):
        result = self._build_protocol()
        assert "get_agent_result" in result

    def test_phase2_verification_present_for_all_modes(self):
        for mode in ("claude-code", "codex", "gemini", "multi_terminal"):
            result = self._build_protocol(execution_mode=mode)
            assert "Spawn verification agent" in result, f"Missing for mode={mode}"

    def test_phase2_preserves_existing_actions(self):
        result = self._build_protocol()
        assert "Unblock an agent" in result
        assert "Spawn a replacement agent" in result
        assert "Broadcast to team" in result
        assert "PROGRESS REPORTING" in result
