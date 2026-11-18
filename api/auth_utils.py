# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, WebSocket, WebSocketException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.utils.log_sanitizer import sanitize


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


@dataclass(frozen=True)
class WebSocketCredentials:

    token: str | None
    api_key: str | None
    from_cookie: bool


def extract_ws_credentials(websocket: WebSocket) -> WebSocketCredentials | None:
    token = websocket.query_params.get("token")
    api_key = websocket.query_params.get("api_key")
    if token or api_key:
        return WebSocketCredentials(token=token or None, api_key=api_key or None, from_cookie=False)

    headers = dict(websocket.headers)
    for cookie_str in headers.get("cookie", "").split(";"):
        key, sep, value = cookie_str.strip().partition("=")
        if sep and key.strip() == "access_token" and value.strip():
            return WebSocketCredentials(token=value.strip(), api_key=None, from_cookie=True)

    auth_header = headers.get("authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else None
    api_key = headers.get("x-api-key")
    if token or api_key:
        return WebSocketCredentials(token=token or None, api_key=api_key or None, from_cookie=False)
    return None


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_key(origin: str) -> tuple[str, str, int] | None:
    parts = urlsplit(origin.strip().lower())
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    return parts.scheme, parts.hostname, port or _DEFAULT_PORTS[parts.scheme]


def _origin_is_this_host(origin: tuple[str, str, int], host_header: str) -> bool:
    host = urlsplit(f"//{host_header.strip().lower()}")
    try:
        port = host.port
    except ValueError:
        return False
    return host.hostname == origin[1] and origin[2] == (port or _DEFAULT_PORTS[origin[0]])


def registered_middleware_kwargs(app: Any, middleware_cls: type) -> dict[str, Any] | None:
    for middleware in getattr(app, "user_middleware", ()):
        if middleware.cls is middleware_cls:
            return dict(middleware.kwargs)
    return None


def _configured_origins(app: Any) -> set[tuple[str, str, int]]:
    from starlette.middleware.cors import CORSMiddleware

    from giljo_mcp.http.url_resolver import get_public_url

    cors = registered_middleware_kwargs(app, CORSMiddleware) or {}
    candidates = [get_public_url(), *cors.get("allow_origins", ())]
    return {key for key in map(_origin_key, candidates) if key is not None}


def cookie_origin_allowed(websocket: WebSocket) -> bool:
    headers = dict(websocket.headers)
    origin = _origin_key(headers.get("origin", ""))
    if origin is None:
        return False
    if _origin_is_this_host(origin, headers.get("host", "")):
        return True
    return origin in _configured_origins(websocket.scope.get("app"))


async def websocket_setup_mode(db: AsyncSession | None) -> bool:
    setup_state = await get_setup_state(db)
    return not setup_state.get("database_initialized", True)


async def authenticate_websocket(
    websocket: WebSocket, db: AsyncSession = None, *, setup_mode: bool | None = None
) -> dict[str, Any]:
    credentials = extract_ws_credentials(websocket)
    if setup_mode is None:
        setup_mode = await websocket_setup_mode(db)

    if setup_mode:
        logger.info("WebSocket connection allowed: initial setup mode (database not initialized)")
        return {"authenticated": True, "context": "setup"}

    if credentials is None:
        logger.warning("WebSocket connection rejected: no credentials provided (post-setup)")
        raise WebSocketException(
            code=1008,
            reason="Authentication required",
        )

    if credentials.from_cookie and not cookie_origin_allowed(websocket):
        logger.warning(
            "WebSocket connection rejected: cookie handshake from origin %s. A dashboard served from "
            "another address needs it in security.cors.allowed_origins or GILJO_PUBLIC_URL.",
            sanitize(str(websocket.headers.get("origin"))),
        )
        raise WebSocketException(code=1008, reason="Origin not allowed")

    token, api_key, token_from_cookie = credentials.token, credentials.api_key, credentials.from_cookie

    if token:
        validated_user = await validate_jwt_token(token, db)
        if validated_user:
            if token_from_cookie or validated_user.get("terms_version") is not None:
                await _refuse_session_below_terms(validated_user, db)
            logger.info(f"WebSocket authenticated via JWT: {validated_user.get('user_id')}")
            return {"authenticated": True, "user": validated_user, "expires_at": validated_user.get("exp")}

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
                "expires_at": validated_key.get("expires_at"),
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


async def _refuse_session_below_terms(validated_user: dict[str, Any], db: AsyncSession | None) -> None:
    from giljo_mcp.auth.terms_gate import session_terms_version, terms_claim_violation

    terms_version = validated_user.get("terms_version")
    if terms_version is None and db is not None:
        terms_version = await session_terms_version(db, validated_user["tenant_key"])
    if terms_claim_violation(terms_version) is not None:
        logger.info("WebSocket connection rejected: Terms re-acceptance required")
        raise WebSocketException(code=1008, reason="Terms re-acceptance required")


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
            "terms_version": principal.terms_version,
            "exp": principal.exp,
        }

    try:
        from giljo_mcp.auth.jwt_manager import JWTManager

        payload = JWTManager.verify_token(token)
        if not payload or JWTManager.is_resource_token(payload):
            return None
        if "tenant_key" not in payload:
            logger.warning("JWT rejected: missing tenant_key claim")
            return None
        return {
            "user_id": payload.get("username"),
            "tenant_key": payload["tenant_key"],
            "role": payload.get("role"),
            "permissions": ["*"],
            "terms_version": payload["tos"] if isinstance(payload.get("tos"), str) else None,
            "exp": payload.get("exp"),
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
    return {
        "name": key.name,
        "tenant_key": key.tenant_key,
        "permissions": key.permissions or ["*"],
        "expires_at": key.expires_at.timestamp() if key.expires_at else None,
    }
