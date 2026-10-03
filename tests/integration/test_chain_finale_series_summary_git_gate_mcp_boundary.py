# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from giljo_mcp.models import Product
from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive
from tests.integration.test_be6081_mcp_boundary_contract import (
    _enable_git_integration,
    _parse_content_dict,
    memory_tool_client,  # noqa: F401 -- pytest fixture
)
from tests.integration.test_be9653_closeout_no_code_changes_mcp_boundary import _seed_uuid_project
from tests.services.test_sec9704a_conductor_chain_finale_memory_entry import (
    _closed_chain,
    _stub_staleness,  # noqa: F401 -- autouse pytest fixture
)


pytestmark = pytest.mark.asyncio


def _series_summary_call(job_id: str) -> str:
    chapter = _build_ch_chain_drive(
        run_id="run-x",
        resolved_order=["head", "p2"],
        current_index=1,
        execution_mode="claude_code_cli",
        conductor_agent_id="cond-1",
        job_id=job_id,
    )
    block = chapter.split("SERIES SUMMARY", 1)[1]
    start = block.index("write_memory_entry(")
    return block[start : block.index(").", start)]


def _args_from_prompt(call: str, project_id: str) -> dict:
    args = {
        "project_id": project_id,
        "author_job_id": re.search(r'author_job_id="([^"]+)"', call).group(1),
        "summary": "Chain run run-x completed: 2 of 2 projects done.",
        "key_outcomes": ["P1 done", "P2 done"],
        "decisions_made": re.search(r'decisions_made=\["([^"]+)"\]', call).group(1).split('", "'),
        "tags": re.search(r'tags=\["([^"]+)"\]', call).group(1).split('", "'),
    }
    declared = re.search(r'no_code_changes="([^"]+)"', call)
    if declared:
        args["no_code_changes"] = declared.group(1)
    return args


async def test_series_summary_as_prompted_is_accepted_with_git_integration_on(memory_tool_client):  # noqa: F811
    client, tenant_key, session = memory_tool_client
    seeded = await _seed_uuid_project(session, tenant_key)
    product = (
        await session.execute(select(Product).where(Product.id == seeded.product_id, Product.tenant_key == tenant_key))
    ).scalar_one()
    (head, _tail), conductor_job_id = await _closed_chain(session, tenant_key, product)
    await _enable_git_integration(session, tenant_key)

    call = _series_summary_call(conductor_job_id)
    async with client() as mcp_session:
        result = await mcp_session.call_tool("write_memory_entry", _args_from_prompt(call, str(head.id)))
    body = _parse_content_dict(result)

    assert not result.is_error, body
    assert body.get("success") is not False, f"the prompted series summary was refused: {body!r}"
    assert body.get("entry_id"), body
    assert "git_warning" not in body, body
