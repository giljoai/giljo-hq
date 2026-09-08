# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9452 -- a NAME-LIST roster lock on the ``standard`` tool profile.

``standard`` had no roster lock of its own. It is derived -- ``_STANDARD_PROFILE_TOOLS
= _CORE_PROFILE_TOOLS | frozenset({...})`` (``_scopes.py``) -- so every ``core``
member reaches ``standard`` only by inheritance, and the sole assertion guarding the
pair was ``_CORE_PROFILE_TOOLS <= _STANDARD_PROFILE_TOOLS``
(``test_be8003k_tool_profiles.py``).

**A subset assertion cannot see a narrowing.** Drop a name from ``core`` and it
leaves ``standard`` in the same stroke, while ``<=`` still holds -- a smaller set is
still a subset. ``standard`` is the auth-derived default for a JWT/OAuth session
WITHOUT ``mcp:agent`` (``_profile_toolset_from_state``), so that is a live client
tier losing a tool with a green suite: an instrument that agrees with the change it
is supposed to catch.

This module closes that hole the way ``_EXPECTED_CORE`` closes it for ``core`` --
by pinning EXPLICIT MEMBERSHIP by name. Not a subset relation (blind to narrowing)
and not a count (a swap of one name for another keeps the count). Changing the
``standard`` roster must now break a named assertion deliberately.

``test_narrowing_core_is_caught_by_name_and_missed_by_the_subset_rule`` is the
non-vacuity proof: it narrows a COPY of ``core`` and shows this module's rule
rejects the result while the pre-existing ``<=`` rule accepts it. Without that
contrast the lock is an untested guard.

