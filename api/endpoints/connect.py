# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Connect surface -- read-only credential-status endpoint (FE-9274).

Backs the "Configured" state on the Connect surface so it survives a page
reload instead of resetting to session-only local state. Computed on the fly
from EXISTING api_keys / oauth_refresh_tokens rows -- no new table, no write
path here.
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
