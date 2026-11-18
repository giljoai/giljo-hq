# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.services.project_helpers import _build_ws_project_data, defer_tenant_event


async def stamp_review(session: AsyncSession, websocket_manager: Any | None, tenant_key: str, project_id: str) -> bool:
    repo = ProjectRepository()
    if not await repo.stamp_reviewed(session, tenant_key, project_id):
        return False
    project = await repo.get_by_id(session, tenant_key, project_id)
    defer_tenant_event(
        session,
        websocket_manager,
        tenant_key,
        "project_update",
        {"project_id": project_id, "update_type": "reviewed", **_build_ws_project_data(project)},
    )
    return True
