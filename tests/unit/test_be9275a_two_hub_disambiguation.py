# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9275a — two-hub disambiguation guidance reaches the agent.

ORIGINAL FORM (BE-9275a): asserted that 12 messaging/task tools each carried
``branding.TWO_HUB_DISAMBIGUATION`` verbatim in their own ``@mcp.tool``
description, so an agent with Giljo AMH (``giljo_amh``) also connected asks the
user which hub before posting.

RE-BASELINED BY BE-9554, KNOWINGLY. The 15 per-tool copies were removed. What was
checked before removing them -- the museum condition, because BE-9275a's decision
is an exhibit, not clutter:

* **BE-9275a's REASON is preserved, not discarded.** The agent must still receive
  the guidance. It does: the identical sentence is served once at the server level
  (``_base.py``'s ``mcp(instructions=...)``), which every MCP client receives at
  initialize. The delivery mechanism changed; the guarantee did not.
* **All three target harnesses were verified to render server ``instructions``**
  before anything was deleted. Claude Code first-hand (it renders in the session's
  own system prompt); opencode in source, because its docs never mention the field
  (``getInstructions()`` at ``packages/opencode/src/mcp/index.ts:399`` and ``:895``,
  consumed in ``session/index.ts`` and ``session/prompt.ts``); Codex per its current
  published docs, whose "keep the first 512 characters self-contained" guidance the
  260-char instructions string sits entirely inside.
* **Four of the twelve were actively wrong to carry it.** ``health_check``,
  ``create_task``, ``update_task`` and ``list_tasks`` do not post to any hub.
  ``create_task``'s description ended "...ask the user which hub to use before
  posting" -- behavioural instruction unrelated to the tool's function, which
  Anthropic's published connector checklist names as a rejection reason.

So this file now pins the INVARIANT BE-9275a cared about (the guidance reaches the
agent, exactly once) instead of the implementation detail it originally happened to
use (twelve copies). If the server-level instructions ever stop carrying it, this
still goes red -- which the old form would NOT have caught.
"""

from api.endpoints.mcp_tools._base import mcp
from giljo_mcp import branding


# The four that never had anything to do with a hub. Named explicitly so a future
# "restore the sentence everywhere" sweep re-reads why these are excluded.
_NON_HUB_TOOLS = ["health_check", "create_task", "update_task", "list_tasks"]


def _registered_tools_by_name() -> dict:
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


def test_the_disambiguation_reaches_the_agent_via_server_instructions():
    """BE-9275a's actual guarantee: an agent with two Giljo hubs connected is told
    to ask which one. Delivered once, at initialize, to every MCP client."""
    instructions = mcp.instructions or ""
    assert branding.TWO_HUB_DISAMBIGUATION in instructions, (
        "The two-hub disambiguation sentence is no longer served at the server level. "
        "BE-9554 removed the per-tool copies ON THE BASIS that this single delivery "
        "carries the guarantee -- if it goes, the guarantee goes with it and the "
        "per-tool copies must come back."
    )


def test_it_is_served_once_not_per_tool():
    """The BE-9554 saving only holds while the sentence stays out of tool descriptions:
    it was 174 chars x 15 tools = 10% of the whole description surface."""
    tools = _registered_tools_by_name()
    carriers = [name for name, tool in tools.items() if branding.TWO_HUB_DISAMBIGUATION in (tool.description or "")]
    assert not carriers, (
        f"The two-hub sentence is back in {len(carriers)} tool description(s): {sorted(carriers)}. "
        "It is already delivered once via server-level instructions; a per-tool copy is "
        "redundant on every harness we target."
    )


def test_the_non_hub_tools_do_not_talk_about_posting_to_hubs():
    """The four that had no business carrying it. Separate from the redundancy argument:
    a task tool instructing an agent about posting is a directory-review rejection risk,
    so this stays true even if the redundancy question is ever revisited."""
    tools = _registered_tools_by_name()
    offenders = [
        name for name in _NON_HUB_TOOLS if name in tools and "which hub" in (tools[name].description or "").lower()
    ]
    assert not offenders, (
        f"{sorted(offenders)} describe hub-posting behaviour but do not post to a hub. "
        "Anthropic's connector checklist rejects descriptions that tell the model to "
        "behave in ways unrelated to the tool's function."
    )
