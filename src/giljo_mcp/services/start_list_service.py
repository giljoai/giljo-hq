# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.platform_registry import get_harness
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.responses.onboarding import (
    ProductExistsRow,
    ProjectBuiltRow,
    ProjectCreatedRow,
    ProjectStagedRow,
    SkillsInstalledRow,
    StartListResult,
    StartListRows,
    ToolConnectedRow,
)
from giljo_mcp.services.credential_status_service import get_credential_status
from giljo_mcp.services.settings_service import TenantSkillsAckService


_product_repo = ProductRepository()
_project_repo = ProjectRepository()

_SURFACE_NAMES = {"claude": "Claude", "chatgpt": "ChatGPT"}


def _known_tool_names(connected_harnesses: dict[str, str], connected_surfaces: list[str]) -> set[str]:
    names = {_SURFACE_NAMES[surface] for surface in connected_surfaces if surface in _SURFACE_NAMES}
    for token in connected_harnesses:
        harness = get_harness(token)
        if harness is not None:
            names.add(harness.display_label)
    return names


async def get_start_list(session: AsyncSession, tenant_key: str) -> StartListResult:
    credentials = await get_credential_status(session, tenant_key)
    live = bool(credentials.connected_harnesses or credentials.connected_surfaces or credentials.has_valid_oauth)

    skills_done = await TenantSkillsAckService(session, tenant_key).get_acknowledged_version() is not None

    tool_done = live or credentials.has_expired_oauth or skills_done
    names = _known_tool_names(credentials.connected_harnesses, credentials.connected_surfaces)

    product_name = await _product_repo.get_start_list_product_name(session, tenant_key)
    facts = await _project_repo.get_start_list_project_facts(session, tenant_key)
    has_project = facts.project_id is not None
    built_and_reviewed = facts.built and facts.reviewed

    rows = StartListRows(
        tool_connected=ToolConnectedRow(
            done=tool_done, live=live, tool_name=next(iter(names)) if len(names) == 1 else None
        ),
        skills_installed=SkillsInstalledRow(done=skills_done),
        product_exists=ProductExistsRow(done=product_name is not None, product_name=product_name),
        project_created=ProjectCreatedRow(
            done=has_project, project_id=facts.project_id, project_name=facts.project_name
        ),
        project_staged=ProjectStagedRow(
            done=facts.staged,
            has_project=has_project,
            mode=facts.staged_mode,
            requested=facts.requested and not facts.staged,
        ),
        project_built=ProjectBuiltRow(
            done=built_and_reviewed,
            in_progress=facts.in_progress,
            awaiting_review=facts.built and not facts.reviewed,
        ),
    )
    done_count = sum((tool_done, skills_done, rows.product_exists.done, has_project, facts.staged, built_and_reviewed))
    return StartListResult(rows=rows, done_count=done_count)
