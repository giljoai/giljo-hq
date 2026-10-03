# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from fastapi import HTTPException, WebSocket, WebSocketException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


async def get_setup_state(db: AsyncSession = None) -> dict[str, Any]:
    if not db:
        return {"database_initialized": False}

    try:
        from sqlalchemy import select

        from giljo_mcp.database import tenant_isolation_bypass
        from giljo_mcp.models import SetupState

        with tenant_isolation_bypass(
            db,
            reason="pre-auth setup-state probe precedes tenant resolution",
            models=(SetupState,),
        ):
            stmt_default = select(SetupState).where(SetupState.tenant_key == "default")
            result_default = await db.execute(stmt_default)
            setup_state = result_default.scalar_one_or_none()

            if setup_state is not None:
                return {"database_initialized": bool(getattr(setup_state, "database_initialized", False))}

            stmt_any = select(SetupState.database_initialized).order_by(SetupState.database_initialized.desc()).limit(1)
            result_any = await db.execute(stmt_any)
            any_flag = result_any.scalar_one_or_none()
        if any_flag is not None:
            return {"database_initialized": bool(any_flag)}

        logger.warning("[WS SETUP DEBUG] No SetupState rows found; treating database as initialized")
        return {"database_initialized": True}

    except (SQLAlchemyError, ValueError):
        logger.exception("Failed to get setup state; failing closed (require auth)")
        return {"database_initialized": True}


async def authenticate_websocket(websocket: WebSocket, db: AsyncSession = None) -> dict[str, Any]:
    setup_state = await get_setup_state(db)
    database_initialized = setup_state.get("database_initialized", True)
    logger.info(f"[WS SETUP DEBUG] db={db}, setup_state={setup_state}, database_initialized={database_initialized}")

    if not database_initialized:
        logger.info("WebSocket connection allowed: initial setup mode (database not initialized)")
        return {"authenticated": True, "context": "setup"}

    token = websocket.query_params.get("token")
    api_key = websocket.query_params.get("api_key")

    if not token and not api_key:
        headers = dict(websocket.headers)
        cookie_header = headers.get("cookie", "")

        if cookie_header:
            cookies = {}
            for cookie_str in cookie_header.split(";"):
                cookie_clean = cookie_str.strip()
                if "=" in cookie_clean:
                    key, value = cookie_clean.split("=", 1)
                    cookies[key.strip()] = value.strip()

            token = cookies.get("access_token")
            if token:
                logger.debug("WebSocket: Found JWT token in httpOnly cookie")

    if not token and not api_key:
        headers = dict(websocket.headers)
        auth_header = headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        api_key = headers.get("x-api-key")

    if not token and not api_key:
        logger.warning("WebSocket connection rejected: no credentials provided (post-setup)")
        raise WebSocketException(
            code=1008,
            reason="Authentication required",
        )

    if token:
        validated_user = await validate_jwt_token(token, db)
        if validated_user:
            logger.info(f"WebSocket authenticated via JWT: {validated_user.get('user_id')}")
            return {"authenticated": True, "user": validated_user}

    if api_key:
        validated_key = await validate_api_key(api_key, db)
        if validated_key:
            logger.info("WebSocket authenticated via API key")
            return {
                "authenticated": True,
                "user": {
                    "user_id": validated_key.get("name"),
                    "tenant_key": validated_key["tenant_key"],
                    "permissions": validated_key.get("permissions", ["*"]),
                },
            }

        from api.middleware.auth_rate_limiter import enforce_api_key_auth_failure

        try:
            await enforce_api_key_auth_failure(websocket)
        except HTTPException as rl_exc:
            if rl_exc.status_code == 429:
                logger.warning("WebSocket connection rejected: API-key auth rate-limited")
                raise WebSocketException(code=1008, reason="Too many requests") from rl_exc
            raise

    logger.warning("WebSocket connection rejected: invalid credentials")
    raise WebSocketException(
        code=1008,
        reason="Invalid credentials",
    )


async def validate_jwt_token(token: str, db: AsyncSession = None) -> dict[str, Any] | None:
    if db is not None:
        from giljo_mcp.auth.principal import PrincipalValidationError, validate_principal

        try:
            principal = await validate_principal(db, jwt_token=token)
        except PrincipalValidationError:
            return None
        return {
            "user_id": principal.username,
            "tenant_key": principal.tenant_key,
            "role": principal.role,
            "permissions": ["*"],
        }

    try:
        from giljo_mcp.auth.jwt_manager import JWTManager

        payload = JWTManager.verify_token(token)
        if not payload:
            return None
        if "tenant_key" not in payload:
            logger.warning("JWT rejected: missing tenant_key claim")
            return None
        return {
            "user_id": payload.get("username"),
            "tenant_key": payload["tenant_key"],
            "role": payload.get("role"),
            "permissions": ["*"],
        }
    except (ImportError, ValueError, KeyError):
        logger.exception("JWT validation failed")
        return None


async def validate_api_key(api_key: str, db: AsyncSession = None) -> dict[str, Any] | None:
    if not db:
        logger.warning("API key validation requires database session")
        return None

    try:
        from giljo_mcp.auth.principal import _resolve_api_key

        resolved = await _resolve_api_key(db, api_key)
    except (ImportError, SQLAlchemyError, ValueError):
        logger.exception("API key validation failed")
        return None

    if resolved is None:
        return None
    key, _user = resolved
    return {"name": key.name, "tenant_key": key.tenant_key, "permissions": key.permissions or ["*"]}
