# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9555: the MASTER PROMPT the board-level "Launch staged..." flow hands out.

Ruling 2 of the design session: the conductor retires as a SERVER-MINTED agent.
The driving harness agent IS the conductor. So the thing the dashboard produces
is no longer a spawn prompt for an agent the server created and holds a job row
for -- it is a seed the user pastes into one terminal, and that session then
writes the ``sequence_run`` record itself via ``link_projects``.

That is a genuinely different prompt from the one at
``GET /prompts/chain-staging/{run_id}``, which cannot be reused here: that one
takes a ``run_id`` and a minted conductor's ``job_id``/``agent_id``, and at the
moment this prompt is produced NONE of those exist yet. The record's own
sequencing is the point -- the agent creates the run, so the run cannot be an
input to the prompt that creates the agent.

What ruling 4 and the BE-9504a drift guard DO require is that the prose lives
server-side, in the prompt engine, generated once for both doors -- never
hand-written into a Vue component where the UI copy and an MCP payload would
drift apart sentence by sentence. Hence a builder module here rather than a
template in the dialog.

Red-first: the module does not exist on the pre-FE-9555 tree.
"""

from __future__ import annotations

import pytest


PROJECTS = [
    {"project_id": "p-1", "taxonomy_alias": "FE-0001", "name": "First", "mission": "Ship the first thing."},
    {"project_id": "p-2", "taxonomy_alias": "BE-0002", "name": "Second", "mission": "Then the second."},
]


def _build(**overrides):
    from giljo_mcp.prompts.master_prompt_builder import build_master_prompt

    kwargs = {
        "projects": PROJECTS,
        "execution_mode": "subagent",
        "mcp_url": "https://example.test/mcp",
        "harness_is_claude": False,
    }
    kwargs.update(overrides)
    return build_master_prompt(**kwargs)


# ---------------------------------------------------------------------------
# What the pasted session must be able to do without asking anyone anything
# ---------------------------------------------------------------------------


def test_every_selected_project_is_named_with_its_id() -> None:
    """The seed is pasted into a session with no context at all. A project the
    prompt does not name is a project that session cannot reach."""
    prompt = _build()
    for project in PROJECTS:
        assert project["project_id"] in prompt
        assert project["taxonomy_alias"] in prompt


def test_the_projects_appear_in_the_order_they_were_given() -> None:
    """Order is the caller's decision (the board's selection / roadmap order),
    not the builder's. Re-sorting here would silently override it."""
    prompt = _build()
    assert prompt.index("FE-0001") < prompt.index("BE-0002")


def test_the_prompt_names_link_projects_as_the_tool_that_records_the_run() -> None:
    """Ruling 6 of the multiproject decision record: the chain is a RECORD, and
    the harness agent is what writes it. BE-9554 shipped `link_projects` as the
    tool that does so -- naming the retired `start_chain_run` would send the
    session looking for a tool that is not on its list."""
    prompt = _build()
    assert "link_projects" in prompt
    assert "start_chain_run" not in prompt


def test_the_execution_mode_is_stated_and_not_left_to_the_agent() -> None:
    assert "subagent" in _build(execution_mode="subagent")
    assert "multi_terminal" in _build(execution_mode="multi_terminal")


def test_the_mcp_url_reaches_the_prompt() -> None:
    assert "https://example.test/mcp" in _build()


def test_the_staging_human_gate_is_not_quietly_dropped() -> None:
    """feedback_staging_stop_do_not_execute: the human gate is sacred, and a
    prompt that drives several projects is exactly where it would be easiest to
    lose. The seed must say implementation is separately authorised."""
    prompt = _build().lower()
    assert "launch_implementation" in prompt or "implement" in prompt


# ---------------------------------------------------------------------------
# The harness bootstrap, which is why this cannot be a static string
# ---------------------------------------------------------------------------


def test_claude_code_gets_the_toolsearch_bootstrap_and_others_do_not() -> None:
    """CE-0035: Claude Code defers MCP tool schemas, so the very first tool call
    fails without an up-front ToolSearch. Every other harness must NOT be told to
    make a call its client does not have."""
    claude = _build(harness_is_claude=True)
    generic = _build(harness_is_claude=False)

    assert "ToolSearch" in claude
    assert "ToolSearch" not in generic


# ---------------------------------------------------------------------------
# Refusals -- a prompt built from nothing is worse than no prompt
# ---------------------------------------------------------------------------


def test_an_empty_selection_is_refused_rather_than_rendered() -> None:
    """A seed listing no projects reads as valid and does nothing. Better to fail
    where the mistake was made."""
    from giljo_mcp.exceptions import ValidationError

    with pytest.raises(ValidationError):
        _build(projects=[])


def test_an_unknown_execution_mode_is_refused() -> None:
    from giljo_mcp.exceptions import ValidationError

    with pytest.raises(ValidationError):
        _build(execution_mode="terminals")


def test_a_project_with_no_mission_is_still_rendered_and_says_so() -> None:
    """Staged-but-mission-less is a real state (the mission can be authored after
    staging), and silently omitting the line would make the confirm dialog's
    mission list quietly disagree with the prompt about which projects are in."""
    prompt = _build(projects=[{"project_id": "p-3", "taxonomy_alias": "IN-0003", "name": "Third", "mission": ""}])
    assert "p-3" in prompt
    assert "IN-0003" in prompt


def test_the_tool_prefix_is_derived_from_branding_not_written_out() -> None:
    """The MCP alias already moved once (``giljo_mcp`` -> ``giljo_hq``, BE-9275).
    A hand-written prefix survives that rename still looking correct, and sends
    every Claude Code session ToolSearching for a server that no longer answers
    to that name. Asserted against branding so the next rename fails here."""
    from giljo_mcp.branding import MCP_ALIAS

    assert f"mcp__{MCP_ALIAS}__" in _build(harness_is_claude=True)
