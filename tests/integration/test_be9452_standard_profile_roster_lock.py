# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


_EXPECTED_STANDARD_FROM_CORE = frozenset(
    {
        "health_check",
        "get_giljo_guide",
        "get_context",
        "list_projects",
        "create_project",
        "create_task",
        "update_task",
        "list_tasks",
        "search_memory",
        "get_job_mission",
        "report_progress",
        "complete_job",
        "write_project_closeout",
        "post_to_thread",
    }
)

_EXPECTED_STANDARD_ADDITIONS = frozenset(
    {
        "create_thread",
        "update_thread",
        "join_thread",
        "set_next_actor",
        "get_my_turn",
        "get_participant_liveness",
        "list_threads",
        "get_thread_history",
        "get_roadmap",
        "save_roadmap",
        "get_vision_document",
        "update_product_context",
        "apply_context_tuning",
        "create_product",
        "create_vision_document",
        "diagnose_project_state",
    }
)

_EXPECTED_STANDARD = _EXPECTED_STANDARD_FROM_CORE | _EXPECTED_STANDARD_ADDITIONS

_STANDARD_MUST_EXCLUDE = (
    "stage_project",
    "get_implementation_prompt",
    "launch_implementation",
    "start_chain_run",
    "spawn_job",
    "resume_or_dismiss_job",
    "update_project_mission",
    "update_job_mission",
    "get_staging_instructions",
    "set_agent_status",
    "get_agent_result",
    "get_workflow_status",
    "write_memory_entry",
    "request_approval",
)


class TestStandardProfileRosterLock:

    def test_standard_is_exactly_the_expected_name_list(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

        missing = _EXPECTED_STANDARD - _STANDARD_PROFILE_TOOLS
        unexpected = _STANDARD_PROFILE_TOOLS - _EXPECTED_STANDARD
        assert not missing, f"standard lost expected tools: {sorted(missing)}"
        assert not unexpected, f"standard gained unpinned tools: {sorted(unexpected)}"

    def test_standard_carries_every_core_name_explicitly(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

        for tool in sorted(_EXPECTED_STANDARD_FROM_CORE):
            assert tool in _STANDARD_PROFILE_TOOLS, (
                f"{tool} is pinned in standard but absent -- a core removal narrows standard"
            )

    def test_standard_still_inherits_the_live_core_set(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _STANDARD_PROFILE_TOOLS

        assert _STANDARD_PROFILE_TOOLS == _CORE_PROFILE_TOOLS | _EXPECTED_STANDARD_ADDITIONS

    def test_standard_excludes_the_privilege_tier(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

        for tool in _STANDARD_MUST_EXCLUDE:
            assert tool not in _STANDARD_PROFILE_TOOLS, f"standard must exclude privilege tool {tool}"

    def test_every_standard_name_is_a_registered_tool(self):
        from api.endpoints.mcp_tools._base import TOOL_SCOPES

        registered = set(TOOL_SCOPES)
        assert registered >= _EXPECTED_STANDARD, f"unregistered names pinned: {sorted(_EXPECTED_STANDARD - registered)}"

    def test_standard_is_reachable_through_the_profile_registry(self):
        from api.endpoints.mcp_tools._base import (
            _STANDARD_PROFILE_TOOLS,
            PROFILE_STANDARD,
            TOOL_PROFILES,
        )

        assert TOOL_PROFILES[PROFILE_STANDARD] is _STANDARD_PROFILE_TOOLS

    def test_a_jwt_session_without_mcp_agent_gets_the_locked_standard_set(self):
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        resolved = _profile_toolset_from_state({"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write"]})
        assert resolved == _EXPECTED_STANDARD


class TestStandardRosterLockIsNotVacuous:

    @staticmethod
    def _narrowed(core: frozenset[str], drop: str) -> tuple[frozenset[str], frozenset[str]]:
        narrowed_core = core - {drop}
        return narrowed_core, narrowed_core | _EXPECTED_STANDARD_ADDITIONS

    def test_the_old_subset_rule_accepts_a_narrowed_core(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS

        narrowed_core, narrowed_standard = self._narrowed(_CORE_PROFILE_TOOLS, "list_tasks")

        assert narrowed_core <= narrowed_standard
        assert "list_tasks" not in narrowed_standard

    def test_narrowing_core_is_caught_by_name_and_missed_by_the_subset_rule(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS

        for dropped in sorted(_EXPECTED_STANDARD_FROM_CORE):
            narrowed_core, narrowed_standard = self._narrowed(_CORE_PROFILE_TOOLS, dropped)

            assert narrowed_core <= narrowed_standard, f"subset rule should still hold when dropping {dropped}"
            assert narrowed_standard != _EXPECTED_STANDARD, f"name-list must reject a standard missing {dropped}"
            assert dropped in _EXPECTED_STANDARD - narrowed_standard

    def test_the_name_list_also_catches_a_widening(self):
        widened = _EXPECTED_STANDARD | {"launch_implementation"}
        assert widened != _EXPECTED_STANDARD
        assert len(widened) != len(_EXPECTED_STANDARD)

        swapped = (_EXPECTED_STANDARD - {"list_tasks"}) | {"launch_implementation"}
        assert len(swapped) == len(_EXPECTED_STANDARD)
        assert swapped != _EXPECTED_STANDARD

    def test_the_live_sets_still_carry_the_inherited_name(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _STANDARD_PROFILE_TOOLS

        assert "list_tasks" in _CORE_PROFILE_TOOLS
        assert "list_tasks" in _STANDARD_PROFILE_TOOLS
        assert _STANDARD_PROFILE_TOOLS == _EXPECTED_STANDARD
