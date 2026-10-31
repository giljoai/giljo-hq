# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session, require_browser_session
from giljo_mcp.models import User
from giljo_mcp.services import oauth_login_service


router = APIRouter()


class ConnectedAppResponse(BaseModel):
    """One app logged in to the account."""

    id: str = Field(description="Identifier used to log this app out")
    client_id: str = Field(description="OAuth client id; the shared built-in id means the name is not distinctive")
    client_name: str = Field(description="Name the app registered with")
    connected_at: datetime
    last_used_at: datetime | None = None
    last_ip: str | None = Field(default=None, description="Address of the most recent request")
    last_user_agent: str | None = None
    mcp_client_name: str | None = Field(default=None, description="Name the app reported over MCP, when it did")
    mcp_client_version: str | None = None
    last_product_name: str | None = Field(default=None, description="Product the app last worked on")
    recent_ips: list[str] = Field(default_factory=list, description="Newest addresses first, at most ten")


class ConnectedAppsLogoutAllResponse(BaseModel):
    """Result of logging every app out."""

    logged_out: bool = True


@router.get("/connected-apps", response_model=list[ConnectedAppResponse], tags=["auth"])
async def list_connected_apps(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    _browser: None = Depends(require_browser_session),
):
    """List the apps currently logged in to your account, most recently used first."""
    apps = await oauth_login_service.list_connected_apps(
        db, tenant_key=current_user.tenant_key, user_id=str(current_user.id)
    )
    return [ConnectedAppResponse(**vars(app)) for app in apps]


@router.delete("/connected-apps/{login_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
async def log_out_connected_app(
    login_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    _browser: None = Depends(require_browser_session),
):
    """Log one app out of your account. Its next request is refused."""
    await oauth_login_service.log_out_app(
        db, tenant_key=current_user.tenant_key, user_id=str(current_user.id), login_id=login_id
    )


@router.delete("/connected-apps", response_model=ConnectedAppsLogoutAllResponse, tags=["auth"])
async def log_out_all_connected_apps(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    _browser: None = Depends(require_browser_session),
):
    """Log every connected app out of your account."""
    await oauth_login_service.log_out_all_apps(db, tenant_key=current_user.tenant_key, user_id=str(current_user.id))
    return ConnectedAppsLogoutAllResponse()
