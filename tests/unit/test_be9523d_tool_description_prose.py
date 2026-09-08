# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9523d -- tool descriptions must state the SHIPPED rule, not the plan.

Each assertion below pins prose to a merged behavior change so the two cannot
silently drift apart again:

- ``create_project`` / ``create_task``: a bare multi-product create is
  refused with ``PRODUCT_AMBIGUOUS`` (``ProductService.resolve_binding_product``,
  ``write=True``) -- the old "falls back to the active product" framing was
  only ever true for a single-product tenant.
- ``launch_implementation``: reachable from any connected MCP client, gated
  on the tenant's Headless toggle -- not "from the CLI" (a real claude.ai
  chat session reached this tool and flagged its own CLI-only framing).
  Crossing the gate does not activate the project (``project_active`` /
  ``next_action`` in the response).
- ``stage_project`` / ``get_implementation_prompt``: the human gate has two doors,
  not one.
- ``start_chain_run``: a headlessly-completed member under
  ``review_policy='per_card'`` auto-satisfies the review gate.
- ``giljo_setup``: states the skills-drift notify-never-auto-install rule in
  its own text, not only in a generated skill file.

Uses the live ``mcp`` instance the same way ``test_be9469_query_description_
truthfulness.py`` does -- this is schema-level prose, not a call/detector path.

Edition Scope: Both.
"""

from __future__ import annotations

from api.endpoints.mcp_sdk_server import mcp


def _tool_by_name(name: str):
    for tool in mcp._tool_manager.list_tools():
        if tool.name == name:
            return tool
    raise AssertionError(f"tool {name!r} is not registered on the live mcp instance")


def _tool_description(tool_name: str) -> str:
    tool = _tool_by_name(tool_name)
    description = getattr(tool, "description", "") or ""
    assert description, f"{tool_name} has no top-level description at all"
    return description


def _param_description(tool_name: str, param_name: str) -> str:
    tool = _tool_by_name(tool_name)
    properties = tool.parameters.get("properties", {}) if isinstance(tool.parameters, dict) else {}
    schema = properties.get(param_name)
    assert schema is not None, f"{tool_name} has no {param_name!r} parameter in its schema"
    description = schema.get("description", "")
    assert description, f"{tool_name}.{param_name} has no description at all"
    return description


class TestCreateProjectStatesShippedAmbiguityRule:
    """``create_project``'s ``product_id`` param carries no ``Field(description=...)``
    (unlike ``create_task``'s) -- FastMCP's schema exposes no per-arg text for it,
    so the top-level tool description is the ONLY agent-visible surface for this
    rule and is what these assertions pin."""

    def test_mentions_product_ambiguous(self):
        description = _tool_description("create_project")
        assert "PRODUCT_AMBIGUOUS" in description

    def test_does_not_claim_unconditional_active_product_fallback(self):
        """The old claim ('omit it and the project binds to the active
        product') is only true for a single-product tenant -- the description
        must not assert it as the unconditional rule."""
        description = _tool_description("create_project")
        assert "single-product tenant" in description


class TestCreateTaskStatesShippedAmbiguityRule:
    def test_mentions_product_ambiguous(self):
        description = _tool_description("create_task")
        assert "PRODUCT_AMBIGUOUS" in description

    def test_product_id_param_mentions_product_ambiguous(self):
        description = _param_description("create_task", "product_id")
        assert "PRODUCT_AMBIGUOUS" in description


class TestLaunchImplementationDropsCliFraming:
    def test_does_not_frame_as_cli_only(self):
        description = _tool_description("launch_implementation")
        assert "from the CLI" not in description
        assert "headless/CLI operation" not in description

    def test_states_any_mcp_client_admission(self):
        description = _tool_description("launch_implementation")
        assert "any MCP client" in description or "any other connected" in description

    def test_states_tenant_toggle_gating(self):
        description = _tool_description("launch_implementation")
        assert "Headless toggle" in description

    def test_states_launch_does_not_activate(self):
        description = _tool_description("launch_implementation")
        assert "does NOT activate" in description
        assert "project_active" in description


class TestStageAndImplementProjectDescribeBothDoors:
    def test_stage_project_names_launch_implementation_as_a_door(self):
        description = _tool_description("stage_project")
        assert "launch_implementation" in description

    def test_get_implementation_prompt_names_launch_implementation_as_a_door(self):
        """BE-9554 re-based: the tool renamed to get_implementation_prompt (it returns a
        prompt; it does not implement). BE-9523d's guarantee is unchanged -- the reader
        must learn the headless door exists -- so the pin follows the prose to the live
        tool rather than staying on the compat shim, whose description is only a pointer."""
        description = _tool_description("get_implementation_prompt")
        assert "launch_implementation" in description


class TestLinkedRunsTellTheAgentAdvancementIsAutomatic:
    """BE-9523d pinned that start_chain_run's `review_policy` said a headlessly-finished
    member is "auto-marked reviewed", so an agent would not sit waiting on a review step
    nobody was there to click, or reach for a mark_reviewed call it did not need.

    BE-9554 RE-BASED THIS, and the reason is stronger than the original pin. The
    retirement removes BOTH `review_policy` and `mark_reviewed` from the agent surface
    entirely -- there is no longer a review knob to misread or a review call to make
    wrongly, so the confusion the prose defended against is now structurally impossible.
    What still MUST be said is the fact underneath it: advancement is automatic and
    ready_to_advance is how you see it. That moved to link_projects, and this pin moved
    with it."""

    def test_link_projects_says_advancement_is_automatic(self):
        description = _tool_description("link_projects")
        assert "automatic" in description.lower(), (
            "link_projects must tell the agent the next project becomes ready on its own. "
            "Without it an agent drives the run by hand or waits for a signal that never comes."
        )

    def test_link_projects_names_the_field_that_shows_it(self):
        description = _tool_description("link_projects")
        assert "ready_to_advance" in description, (
            "Naming the field is the difference between 'it happens somehow' and a check "
            "the agent can actually make -- get_workflow_status carries it."
        )


class TestGiljoSetupStatesNotifyNeverAutoInstall:
    def test_mentions_skills_version(self):
        description = _tool_description("giljo_setup")
        assert "skills_version" in description

    def test_states_never_without_explicit_ask(self):
        description = _tool_description("giljo_setup")
        assert "NEVER" in description
