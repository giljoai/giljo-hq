# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for agent protocol format validation (Handover 0359).

Verifies that _generate_agent_protocol() produces protocol strings
that match the backend's expected progress format.
"""

from giljo_mcp.services.protocol_builder import _generate_agent_protocol


class TestAgentProtocolFormat:
    """Test agent protocol string format matches backend expectations."""

    def test_protocol_includes_mode_todo(self):
        """Verify protocol instructs agents to use todo_items array format (Handover 0392)."""
        # Generate protocol
        protocol = _generate_agent_protocol(job_id="test-job-123", tenant_key="tenant-abc", agent_name="test-agent")

        # Assert protocol contains new todo_items array format (Handover 0392)
        assert "todo_items=" in protocol, "Protocol must instruct agents to use todo_items array in report_progress"
        assert '"content":' in protocol, "Protocol must show todo_items with 'content' field"
        assert '"status":' in protocol, "Protocol must show todo_items with 'status' field"

        # Assert protocol does NOT contain old formats
        assert '"mode": "todo"' not in protocol, "Protocol should NOT use deprecated mode='todo' format"
        assert '"steps_completed"' not in protocol, "Protocol must NOT use old format 'steps_completed'"
        assert '"steps_total"' not in protocol, "Protocol must NOT use old format 'steps_total'"

    def test_protocol_includes_current_step(self):
        """Verify protocol includes todo_items content field for task descriptions (Handover 0392)."""
        protocol = _generate_agent_protocol(job_id="test-job-456", tenant_key="tenant-xyz", agent_name="another-agent")

        # New format uses todo_items array with content field for task descriptions
        assert "todo_items" in protocol, "Protocol should include todo_items array"
        assert '"content"' in protocol, "Protocol should show content field for task descriptions in todo_items"

    def test_protocol_backward_compatibility(self):
        """Verify protocol supports optional agent_id parameter and uses todo_items format."""
        # Test with agent_id provided
        protocol_with_id = _generate_agent_protocol(
            job_id="job-123", tenant_key="tenant-abc", agent_name="agent-1", agent_id="executor-456"
        )

        # Test without agent_id (backwards compat)
        protocol_without_id = _generate_agent_protocol(job_id="job-123", tenant_key="tenant-abc", agent_name="agent-1")

        # Both should contain todo_items array format (Handover 0392)
        assert "todo_items=" in protocol_with_id, "Protocol with agent_id should use todo_items format"
        assert "todo_items=" in protocol_without_id, "Protocol without agent_id should use todo_items format"

    def test_protocol_phase_3_order(self):
        """Verify Phase 3 contains correct progress reporting format with todo_items array (Handover 0392)."""
        protocol = _generate_agent_protocol(job_id="test-job-789", tenant_key="tenant-def", agent_name="test-agent")

        # Find Phase 3 section
        assert "### Phase 3: PROGRESS REPORTING" in protocol

        # Extract Phase 3 content
        phase_3_start = protocol.index("### Phase 3: PROGRESS REPORTING")
        phase_4_start = protocol.index("### Phase 4: COMPLETION")
        phase_3_content = protocol[phase_3_start:phase_4_start]

        # Verify Phase 3 contains report_progress call with todo_items array format
        assert "report_progress" in phase_3_content, "Phase 3 should show report_progress call"
        assert "todo_items=" in phase_3_content, "Phase 3 should show todo_items parameter"
        assert '"content":' in phase_3_content, "Phase 3 should show content field in todo_items"
        assert '"status":' in phase_3_content, "Phase 3 should show status field in todo_items"

    def test_protocol_distinct_identifiers(self):
        """Verify protocol shows different values for job_id and agent_id (Bug 2)."""
        # When agent_id is provided, it should differ from job_id
        protocol = _generate_agent_protocol(
            job_id="job-123", tenant_key="tenant-abc", agent_name="test-agent", agent_id="executor-456"
        )

        # Extract the "Your Identifiers" section
        assert "**Your Identifiers:**" in protocol
        identifiers_start = protocol.index("**Your Identifiers:**")
        identifiers_end = protocol.index("**When to Check Messages:**")
        identifiers_section = protocol[identifiers_start:identifiers_end]

        # Verify job_id and agent_id show different values
        assert "job-123" in identifiers_section, "job_id should be job-123"
        assert "executor-456" in identifiers_section, "agent_id should be executor-456"
        # They should NOT both show the same value
        assert identifiers_section.count("job-123") >= 1
        assert identifiers_section.count("executor-456") >= 1

    def test_protocol_get_thread_history_omits_tenant_key(self):
        """Rendered get_thread_history examples must NOT include tenant_key (audit_vestigial_cleanup).

        The MCP server auto-injects tenant_key from the API key session and strips
        it from the tool schema entirely. Rendered example signatures that pass
        tenant_key=... are an active contradiction with the dispatch contract.

        BE-9012d: retargeted from the retired receive_messages bus call to its Hub
        replacement, get_thread_history (the same tenant_key-omission contract).
        """
        protocol = _generate_agent_protocol(
            job_id="job-abc", tenant_key="tenant-xyz", agent_name="test-agent", agent_id="executor-def"
        )

        # Find all get_thread_history calls in the protocol
        # There should be examples in Phase 1, 2, 3, and 4
        import re

        get_thread_history_calls = re.findall(r"get_thread_history\([^)]+\)", protocol)

        # Verify we found multiple examples
        assert len(get_thread_history_calls) >= 4, (
            f"Expected at least 4 get_thread_history examples, found {len(get_thread_history_calls)}"
        )

        # Verify NONE of them include tenant_key
        for call in get_thread_history_calls:
            # Skip short-form examples that just show the tool name
            if "as_participant=" not in call:
                continue

            assert "tenant_key=" not in call, f"get_thread_history example must omit tenant_key: {call}"

    def test_protocol_includes_todowrite_sync_instructions_for_claude_code(self):
        """Verify the claude-code protocol includes instructions to sync TodoWrite with
        report_progress (Bug 4).

        BE-9260: TodoWrite is a Claude-Code-only tool, so the "sync your task list"
        section now phrases itself per-harness (``task_list_phrase``) instead of
        hardcoding "TodoWrite" for every tool. This test pins the CLAUDE-CODE render
        (the harness Bug 4 was actually about); the harness-neutral case is covered by
        ``test_protocol_uses_harness_neutral_phrasing_for_non_claude_tool`` below."""
        protocol = _generate_agent_protocol(
            job_id="job-123", tenant_key="tenant-abc", agent_name="test-agent", tool="claude-code"
        )

        # Verify protocol mentions syncing TodoWrite with progress reporting
        assert "TodoWrite" in protocol, "Protocol should mention TodoWrite tool"
        assert "report_progress" in protocol, "Protocol should mention report_progress tool"

        # Look for explicit sync instructions (should be near each other)
        # Check for keywords that indicate the sync relationship
        protocol_lower = protocol.lower()
        assert "sync" in protocol_lower or "immediately" in protocol_lower or "every time" in protocol_lower, (
            "Protocol should include instructions to sync TodoWrite status with progress reporting"
        )

        # Verify the sync section mentions both tools together
        # Find sections that mention both TodoWrite and report_progress
        lines = protocol.split("\n")
        todowrite_section_found = False
        for i, line in enumerate(lines):
            if "todowrite" in line.lower() and "sync" in line.lower():
                # Look in surrounding lines for report_progress mention
                context = "\n".join(lines[max(0, i - 5) : min(len(lines), i + 15)])
                if "report_progress" in context.lower():
                    todowrite_section_found = True
                    break

        assert todowrite_section_found, "Protocol should have a section explaining TodoWrite sync with report_progress"

    def test_protocol_uses_harness_neutral_phrasing_for_non_claude_tool(self):
        """BE-9260: a non-claude-code (or default/unspecified) tool must get the
        harness-neutral "task list" phrasing instead of the Claude-Code-only
        TodoWrite tool name, while still carrying the same sync-with-report_progress
        guidance."""
        protocol = _generate_agent_protocol(job_id="job-123", tenant_key="tenant-abc", agent_name="test-agent")

        assert "TodoWrite" not in protocol, "Default/non-claude-code render must not leak TodoWrite wording"
        assert "task list" in protocol
        assert "report_progress" in protocol
        protocol_lower = protocol.lower()
        assert "sync" in protocol_lower or "immediately" in protocol_lower or "every time" in protocol_lower


class TestCH2ProgressTracking:
    """Verify CH2 startup sequence includes progress tracking step."""

    def test_ch2_includes_progress_tracking_step(self):
        """CH2 startup contains Step 1b with report_progress and orchestration scope."""
        from giljo_mcp.services.protocol_builder import _build_ch2_startup

        ch2 = _build_ch2_startup(orchestrator_id="orch-123", project_id="proj-456")
        assert "STEP 1b" in ch2, "CH2 should contain Step 1b for progress tracking"
        assert "report_progress" in ch2, "Step 1b should reference report_progress"
        assert "PROJECT OUTCOME" in ch2, "Step 1b should scope to project outcomes, not orchestrator actions"
