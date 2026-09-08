# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Connect surface -- read-only credential-status endpoint (FE-9274).

Backs the "Configured" state on the Connect surface so it survives a page
reload instead of resetting to session-only local state. Computed on the fly
from EXISTING api_keys / oauth_refresh_tokens rows -- no new table.

BE-9591: this module gained ONE write -- removing a tool's stored connection.
The read above was always the whole surface, and "Remove tool" used to touch
nothing durable, so a removed tool went green again from history the moment it
was re-added.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
from giljo_mcp.schemas.responses.auth import CredentialStatusResult
from giljo_mcp.services.credential_status_service import get_credential_status


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/credential-status", response_model=CredentialStatusResult, tags=["connect"])
async def get_connect_credential_status(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> CredentialStatusResult:
    """Durable connection-credential status for the Connect surface.

    Read-only, tenant-scoped. ``tenant_key`` is taken from the authenticated
    principal -- never accepted as a request parameter, per ADR-009.
    """
    return await get_credential_status(db, current_user.tenant_key)


@router.delete("/connections/{harness}", tags=["connect"])
async def remove_tool_connection(
    harness: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Forget this tenant's stored connection for one tool (BE-9591).

    Backs "Remove tool". ``connected_harnesses`` -- the only thing the Connect
    card and the setup wizard read -- derives entirely from ``mcp_sessions`` rows,
    so a removal that leaves them behind removes nothing the user can see: add the
    tool back and it reads connected, green, purely from history.

    Tenant-scoped from the authenticated principal, never a request parameter
    (ADR-009). ``harness`` is the resolved token the card is keyed by, and the
    service matches rows by RESOLVING each one's clientInfo rather than string
    matching -- so removing the generic card clears the rows that display on it.

    Idempotent: removing a tool that owns no rows returns ``removed: 0``. The UI
    may fire this for a card that was never connected, and that is the state the
    user asked for, not an error.
    """
    from api.endpoints.mcp_session import MCPSessionManager

    removed = await MCPSessionManager(db).delete_sessions_for_harness(
        tenant_key=current_user.tenant_key, harness=harness
    )
    logger.info("Removed %d stored connection row(s) for harness=%s", removed, harness)
    return {"harness": harness, "removed": removed}
