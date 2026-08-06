# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Authentication module for Giljo HQ.

This module provides unified authentication for all deployment contexts:
- JWT token management for web dashboard sessions
- Auth dependencies for FastAPI endpoints
- Production parity: localhost and network clients treated identically
- AuthManager: Main authentication manager

Components:
    - JWTManager: Create and verify JWT tokens
    - get_current_user: FastAPI dependency for authentication
    - require_admin: FastAPI dependency for admin-only endpoints
    - AuthManager: Main auth manager with unified logic
"""

# Import from the auth/ subdirectory modules
# Import AuthManager from the auth manager module
from giljo_mcp.auth_manager import AuthManager

from .dependencies import (
    get_current_active_user,
    get_current_user,
    get_current_user_optional,
    get_db_session,
    require_admin,
)
from .jwt_manager import JWTManager
from .principal import (
    AuthErrorReason,
    Principal,
    PrincipalValidationError,
    validate_principal,
)


__all__ = [
    "AuthErrorReason",
    # Legacy
    "AuthManager",
    # JWT
    "JWTManager",
    # Unified validator (SEC-3004)
    "Principal",
    "PrincipalValidationError",
    # Dependencies
    "get_current_active_user",
    "get_current_user",
    "get_current_user_optional",
    "get_db_session",
    "require_admin",
    "validate_principal",
]
