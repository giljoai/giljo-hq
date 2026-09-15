# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.services.protocol_builder import _generate_agent_protocol


class TestAgentProtocolFormat:

    def test_protocol_includes_mode_todo(self):
        protocol = _generate_agent_protocol(job_id="test-job-123", tenant_key="tenant-abc", agent_name="test-agent")

        assert "todo_items=" in protocol, "Protocol must instruct agents to use todo_items array in report_progress"
        assert '"content":' in protocol, "Protocol must show todo_items with 'content' field"
        assert '"status":' in protocol, "Protocol must show todo_items with 'status' field"

        assert '"mode": "todo"' not in protocol, "Protocol should NOT use deprecated mode='todo' format"
        assert '"steps_completed"' not in protocol, "Protocol must NOT use old format 'steps_completed'"
        assert '"steps_total"' not in protocol, "Protocol must NOT use old format 'steps_total'"

    def test_protocol_includes_current_step(self):
        protocol = _generate_agent_protocol(job_id="test-job-456", tenant_key="tenant-xyz", agent_name="another-agent")

        assert "todo_items" in protocol, "Protocol should include todo_items array"
        assert '"content"' in protocol, "Protocol should show content field for task descriptions in todo_items"

    def test_protocol_backward_compatibility(self):
        protocol_with_id = _generate_agent_protocol(
            job_id="job-123", tenant_key="tenant-abc", agent_name="agent-1", agent_id="executor-456"
        )

        protocol_without_id = _generate_agent_protocol(job_id="job-123", tenant_key="tenant-abc", agent_name="agent-1")

        assert "todo_items=" in protocol_with_id, "Protocol with agent_id should use todo_items format"
        assert "todo_items=" in protocol_without_id, "Protocol without agent_id should use todo_items format"

    def test_protocol_phase_3_order(self):
        protocol = _generate_agent_protocol(job_id="test-job-789", tenant_key="tenant-def", agent_name="test-agent")

        assert "### Phase 3: PROGRESS REPORTING" in protocol

        phase_3_start = protocol.index("### Phase 3: PROGRESS REPORTING")
        phase_4_start = protocol.index("### Phase 4: COMPLETION")
        phase_3_content = protocol[phase_3_start:phase_4_start]

        assert "report_progress" in phase_3_content, "Phase 3 should show report_progress call"
        assert "todo_items=" in phase_3_content, "Phase 3 should show todo_items parameter"
        assert '"content":' in phase_3_content, "Phase 3 should show content field in todo_items"
        assert '"status":' in phase_3_content, "Phase 3 should show status field in todo_items"

    def test_protocol_distinct_identifiers(self):
        protocol = _generate_agent_protocol(
            job_id="job-123", tenant_key="tenant-abc", agent_name="test-agent", agent_id="executor-456"
        )

        assert "**Your Identifiers:**" in protocol
        identifiers_start = protocol.index("**Your Identifiers:**")
        identifiers_end = protocol.index("**When to Check Messages:**")
        identifiers_section = protocol[identifiers_start:identifiers_end]

        assert "job-123" in identifiers_section, "job_id should be job-123"
        assert "executor-456" in identifiers_section, "agent_id should be executor-456"
        assert identifiers_section.count("job-123") >= 1
        assert identifiers_section.count("executor-456") >= 1

    def test_protocol_get_thread_history_omits_tenant_key(self):
        protocol = _generate_agent_protocol(
            job_id="job-abc", tenant_key="tenant-xyz", agent_name="test-agent", agent_id="executor-def"
        )

        import re

        get_thread_history_calls = re.findall(r"get_thread_history\([^)]+\)", protocol)

        assert len(get_thread_history_calls) >= 4, (
            f"Expected at least 4 get_thread_history examples, found {len(get_thread_history_calls)}"
        )

        for call in get_thread_history_calls:
            if "as_participant=" not in call:
                continue

            assert "tenant_key=" not in call, f"get_thread_history example must omit tenant_key: {call}"

    def test_protocol_includes_todowrite_sync_instructions_for_claude_code(self):
        protocol = _generate_agent_protocol(
            job_id="job-123", tenant_key="tenant-abc", agent_name="test-agent", tool="claude-code"
        )

        assert "TodoWrite" in protocol, "Protocol should mention TodoWrite tool"
        assert "report_progress" in protocol, "Protocol should mention report_progress tool"

        protocol_lower = protocol.lower()
        assert "sync" in protocol_lower or "immediately" in protocol_lower or "every time" in protocol_lower, (
            "Protocol should include instructions to sync TodoWrite status with progress reporting"
        )

        lines = protocol.split("\n")
        todowrite_section_found = False
        for i, line in enumerate(lines):
            if "todowrite" in line.lower() and "sync" in line.lower():
                context = "\n".join(lines[max(0, i - 5) : min(len(lines), i + 15)])
                if "report_progress" in context.lower():
                    todowrite_section_found = True
                    break

        assert todowrite_section_found, "Protocol should have a section explaining TodoWrite sync with report_progress"

    def test_protocol_uses_harness_neutral_phrasing_for_non_claude_tool(self):
        protocol = _generate_agent_protocol(job_id="job-123", tenant_key="tenant-abc", agent_name="test-agent")

        assert "TodoWrite" not in protocol, "Default/non-claude-code render must not leak TodoWrite wording"
        assert "task list" in protocol
        assert "report_progress" in protocol
        protocol_lower = protocol.lower()
        assert "sync" in protocol_lower or "immediately" in protocol_lower or "every time" in protocol_lower


class TestCH2ProgressTracking:

    def test_ch2_includes_progress_tracking_step(self):
        from giljo_mcp.services.protocol_builder import _build_ch2_startup

        ch2 = _build_ch2_startup(orchestrator_id="orch-123", project_id="proj-456")
        assert "STEP 1b" in ch2, "CH2 should contain Step 1b for progress tracking"
        assert "report_progress" in ch2, "Step 1b should reference report_progress"
        assert "PROJECT OUTCOME" in ch2, "Step 1b should scope to project outcomes, not orchestrator actions"