No DB, no mocks, no module-level mutable state -- pure set assertions over imported
frozensets. Parallel-safe. Edition Scope: Both.
"""

from __future__ import annotations


# The exact ``standard`` roster, hardcoded as the NAME-LIST lock. Grouped as
# ``_scopes.py`` composes it so a reader can see which half a name comes from.
#
# Inherited from ``core`` (BE-8003k's 14, incl. BE-9017's ``health_check``). These
# are here BY NAME on purpose: naming them is precisely what makes a ``core``
# removal fail loudly in ``standard`` instead of silently narrowing it.
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

# ``standard``'s own additions -- the mid-tier surface (_scopes.py): the Hub/BBS
# thread suite, roadmap, product-context / vision, and the read-only diagnostic.
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

# The orchestration/lifecycle privilege tools ``standard`` must never carry. The
# first three are the implement-gate trio already pinned for ``core`` + ``standard``
# by BE-8003k DoD #3; the rest are the full-only privilege surface named in
# ``_scopes.py``'s standard block ("spawn/stage/implement/chains/reactivation/
# mission edits"). Kept as an explicit exclusion list so a future widening of
# ``standard`` toward the privilege tier trips a named assertion too -- the
# membership lock above already catches it, and this says WHY it matters.
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
    """Explicit-membership lock on ``standard`` -- the guard the subset rule lacked."""

    def test_standard_is_exactly_the_expected_name_list(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

        missing = _EXPECTED_STANDARD - _STANDARD_PROFILE_TOOLS
        unexpected = _STANDARD_PROFILE_TOOLS - _EXPECTED_STANDARD
        assert not missing, f"standard lost expected tools: {sorted(missing)}"
        assert not unexpected, f"standard gained unpinned tools: {sorted(unexpected)}"

    def test_standard_carries_every_core_name_explicitly(self):
        """The inherited half, asserted by name rather than by ``core <= standard``.

        This is the assertion a ``core`` removal has to get past. The subset rule
        cannot supply it -- see the non-vacuity test below.
        """
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

        for tool in sorted(_EXPECTED_STANDARD_FROM_CORE):
            assert tool in _STANDARD_PROFILE_TOOLS, (
                f"{tool} is pinned in standard but absent -- a core removal narrows standard"
            )

    def test_standard_still_inherits_the_live_core_set(self):
        """Guards the DERIVATION, not just the result.

        If someone rewrites ``standard`` as a hand-written literal that happens to
        match today's names, this fails -- the union with ``core`` is the property
        the name-list above is protecting.
        """
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _STANDARD_PROFILE_TOOLS

        assert _STANDARD_PROFILE_TOOLS == _CORE_PROFILE_TOOLS | _EXPECTED_STANDARD_ADDITIONS

    def test_standard_excludes_the_privilege_tier(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

        for tool in _STANDARD_MUST_EXCLUDE:
            assert tool not in _STANDARD_PROFILE_TOOLS, f"standard must exclude privilege tool {tool}"

    def test_every_standard_name_is_a_registered_tool(self):
        """A pinned name that is not registered would be a dead entry (INF-6111 class)."""
        from api.endpoints.mcp_tools._base import TOOL_SCOPES

        registered = set(TOOL_SCOPES)
        assert registered >= _EXPECTED_STANDARD, f"unregistered names pinned: {sorted(_EXPECTED_STANDARD - registered)}"

    def test_standard_is_reachable_through_the_profile_registry(self):
        """Pin the name->set wiring too, so the lock cannot be bypassed by re-pointing it."""
        from api.endpoints.mcp_tools._base import (
            _STANDARD_PROFILE_TOOLS,
            PROFILE_STANDARD,
            TOOL_PROFILES,
        )

        assert TOOL_PROFILES[PROFILE_STANDARD] is _STANDARD_PROFILE_TOOLS

    def test_a_jwt_session_without_mcp_agent_gets_the_locked_standard_set(self):
        """Why this roster matters: it IS what a real client tier is served.

        ``standard`` is not decorative -- it is the auth-derived default for a
        JWT/OAuth session carrying no ``mcp:agent``. Asserting through the resolver
        ties the roster to the observable rather than to the constant.
        """
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        resolved = _profile_toolset_from_state({"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write"]})
        assert resolved == _EXPECTED_STANDARD


class TestStandardRosterLockIsNotVacuous:
    """The deliverable: this lock catches a narrowing the pre-existing rule misses.

    BE-9452's finding was that ``_CORE_PROFILE_TOOLS <= _STANDARD_PROFILE_TOOLS``
    holds when ``core`` shrinks, so a ``core`` removal silently narrows ``standard``
    with a green suite. These tests reproduce that on COPIES of the real frozensets
    -- nothing in ``_scopes.py`` is mutated, so they are parallel-safe -- and show
    the two rules disagreeing on the same input. That disagreement is the proof the
    new guard is load-bearing.
    """

    @staticmethod
    def _narrowed(core: frozenset[str], drop: str) -> tuple[frozenset[str], frozenset[str]]:
        """Return (narrowed_core, narrowed_standard) for a hypothetical ``core`` removal.

        Mirrors ``_scopes.py``'s derivation exactly: ``standard`` is the union, so
        dropping from ``core`` drops from ``standard``.
        """
        narrowed_core = core - {drop}
        return narrowed_core, narrowed_core | _EXPECTED_STANDARD_ADDITIONS

    def test_the_old_subset_rule_accepts_a_narrowed_core(self):
        """The gap, reproduced: ``<=`` passes on the very change it should catch."""
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS

        narrowed_core, narrowed_standard = self._narrowed(_CORE_PROFILE_TOOLS, "list_tasks")

        # A smaller set is still a subset -- the pre-existing guard is satisfied.
        assert narrowed_core <= narrowed_standard
        # And the tool is genuinely gone from the tier nobody was watching.
        assert "list_tasks" not in narrowed_standard

    def test_narrowing_core_is_caught_by_name_and_missed_by_the_subset_rule(self):
        """The contrast, on one input: name-list REJECTS, subset rule ACCEPTS."""
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS

        for dropped in sorted(_EXPECTED_STANDARD_FROM_CORE):
            narrowed_core, narrowed_standard = self._narrowed(_CORE_PROFILE_TOOLS, dropped)

            # Pre-existing rule: blind to the narrowing.
            assert narrowed_core <= narrowed_standard, f"subset rule should still hold when dropping {dropped}"
            # This module's rule: catches it, for every inherited name, not just one.
            assert narrowed_standard != _EXPECTED_STANDARD, f"name-list must reject a standard missing {dropped}"
            assert dropped in _EXPECTED_STANDARD - narrowed_standard

    def test_the_name_list_also_catches_a_widening(self):
        """A count-based lock would miss a swap; a name-list catches both directions.

        Derived from ``_EXPECTED_STANDARD`` rather than from the live frozenset on
        purpose: this asserts a property OF THE RULE, so it must hold regardless of
        what ``_scopes.py`` currently says. Building it from the live set made it
        fail spuriously under the very mutation exercise it accompanies -- caught by
        running that exercise, and the reason this note is here.
        """
        widened = _EXPECTED_STANDARD | {"launch_implementation"}
        assert widened != _EXPECTED_STANDARD
        assert len(widened) != len(_EXPECTED_STANDARD)

        # The harder case: same SIZE, different membership. Only a name-list sees it.
        swapped = (_EXPECTED_STANDARD - {"list_tasks"}) | {"launch_implementation"}
        assert len(swapped) == len(_EXPECTED_STANDARD)
        assert swapped != _EXPECTED_STANDARD

    def test_the_live_sets_still_carry_the_inherited_name(self):
        """Two jobs: copy-safety for the mutations above, and a third narrowing detector.

        The ``_narrowed`` helper works on copies, so the real frozensets must be
        unchanged after it runs. Asserting that against the live objects also means
        this fails if ``core`` is genuinely narrowed -- deliberate, not a side effect.
        """
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _STANDARD_PROFILE_TOOLS

        assert "list_tasks" in _CORE_PROFILE_TOOLS
        assert "list_tasks" in _STANDARD_PROFILE_TOOLS
        assert _STANDARD_PROFILE_TOOLS == _EXPECTED_STANDARD
