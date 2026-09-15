# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.oauth_service import (
    ResolvedClient,
    _builtin_single_client_resolver,
    get_client_resolver,
    set_client_resolver,
)
from tests.fixtures.base_fixtures import restored_global_client_resolver


async def _async_resolver(client_id: str, _tenant_key: str) -> ResolvedClient | None:
    return ResolvedClient(
        client_id=client_id,
        client_name="Leaked SaaS Client",
        redirect_uris=None,
        client_secret_hash=None,
    )


def test_the_containment_puts_back_exactly_what_it_found():
    assert get_client_resolver() is _builtin_single_client_resolver, (
        "a prior test leaked a non-builtin resolver into this one"
    )

    with restored_global_client_resolver():
        set_client_resolver(_async_resolver)
        assert get_client_resolver() is _async_resolver, "the leak must be real inside the block"

    assert get_client_resolver() is _builtin_single_client_resolver, (
        "the resolver must not outlive the test that installed it"
    )


def test_a_leaked_async_resolver_would_break_a_synchronous_caller():
    set_client_resolver(_async_resolver)

    result = get_client_resolver()("giljo-mcp-default", "tk_irrelevant")
    try:
        assert not hasattr(result, "client_id"), "an async resolver must not look synchronous"
    finally:
        result.close()
