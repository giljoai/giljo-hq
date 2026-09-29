# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.tools.project_closeout import close_project_and_update_memory


async def close_project_without_code_changes(
    project_id: str,
    reason: str,
    *,
    tenant_key: str,
    db_manager: DatabaseManager,
    summary: str | None = None,
    key_outcomes: list[str] | None = None,
    decisions_made: list[str] | None = None,
    tags: list[str] | None = None,
    force: bool = False,
    session: AsyncSession | None = None,
    websocket_manager: Any | None = None,
) -> dict[str, Any]:
    if not (reason or "").strip():
        raise ValidationError("reason is required: say why this project has no code changes.")
    return await close_project_and_update_memory(
        project_id=project_id,
        summary=summary or f"Closed with no code changes: {reason.strip()}",
        key_outcomes=key_outcomes or [],
        decisions_made=decisions_made or [],
        tags=tags,
        tenant_key=tenant_key,
        db_manager=db_manager,
        session=session,
        force=force,
        no_code_changes=reason,
        websocket_manager=websocket_manager,
    )
