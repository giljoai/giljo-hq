# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.repositories.auth_repository import AuthRepository
from giljo_mcp.schemas.responses.auth import CredentialStatusResult
from giljo_mcp.services.oauth_refresh_service import get_oauth_credential_status


_auth_repo = AuthRepository()


async def get_credential_status(session: AsyncSession, tenant_key: str) -> CredentialStatusResult:
    has_valid_api_key = await _auth_repo.has_valid_api_key(session, tenant_key)
    has_valid_oauth, has_expired_oauth = await get_oauth_credential_status(session, tenant_key)
    connected_harnesses = await _auth_repo.connected_harnesses(session, tenant_key)
    return CredentialStatusResult(
        has_valid_api_key=has_valid_api_key,
        has_valid_oauth=has_valid_oauth,
        has_expired_oauth=has_expired_oauth,
        connected_harnesses=connected_harnesses,
    )
