# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import inspect

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.oauth_cimd import is_cimd_client_id, resolve_cimd_client
from giljo_mcp.services.oauth_service import get_client_resolver


router = APIRouter()


async def resolve_client_name(client_id: str, tenant_key: str) -> str | None:
    if is_cimd_client_id(client_id):
        resolved = await resolve_cimd_client(client_id)
    else:
        resolved = get_client_resolver()(client_id, tenant_key)
        if inspect.isawaitable(resolved):
            resolved = await resolved
    return resolved.client_name if resolved is not None else None


class OAuthClientNameResponse(BaseModel):
    """The registered display name of an OAuth client."""

    client_id: str = Field(description="The client identifier that was looked up.")
    client_name: str = Field(description="The name the application registered under.")


@router.get("/authorize/client", response_model=OAuthClientNameResponse, tags=["oauth"])
async def get_authorize_client(
    client_id: str = Query(..., min_length=1, max_length=2048, pattern=r"^[^\x00-\x1f\x7f]+$"),
    current_user: User = Depends(get_current_active_user),
):
    """Look up the registered name of the application asking for consent.

    Lets the consent screen show the app by name instead of its client id.

    Raises:
        HTTPException 404: If no application is registered under ``client_id``.
    """
    name = await resolve_client_name(client_id, current_user.tenant_key)
    if not name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return OAuthClientNameResponse(client_id=client_id, client_name=name)
