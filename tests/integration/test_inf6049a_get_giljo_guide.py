# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest

from api.endpoints.mcp_sdk_server import mcp
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    assert result.is_error is False, f"get_giljo_guide errored at the transport boundary: {result}"
    assert result.content, "get_giljo_guide returned no content"
    return json.loads(result.content[0].text)


async def test_get_giljo_guide_is_callable_through_transport():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})

    payload = _payload(result)
    assert isinstance(payload.get("guide"), str)
    assert payload["guide"].strip(), "guide body is empty"


async def test_guide_carries_the_consolidated_recipe_sections():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})

    guide = _payload(result)["guide"]
    assert "create_task" in guide and "create_project" in guide
    assert "TSK" in guide
    assert "suffix" in guide and "series_number" in guide
    assert "Edition Scope" in guide
    assert "tenant_key" in guide
    assert "PRODUCT_AMBIGUOUS" in guide
    assert "default product" in guide.lower()
    assert "get_context" in guide and "list_projects" in guide and "list_tasks" in guide


async def test_guide_carries_the_agent_message_hub_recipe():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})

    guide = _payload(result)["guide"]
    assert "Agent Message Hub" in guide
    assert "Nine tools" in guide
    hub_tools = (
        "create_thread",
        "join_thread",
        "post_to_thread",
        "update_thread",
        "get_my_turn",
        "set_next_actor",
        "list_threads",
        "get_thread_history",
        "get_participant_liveness",
    )
    assert len(set(hub_tools)) == len(hub_tools), (
        f"the hub roster repeats a name: {sorted(n for n in hub_tools if hub_tools.count(n) > 1)}. "
        "A duplicate inflates the count this test claims to verify without adding a tool -- "
        "which is exactly how the 'Eleven tools' claim survived BE-9554 (see BE-9565)."
    )
    assert len(hub_tools) == 9, f"expected 9 hub tools, roster lists {len(hub_tools)}"
    for tool_name in hub_tools:
        assert tool_name in guide, f"hub tool '{tool_name}' missing from the guide"
    assert "CHT-" in guide
    assert "loop_directive" in guide
    assert "never pass `tenant_key`" in guide
    assert "another tenant" in guide


async def test_guide_is_registered_with_read_scope_and_no_args():
    from api.endpoints.mcp_sdk_server import TOOL_SCOPES

    assert TOOL_SCOPES.get("get_giljo_guide") == "mcp:read"
    tool = {t.name: t for t in mcp._tool_manager.list_tools()}["get_giljo_guide"]
    required = (tool.parameters or {}).get("required", []) if isinstance(tool.parameters, dict) else []
    assert required == [], f"get_giljo_guide must take no required args, got {required}"


async def test_guide_closeout_sequence_has_no_redundant_memory_write():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})
    guide = _payload(result)["guide"]
    assert "`write_memory_entry` -> `write_project_closeout`" not in guide
    assert "`complete_job` -> `write_project_closeout`" in guide
    low = guide.lower()
    assert "redundant" in low
    assert "series-summary" in low or "series summary" in low


async def test_guide_opens_with_the_current_product_name():
    from giljo_mcp.branding import PRODUCT_NAME

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})

    guide = _payload(result)["guide"]
    first_line = guide.lstrip().splitlines()[0]
    assert PRODUCT_NAME in first_line, (
        f"guide header must name the current product ({PRODUCT_NAME!r}), got {first_line!r}"
    )
    assert "GiljoAI MCP" not in guide, "guide still carries the pre-rebrand product name"


async def test_guide_carries_verbatim_artifact_principle():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})
    guide = _payload(result)["guide"].lower()
    assert "verbatim" in guide, "guide must carry the verbatim-artifact principle"
    assert "-argumentlist" in guide or "array form" in guide, "principle should name the reformat footgun"


@pytest.mark.asyncio
async def test_guide_carries_hub_etiquette_and_status_vocabulary():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})
    guide = _payload(result)["guide"]

    assert "Hub etiquette" in guide
    assert "join_thread" in guide
    for word in ("active", "inactive", "parked", "completed", "cancelled", "superseded"):
        assert word in guide, word
    for word in ("pending", "in_progress", "blocked"):
        assert word in guide, word
    for word in ("open", "resolved", "closed"):
        assert word in guide, word
    assert "Status vocabulary" in guide
