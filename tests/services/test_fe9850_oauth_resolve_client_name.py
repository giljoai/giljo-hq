# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from api.endpoints.oauth_client_info import resolve_client_name
from giljo_mcp.services import oauth_service
from giljo_mcp.services.oauth_service import ResolvedClient, get_client_resolver, set_client_resolver


@pytest.fixture
def restore_resolver():
    original = get_client_resolver()
    yield
    set_client_resolver(original)


@pytest.mark.asyncio
async def test_registered_dcr_client_name_comes_from_resolver(restore_resolver):
    async def resolver(client_id, tenant_key):
        return ResolvedClient(
            client_id=client_id,
            client_name="Acme Notes",
            redirect_uris=["https://acme.example/cb"],
            client_secret_hash=None,
        )

    set_client_resolver(resolver)
    assert await resolve_client_name("dcr-abc", "tk") == "Acme Notes"


@pytest.mark.asyncio
async def test_unknown_client_returns_none(restore_resolver):
    set_client_resolver(oauth_service._builtin_single_client_resolver)
    assert await resolve_client_name("nope", "tk") is None
