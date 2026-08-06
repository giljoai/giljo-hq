# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9274: read-only, tenant-scoped credential-status aggregation.

Computes whether the current tenant has durable connection credentials -- a
live API key and/or a live OAuth grant -- purely by querying EXISTING
``api_keys`` / ``oauth_refresh_tokens`` rows. No new table, no migration, no
write path. Backs the Connect surface's "Configured" state so it survives a
page reload instead of resetting to session-only local state.

Both editions share this path: CE tenants simply have zero (or few)
``oauth_refresh_tokens`` rows, which the same query reports honestly as
``has_valid_oauth=False`` -- there is no CE/SaaS branch here.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.repositories.auth_repository import AuthRepository
from giljo_mcp.schemas.responses.auth import CredentialStatusResult
from giljo_mcp.services.oauth_refresh_service import get_oauth_credential_status


_auth_repo = AuthRepository()


async def get_credential_status(session: AsyncSession, tenant_key: str) -> CredentialStatusResult:
    """Aggregate API-key + OAuth credential status for ``tenant_key``.

    ``tenant_key`` MUST come from the authenticated principal -- callers must
    never accept it from request input (see ``api/endpoints/connect.py``).
    """
    has_valid_api_key = await _auth_repo.has_valid_api_key(session, tenant_key)
    has_valid_oauth, has_expired_oauth = await get_oauth_credential_status(session, tenant_key)
    return CredentialStatusResult(
        has_valid_api_key=has_valid_api_key,
        has_valid_oauth=has_valid_oauth,
        has_expired_oauth=has_expired_oauth,
    )
