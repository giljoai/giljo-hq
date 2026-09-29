# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter, Depends

from api.endpoints.oauth import AuthorizeRequest, append_query_params, validate_consent_request
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
from giljo_mcp.services.oauth_service import OAuthService


router = APIRouter()

DENY_ERROR_DESCRIPTION = "The user denied the authorization request."


@router.post("/authorize/deny", tags=["oauth"])
async def deny(
    body: AuthorizeRequest,
    current_user: User = Depends(get_current_active_user),
    db=Depends(get_db_session),
):
    """Decline an OAuth authorization request.

    Checks the request the same way as authorization, then returns the
    application's registered redirect URI carrying an ``access_denied`` error
    and the original ``state``, so the application learns the user declined.

    Returns:
        JSON with the redirect_uri to send the user back to.

    Raises:
        HTTPException 400: If the client or redirect URI is not valid. No URI is
            returned in that case.
    """
    await validate_consent_request(OAuthService(db_session=db), body, current_user.tenant_key)

    params = {"error": "access_denied", "error_description": DENY_ERROR_DESCRIPTION}
    if body.state:
        params["state"] = body.state
    return {"redirect_uri": append_query_params(body.redirect_uri, params)}
