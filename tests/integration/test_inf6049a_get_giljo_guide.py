# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-6049a -- MCP-boundary test for the new ``get_giljo_guide`` tool.

CLAUDE.md mandates a regression test at the layer the change lives (BE-5042
precedent: a tool can pass every service-layer test yet fail at the FastMCP
@mcp.tool wrapper). ``get_giljo_guide`` is a no-arg static-content tool, so this
drives it through the SDK's in-memory transport and asserts the consolidated
recipe sections actually surface over the wire (not just that a function returns
a string in isolation).
"""

from __future__ import annotations

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

# Importing the transport module registers every @mcp.tool on the shared instance.
from api.endpoints.mcp_sdk_server import mcp


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    assert result.isError is False, f"get_giljo_guide errored at the transport boundary: {result}"
    assert result.content, "get_giljo_guide returned no content"
    return json.loads(result.content[0].text)


async def test_get_giljo_guide_is_callable_through_transport():
    """The tool dispatches and returns a JSON dict with a 'guide' string, no args."""
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})

    payload = _payload(result)
    assert isinstance(payload.get("guide"), str)
    assert payload["guide"].strip(), "guide body is empty"


async def test_guide_carries_the_consolidated_recipe_sections():
    """The five judgment-layer sections sourced from the slash bodies must surface."""
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})

    guide = _payload(result)["guide"]
    # (a) project-vs-task routing, (b) chain convention, (c) Edition Scope,
    # (d) read-vs-write + never-tenant_key + active-product, (e) lifecycle.
    assert "create_task" in guide and "create_project" in guide
    assert "TSK" in guide  # task auto-tag advertising preserved from the slash bodies
    assert "suffix" in guide and "series_number" in guide  # chain convention
    assert "Edition Scope" in guide
    assert "tenant_key" in guide  # never-pass rule
    assert "active product" in guide.lower()
    assert "get_context" in guide and "list_projects" in guide and "list_tasks" in guide


async def test_guide_carries_the_agent_message_hub_recipe():
    """BE-6054d: the §8 Agent Message Hub recipe surfaces over the wire, names all 8
    hub tools, and frames every operation as tenant-scoped (no cross-tenant leak)."""
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})

    guide = _payload(result)["guide"]
    assert "Agent Message Hub" in guide
    # All 8 hub tools (BE-6054b) are discoverable from the guide.
    for tool_name in (
        "create_thread",
        "join_thread",
        "post_to_thread",
        "get_my_turn",
        "pass_baton",
        "list_threads",
        "get_thread_history",
        "search_threads",
    ):
        assert tool_name in guide, f"hub tool '{tool_name}' missing from the guide"
    # The shareable chat id + the loop directive (BE-6054c) are taught.
    assert "CHT-" in guide
    assert "loop_directive" in guide
    # Tenant-safe framing: never pass tenant_key; cannot reach another tenant's threads.
    assert "never pass `tenant_key`" in guide
    assert "another tenant" in guide


async def test_guide_is_registered_with_read_scope_and_no_args():
    """Advertised surface: no required args, read scope (visible to read-only callers)."""
    from api.endpoints.mcp_sdk_server import TOOL_SCOPES

    assert TOOL_SCOPES.get("get_giljo_guide") == "mcp:read"
    tool = {t.name: t for t in mcp._tool_manager.list_tools()}["get_giljo_guide"]
    required = (tool.parameters or {}).get("required", []) if isinstance(tool.parameters, dict) else []
    assert required == [], f"get_giljo_guide must take no required args, got {required}"


async def test_guide_closeout_sequence_has_no_redundant_memory_write():
    """BE-6230: the canonical closeout sequence must be complete_job -> write_project_closeout
    (NOT ...-> write_memory_entry -> write_project_closeout). write_project_closeout writes the
    single project_closeout 360 entry itself, so prescribing a separate write_memory_entry in
    the closeout step double-writes the 360. The guide must say so without changing any tool
    contract (write_memory_entry stays for non-closeout records / the conductor series-summary)."""
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})
    guide = _payload(result)["guide"]
    # The canonical sequence no longer chains write_memory_entry before write_project_closeout.
    assert "`write_memory_entry` -> `write_project_closeout`" not in guide
    assert "`complete_job` -> `write_project_closeout`" in guide
    # The redundancy is called out explicitly, and write_memory_entry is preserved for other use.
    low = guide.lower()
    assert "redundant" in low
    assert "series-summary" in low or "series summary" in low


async def test_guide_opens_with_the_current_product_name():
    """BE-9361: the guide greets every connected agent, and it opened with the
    dead pre-rebrand name ("GiljoAI MCP") for months after BE-9275 renamed the
    product to Giljo HQ -- the residual that started this project.

    Pinned to ``branding.PRODUCT_NAME`` rather than to the literal on purpose:
    a future rebrand that flips branding.py but forgets this agent-facing header
    goes RED here, which is the exact regression class BE-9361 exists to close.
    A literal would happily pass while the guide went stale again.
    """
    from giljo_mcp.branding import PRODUCT_NAME

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})

    guide = _payload(result)["guide"]
    first_line = guide.lstrip().splitlines()[0]
    assert PRODUCT_NAME in first_line, (
        f"guide header must name the current product ({PRODUCT_NAME!r}), got {first_line!r}"
    )
    # The dead name must not survive anywhere in the agent-facing body. The
    # house brand on its own ("the GiljoAI dashboard") is correct and stays.
    assert "GiljoAI MCP" not in guide, "guide still carries the pre-rebrand product name"


async def test_guide_carries_verbatim_artifact_principle():
    """BE-6207: the guide states the server-authored-artifact = verbatim discipline
    (the durable principle that reinforces the inline chain STEP A spawn directive)."""
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})
    guide = _payload(result)["guide"].lower()
    assert "verbatim" in guide, "guide must carry the verbatim-artifact principle"
    assert "-argumentlist" in guide or "array form" in guide, "principle should name the reformat footgun"
