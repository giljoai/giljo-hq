# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest

from giljo_mcp.models.templates import AgentTemplate


pytestmark = pytest.mark.asyncio


def _tenant_key(auth_headers: dict) -> str:
    cookie = auth_headers["Cookie"]
    seg = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    payload_b64 = seg.split("=", 1)[1].split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))["tenant_key"]


async def _seed(db_manager, tenant_key: str, **overrides) -> str:
    template_id = str(uuid4())
    row = AgentTemplate(
        id=template_id,
        tenant_key=tenant_key,
        name=overrides.pop("name", f"be9605c-{uuid4().hex[:6]}"),
        category="custom",
        role="implementer",
        system_instructions="## Giljo HQ Agent\nbootstrap text that must NOT ship",
        user_instructions=overrides.pop("user_instructions", "Build the thing carefully."),
        description=overrides.pop("description", "Builds things."),
        model=overrides.pop("model", "claude-opus-5"),
        effort=overrides.pop("effort", "max"),
        behavioral_rules=overrides.pop("behavioral_rules", ["Rule one", "Rule two"]),
        success_criteria=overrides.pop("success_criteria", ["Tests green"]),
        tool="claude",
        cli_tool="claude",
        is_active=True,
    )
    async with db_manager.get_session_async() as session:
        session.add(row)
        await session.commit()
    return template_id


async def test_profile_md_round_trip(api_client, auth_headers, db_manager):
    tenant_key = _tenant_key(auth_headers)
    name = f"Probe Agent {uuid4().hex[:4]}"
    template_id = await _seed(db_manager, tenant_key, name=name)

    resp = await api_client.get(f"/api/v1/templates/{template_id}/profile.md", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/markdown")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;"), disposition
    assert disposition.endswith(('-profile.md"', "-profile.md")), disposition

    body = resp.text
    lines = body.splitlines()
    assert lines[0] == f"# {name}"
    headings = [line for line in lines if line.startswith("## ")]
    assert headings == ["## Description", "## Model / Effort", "## Profile instructions"], headings
    assert "Builds things." in body
    assert "claude-opus-5 / max" in body
    assert "Build the thing carefully." in body
    assert "- Rule one" in body and "- Tests green" in body
    assert "bootstrap text that must NOT ship" not in body
    assert "---\nname:" not in body, "no YAML frontmatter -- harness-neutral"


async def test_profile_md_other_tenant_is_404(api_client, auth_headers, db_manager):
    foreign_id = await _seed(db_manager, f"tk_foreign_{uuid4().hex[:8]}")
    resp = await api_client.get(f"/api/v1/templates/{foreign_id}/profile.md", headers=auth_headers)
    assert resp.status_code == 404, resp.text
    missing = await api_client.get(f"/api/v1/templates/{uuid4()}/profile.md", headers=auth_headers)
    assert missing.status_code == 404
    assert resp.json() == missing.json(), "foreign and missing must be indistinguishable"


async def test_profile_md_requires_auth(api_client, auth_headers, db_manager):
    template_id = await _seed(db_manager, _tenant_key(auth_headers))
    resp = await api_client.get(f"/api/v1/templates/{template_id}/profile.md")
    assert resp.status_code in (401, 403), resp.status_code


async def test_profile_md_uses_the_mission_profile_composer(api_client, auth_headers, db_manager):
    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.services.mission_assembly import compose_agent_profile
    from giljo_mcp.template_renderer import render_profile_markdown

    tenant_key = _tenant_key(auth_headers)
    template_id = await _seed(db_manager, tenant_key, model="  inherit ", effort="inherit")
    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            row = await session.get(AgentTemplate, template_id)
        expected = render_profile_markdown(compose_agent_profile(row))
    resp = await api_client.get(f"/api/v1/templates/{template_id}/profile.md", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.text == expected
    assert "inherit / inherit" in resp.text
