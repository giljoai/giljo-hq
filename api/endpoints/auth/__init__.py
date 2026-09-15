# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter

from . import api_keys, registration, session, setup
from .api_keys import (
    create_api_key,
    get_active_api_keys,
    list_api_keys,
    revoke_api_key,
)
from .models import (
    APIKeyCreateRequest,
    APIKeyCreateResponse,
    APIKeyResponse,
    APIKeyRevokeResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    RegisterUserRequest,
    RegisterUserResponse,
    SetupStateUpdate,
    UserProfileResponse,
)
from .registration import (
    _first_admin_creation_lock,
    create_first_admin_user,
    get_rate_limiter,
    register_user,
)
from .session import (
    _build_cookie_params,
    get_config,
    get_me,
    login,
    logout,
    refresh_token,
)
from .setup import update_setup_state


router = APIRouter()
router.include_router(session.router)
router.include_router(setup.router)
router.include_router(api_keys.router)
router.include_router(registration.router)


__all__ = [
    "APIKeyCreateRequest",
    "APIKeyCreateResponse",
    "APIKeyResponse",
    "APIKeyRevokeResponse",
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "PasswordChangeRequest",
    "PasswordChangeResponse",
    "RegisterUserRequest",
    "RegisterUserResponse",
    "SetupStateUpdate",
    "UserProfileResponse",
    "_build_cookie_params",
    "_first_admin_creation_lock",
    "create_api_key",
    "create_first_admin_user",
    "get_active_api_keys",
    "get_config",
    "get_me",
    "get_rate_limiter",
    "list_api_keys",
    "login",
    "logout",
    "refresh_token",
    "register_user",
    "revoke_api_key",
    "router",
    "update_setup_state",
]
