# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pydantic import BaseModel, ConfigDict, Field


class AuthResult(BaseModel):
    """Authentication result returned by authenticate_user and create_first_admin.

    Contains the authenticated user's profile data and a JWT token for
    session establishment.  Optional fields (email, full_name, is_active,
    created_at, last_login) are populated when the full user profile is
    available (e.g. authenticate_user), but may be omitted in lightweight
    flows.
    """

    user_id: str
    username: str
    token: str
    tenant_key: str
    role: str = "user"
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    is_active: bool = True
    created_at: str | None = None
    last_login: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SetupStateInfo(BaseModel):
    """Setup state information for a tenant.

    Maps directly to the SetupState ORM model fields returned by
    AuthService.check_setup_state().
    """

    first_admin_created: bool = False
    database_initialized: bool = False
    tenant_key: str

    model_config = ConfigDict(from_attributes=True)


class CredentialStatusResult(BaseModel):
    """Durable connection-credential status for the current tenant (FE-9274).

    Computed on the fly from ``api_keys`` + ``oauth_refresh_tokens`` -- no new
    table, no migration. Backs the Connect surface's "Configured" state so it
    survives a page reload instead of resetting to session-only state.

    ``has_expired_oauth`` is true only when >=1 ``oauth_refresh_tokens`` row
    exists for the tenant AND none of them are currently valid (all revoked
    and/or past ``expires_at``) -- distinct from "never connected", which
    reports all three fields false.
    """

    has_valid_api_key: bool
    has_valid_oauth: bool
    has_expired_oauth: bool

    connected_harnesses: dict[str, str] = {}

    model_config = ConfigDict(from_attributes=True)


class ApiKeyInfo(BaseModel):
    """API key summary information (no sensitive data).

    Returned by AuthService.list_api_keys(). Contains only the key
    prefix (never the full key or hash) for display purposes.
    """

    id: str
    name: str
    key_prefix: str
    permissions: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: str | None = None
    last_used: str | None = None
    revoked_at: str | None = None
    expires_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreateResult(BaseModel):
    """Result of creating a new API key.

    Contains the raw API key (shown only once), the key prefix for future
    identification, and the hashed version stored in the database.

    SECURITY: The ``api_key`` field contains the plaintext key and must
    only be returned to the user once at creation time.
    """

    id: str
    name: str
    api_key: str
    key_prefix: str
    key_hash: str
    permissions: list[str] = Field(default_factory=list)
    expires_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class UserInfo(BaseModel):
    """Basic user profile information returned by registration methods.

    Returned by AuthService.register_user(), create_user_in_org(),
    and _register_user_impl(). Does not include sensitive fields
    like password hashes.
    """

    id: str
    username: str
    email: str | None = None
    role: str
    tenant_key: str

    model_config = ConfigDict(from_attributes=True)


SetupState = SetupStateInfo
