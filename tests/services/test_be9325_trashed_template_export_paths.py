# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9325 (2/2) -- a trashed agent template must not ship back onto disk.

Companion to ``test_be9325_trashed_template_lifecycle.py`` (spawn resolution,
already fixed). This file covers the export side: soft-delete stamps
``deleted_at`` and deliberately leaves ``is_active`` alone
(``services/template_service.py:720``), so any export query filtering on
``is_active`` alone still matches a TRASHED template and writes it back onto
the user's own disk on every ``giljo_setup`` / download-token export.

Two of the three affected queries live in ``FileStaging``
(``src/giljo_mcp/file_staging.py``):
  * ``stage_agent_templates``  (download-token ZIP path)
  * ``stage_combined_setup``   (the ``giljo_setup`` combined ZIP)

The third (the direct ``/api/download/agent-templates.zip`` endpoint) is
covered separately at the HTTP layer in
``tests/api/test_be9325_trashed_template_download_endpoint.py`` -- it needs
the ``api_client``/``auth_headers`` fixtures that only exist there.

Real-DB tests on purpose -- the defect lives in the WHERE clause, so only
real rows exercise it.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.file_staging import FileStaging
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.template_renderer import _slugify_filename


def _template(tenant_key: str, name: str, *, deleted: bool = False) -> AgentTemplate:
    """A minimally-valid active template row, optionally already trashed.

    ``is_active=True`` on a trashed row is not a contrivance -- it is exactly
    what soft-delete leaves behind, and it is the whole bug.
    """
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        category="custom",
        system_instructions="sys",
        user_instructions="user",
        tool="claude",
        cli_tool="claude",
        is_active=True,
        deleted_at=datetime.now(UTC) if deleted else None,
    )


@pytest.mark.asyncio
async def test_stage_agent_templates_excludes_trashed(db_session, test_tenant_key, tmp_path):
    """The download-token export ZIP (FileStaging.stage_agent_templates) must
    not contain a trashed template's file, and must still contain the live one.
    """
    live = _template(test_tenant_key, f"be9325-live-{uuid4().hex[:8]}")
    trashed = _template(test_tenant_key, f"be9325-trashed-{uuid4().hex[:8]}", deleted=True)
    db_session.add_all([live, trashed])
    await db_session.flush()

    staging = FileStaging(base_path=tmp_path, db_session=db_session)
    staging_dir = tmp_path / test_tenant_key / "token-export"

    zip_path, message = await staging.stage_agent_templates(staging_dir, test_tenant_key, db_session=db_session)

    assert zip_path is not None, message
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())

    live_filename = f"{_slugify_filename(live.name)}.md"
    trashed_filename = f"{_slugify_filename(trashed.name)}.md"

    assert live_filename in names, f"Live template missing from export ZIP. Members: {sorted(names)}"
    assert trashed_filename not in names, (
        "A soft-deleted template shipped back onto the user's own disk via the download-token "
        f"export. The user deleted this agent; members: {sorted(names)}"
    )


@pytest.mark.asyncio
async def test_stage_combined_setup_excludes_trashed(db_session, test_tenant_key, tmp_path):
    """The giljo_setup combined ZIP (FileStaging.stage_combined_setup) must not
    contain a trashed template's file, and must still contain the live one.
    """
    live = _template(test_tenant_key, f"be9325-combo-live-{uuid4().hex[:8]}")
    trashed = _template(test_tenant_key, f"be9325-combo-trashed-{uuid4().hex[:8]}", deleted=True)
    db_session.add_all([live, trashed])
    await db_session.flush()

    staging = FileStaging(base_path=tmp_path, db_session=db_session)
    staging_dir = tmp_path / test_tenant_key / "token-combined"

    zip_path, message = await staging.stage_combined_setup(
        staging_dir, test_tenant_key, db_session=db_session, platform="claude_code"
    )

    assert zip_path is not None, message
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())

    live_entry = f"agents/{_slugify_filename(live.name)}.md"
    trashed_entry = f"agents/{_slugify_filename(trashed.name)}.md"

    assert live_entry in names, f"Live template missing from combined setup ZIP. Members: {sorted(names)}"
    assert trashed_entry not in names, (
        "A soft-deleted template shipped back onto the user's own disk via the giljo_setup "
        f"combined ZIP. The user deleted this agent; members: {sorted(names)}"
    )
