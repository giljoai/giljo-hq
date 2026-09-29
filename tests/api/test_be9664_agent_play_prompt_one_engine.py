# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import update

from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.platform_registry import get_harness
from giljo_mcp.prompts.spawn_prompt import build_agent_prompt


class _Hints:

    def __init__(self, *, cli_tool: str | None, model: str, effort: str) -> None:
        self.cli_tool = cli_tool
        self.model = model
        self.effort = effort


def _extract_tenant_key(auth_headers: dict) -> str:
    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


async def _seed_specialist(
    db_manager,
    tenant_key: str,
    *,
    execution_mode: str = "multi_terminal",
    cli_tool: str = "claude",
    model: str = "inherit",
    effort: str = "inherit",
    launched: bool = True,
) -> dict:
    project_id = str(uuid4())
    agent_id = str(uuid4())
    product_id = str(uuid4())
    job_id = str(uuid4())
    template_id = str(uuid4())
    project_name = f"BE-9664 play prompt project {uuid4().hex[:8]}"
    async with db_manager.get_session_async() as session:
        session.add(
            Product(
                id=product_id,
                tenant_key=tenant_key,
                name=f"BE-9664 product {uuid4().hex[:8]}",
                description="seeded",
                is_active=False,
            )
        )
        session.add(
            Project(
                id=project_id,
                product_id=product_id,
                name=project_name,
                description="one prompt engine",
                mission="one prompt engine",
                status="active",
                tenant_key=tenant_key,
                execution_mode=execution_mode,
                implementation_launched_at=datetime.now(UTC) if launched else None,
            )
        )
        session.add(
            AgentTemplate(
                id=template_id,
                tenant_key=tenant_key,
                name=f"implementer-backend-{uuid4().hex[:8]}",
                role="implementer",
                description="seeded template",
                system_instructions="seeded",
                cli_tool=cli_tool,
                model=model,
                effort=effort,
            )
        )
        session.add(
            AgentJob(
                job_id=job_id,
                tenant_key=tenant_key,
                project_id=project_id,
                job_type="implementer",
                mission="Implement the thing.",
                status="active",
                template_id=template_id,
            )
        )
        session.add(
            AgentExecution(
                agent_id=agent_id,
                job_id=job_id,
                tenant_key=tenant_key,
                agent_name="implementer-backend",
                agent_display_name="implementer",
                status="staged",
            )
        )
        await session.commit()
    return {
        "agent_id": agent_id,
        "job_id": job_id,
        "project_name": project_name,
        "template_id": template_id,
    }


@pytest.mark.asyncio
async def test_play_prompt_does_not_disclose_tenant_key(api_client, auth_headers, db_manager):
    tenant_key = _extract_tenant_key(auth_headers)
    seed = await _seed_specialist(db_manager, tenant_key)

    resp = await api_client.get(f"/api/v1/prompts/agent/{seed['agent_id']}", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    whole_response = json.dumps(body)

    assert tenant_key not in whole_response, (
        "BE-9664: the Play prompt response discloses the caller's tenant_key -- "
        "the tenancy isolation boundary (ADR-009) must never reach agent-facing text"
    )
    assert "tk_" not in whole_response, (
        f"BE-9664: a tenant-key-shaped literal reached the Play prompt response: {whole_response!r}"
    )
    assert "tenant_key" not in whole_response, (
        "BE-9664: the Play prompt still instructs the agent to pass tenant_key, "
        "a parameter the MCP dispatch strips from the schema"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("launched", [False, True], ids=["pre-gate", "post-gate"])
async def test_play_prompt_is_byte_identical_to_the_shared_generator(api_client, auth_headers, db_manager, launched):
    tenant_key = _extract_tenant_key(auth_headers)
    seed = await _seed_specialist(
        db_manager, tenant_key, cli_tool="codex", model="opus", effort="high", launched=launched
    )

    resp = await api_client.get(f"/api/v1/prompts/agent/{seed['agent_id']}", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    expected = build_agent_prompt(
        "implementer-backend",
        "implementer",
        seed["project_name"],
        seed["job_id"],
        _Hints(cli_tool="codex", model="opus", effort="high"),
        multi_terminal=True,
        launched=launched,
    )
    assert resp.json()["prompt"] == expected, (
        "BE-9664: the Play prompt has drifted from the shared generator -- "
        "a hand-built prompt path is forbidden by the one-prompt-engine rule"
    )
    assert "## HARNESS" in expected, "guard the guard: this fixture must exercise the launch block"
    flag = get_harness("codex").autonomy_flag
    assert (flag in expected) is launched, "the autonomy flag is named after the human gate and never before"


@pytest.mark.asyncio
async def test_play_prompt_for_a_subagent_project_carries_no_launch_text(api_client, auth_headers, db_manager):
    tenant_key = _extract_tenant_key(auth_headers)
    seed = await _seed_specialist(db_manager, tenant_key, execution_mode="subagent")

    resp = await api_client.get(f"/api/v1/prompts/agent/{seed['agent_id']}", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    prompt = resp.json()["prompt"]
    assert "## HARNESS" not in prompt, f"subagent mode must not get launch text; got: {prompt!r}"
    assert "## STARTUP (MANDATORY)" in prompt, prompt


@pytest.mark.asyncio
async def test_play_prompt_ignores_a_trashed_template(api_client, auth_headers, db_manager):
    tenant_key = _extract_tenant_key(auth_headers)
    seed = await _seed_specialist(db_manager, tenant_key, cli_tool="codex", model="opus", effort="high")

    async with db_manager.get_session_async() as session:
        session.info["tenant_key"] = tenant_key
        await session.execute(
            update(AgentTemplate)
            .where(AgentTemplate.id == seed["template_id"], AgentTemplate.tenant_key == tenant_key)
            .values(deleted_at=datetime.now(UTC))
        )
        await session.commit()

    resp = await api_client.get(f"/api/v1/prompts/agent/{seed['agent_id']}", headers=auth_headers)

    assert resp.status_code == 200, f"a trashed template must not break the Play prompt: {resp.text}"
    prompt = resp.json()["prompt"]
    assert prompt, "the prompt must still render"
    assert "codex" not in prompt, f"the binned template's harness still reached the prompt: {prompt!r}"
    assert "opus" not in prompt, f"the binned template's model hint still reached the prompt: {prompt!r}"
    assert "Harness: default" in prompt, (
        f"a trashed template must degrade to the default harness, not vanish the block: {prompt!r}"
    )
    assert prompt == build_agent_prompt(
        "implementer-backend",
        "implementer",
        seed["project_name"],
        seed["job_id"],
        None,
        multi_terminal=True,
        launched=True,
    ), "one engine still: the degraded prompt is the generator's no-template output"
