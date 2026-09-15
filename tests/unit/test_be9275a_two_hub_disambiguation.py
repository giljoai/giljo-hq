# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from api.endpoints.mcp_tools._base import mcp
from giljo_mcp import branding


_NON_HUB_TOOLS = ["health_check", "create_task", "update_task", "list_tasks"]


def _registered_tools_by_name() -> dict:
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


def test_the_disambiguation_reaches_the_agent_via_server_instructions():
    instructions = mcp.instructions or ""
    assert branding.TWO_HUB_DISAMBIGUATION in instructions, (
        "The two-hub disambiguation sentence is no longer served at the server level. "
        "BE-9554 removed the per-tool copies ON THE BASIS that this single delivery "
        "carries the guarantee -- if it goes, the guarantee goes with it and the "
        "per-tool copies must come back."
    )


def test_it_is_served_once_not_per_tool():
    tools = _registered_tools_by_name()
    carriers = [name for name, tool in tools.items() if branding.TWO_HUB_DISAMBIGUATION in (tool.description or "")]
    assert not carriers, (
        f"The two-hub sentence is back in {len(carriers)} tool description(s): {sorted(carriers)}. "
        "It is already delivered once via server-level instructions; a per-tool copy is "
        "redundant on every harness we target."
    )


def test_the_non_hub_tools_do_not_talk_about_posting_to_hubs():
    tools = _registered_tools_by_name()
    offenders = [
        name for name in _NON_HUB_TOOLS if name in tools and "which hub" in (tools[name].description or "").lower()
    ]
    assert not offenders, (
        f"{sorted(offenders)} describe hub-posting behaviour but do not post to a hub. "
        "Anthropic's connector checklist rejects descriptions that tell the model to "
        "behave in ways unrelated to the tool's function."
    )
