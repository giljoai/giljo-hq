# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9325 (2/2) -- the authenticated agent-templates.zip download must not
ship a trashed template back onto the user's own disk.

``GET /api/download/agent-templates.zip`` (``api/endpoints/downloads/bundles.py``)
queried ``tenant_key`` + (optionally) ``is_active`` only. Soft-delete stamps
``deleted_at`` and deliberately leaves ``is_active`` alone
(``services/template_service.py:720``), so a trashed template still matched
and was written into the ZIP the user downloads themselves.

HTTP-boundary test on purpose (the failing layer is the endpoint's own query,
not a service): full app via ``api_client`` + a real JWT via ``auth_headers``,
against the real PostgreSQL test DB.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.template_renderer import _slugify_filename


def _extract_tenant_key(auth_headers: dict) -> str:
    """Decode the tenant_key baked into the JWT access_token cookie."""
    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


async def _seed_templates(db_manager, tenant_key: str, live_name: str, trashed_name: str) -> None:
    async with db_manager.get_session_async() as session:
        session.add(
            AgentTemplate(
                id=str(uuid4()),
                tenant_key=tenant_key,
                name=live_name,
                category="custom",
                system_instructions="sys",
                user_instructions="user",
                tool="claude",
                cli_tool="claude",
                is_active=True,
                deleted_at=None,
            )
        )
        session.add(
            AgentTemplate(
                id=str(uuid4()),
                tenant_key=tenant_key,
                name=trashed_name,
                category="custom",
                system_instructions="sys",
                user_instructions="user",
                tool="claude",
                cli_tool="claude",
                is_active=True,  # BE-9325: soft-delete leaves is_active True -- the whole bug.
                deleted_at=datetime.now(UTC),
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_download_agent_templates_zip_excludes_trashed(api_client, auth_headers, db_manager):
    """The authenticated download must contain the live template's file and
    must NOT contain the trashed template's file.
    """
    tenant_key = _extract_tenant_key(auth_headers)
    live_name = f"be9325-dl-live-{uuid4().hex[:8]}"
    trashed_name = f"be9325-dl-trashed-{uuid4().hex[:8]}"
    await _seed_templates(db_manager, tenant_key, live_name, trashed_name)

    resp = await api_client.get("/api/download/agent-templates.zip", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = set(zf.namelist())

    live_filename = f"{_slugify_filename(live_name)}.md"
    trashed_filename = f"{_slugify_filename(trashed_name)}.md"

    assert live_filename in names, f"Live template missing from download ZIP. Members: {sorted(names)}"
    assert trashed_filename not in names, (
        "A soft-deleted template shipped back onto the user's own disk via the authenticated "
        f"agent-templates.zip download. The user deleted this agent; members: {sorted(names)}"
    )
