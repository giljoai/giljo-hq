# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from api.middleware.auth_rate_limiter import get_rate_limiter
from api.middleware.auth_rate_limits import limit_for
from giljo_mcp.auth.dependencies import get_db_session


router = APIRouter()


def _revoke_error(description: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "invalid_request", "error_description": description},
    )


_REVOKE_FIELD_MAX_LENGTHS = {
    "token": 4096,
    "token_type_hint": 32,
}


async def _parse_revoke_body(request: Request) -> dict:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_request: malformed JSON body",
            ) from exc
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_request: body must be a JSON object",
            )
        return data

    form = await request.form()
    return dict(form.items())


def _enforce_caps(**fields: str | None) -> None:
    for name, value in fields.items():
        if value is None:
            continue
        cap = _REVOKE_FIELD_MAX_LENGTHS.get(name)
        if cap is not None and len(value) > cap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"invalid_request: {name} exceeds maximum length {cap}",
            )


@router.post("/revoke", tags=["oauth"])
async def revoke(
    request: Request,
    db=Depends(get_db_session),
):
    """RFC 7009 OAuth 2.0 Token Revocation.

    Body (form or JSON): ``token`` (required), ``token_type_hint`` (optional;
    ``access_token`` or ``refresh_token``). The hint is advisory -- on first-
    type miss the service tries the other type.

    Response is ALWAYS 200 OK with empty body except when ``token`` is
    absent (400 invalid_request). Unknown, malformed, foreign, or already-
    revoked tokens still return 200 (RFC 7009 §2.2 -- no token-validity leak).

    Side effects:
      - Access JWT: persists a row in ``oauth_revoked_tokens`` keyed by the
        JWT's ``jti`` claim. The /mcp Bearer middleware rejects revoked
        tokens on the next request.
      - Refresh token: flips ``revoked=true`` on the entire token family
        (RFC 6749 §10.4 / OAuth 2.1 Security BCP).
    """
    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(request, limit=limit_for("oauth_revoke"), window=60, raise_on_limit=True)

    from giljo_mcp.services import oauth_revocation_service as _revoke

    try:
        body = await _parse_revoke_body(request)
        token_value = body.get("token")
        token_type_hint = body.get("token_type_hint")

        if not isinstance(token_value, str):
            return _revoke_error("token is required")
        if token_type_hint is not None and not isinstance(token_type_hint, str):
            token_type_hint = None

        _enforce_caps(token=token_value, token_type_hint=token_type_hint)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "invalid request"
        description = detail.split(": ", 1)[1] if ": " in detail else detail
        return _revoke_error(description)

    await _revoke.revoke_token(
        db,
        token=token_value,
        token_type_hint=token_type_hint,
    )

    return Response(status_code=status.HTTP_200_OK)
