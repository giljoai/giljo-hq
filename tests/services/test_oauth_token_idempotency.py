# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services import cache_backends
from giljo_mcp.services import oauth_token_idempotency as idem


@pytest.fixture(autouse=True)
def _isolated_registry():
    cache_backends.reset_registry_for_tests()
    yield
    cache_backends.reset_registry_for_tests()


class TestComputeBodySignature:
    def test_identical_inputs_yield_identical_signatures(self):
        sig1 = idem.compute_body_signature(client_id="cid", proof="proof", redirect_uri="https://x/cb")
        sig2 = idem.compute_body_signature(client_id="cid", proof="proof", redirect_uri="https://x/cb")
        assert sig1 == sig2
        assert len(sig1) == 64

    def test_field_separator_prevents_concatenation_collision(self):
        sig_a = idem.compute_body_signature(client_id="ab", proof="c", redirect_uri="d")
        sig_b = idem.compute_body_signature(client_id="a", proof="bc", redirect_uri="d")
        assert sig_a != sig_b

    def test_signature_changes_with_each_field(self):
        base = idem.compute_body_signature(client_id="cid", proof="proof", redirect_uri="https://x/cb")
        diff_client = idem.compute_body_signature(client_id="cid2", proof="proof", redirect_uri="https://x/cb")
        diff_proof = idem.compute_body_signature(client_id="cid", proof="proof2", redirect_uri="https://x/cb")
        diff_redir = idem.compute_body_signature(client_id="cid", proof="proof", redirect_uri="https://x/cb2")
        assert len({base, diff_client, diff_proof, diff_redir}) == 4


class TestCacheGetPut:
    @pytest.mark.asyncio
    async def test_put_then_get_round_trips_entry(self):
        entry = idem.IdempotencyEntry(
            response_body={"access_token": "tok"},
            body_signature="sig-abc",
        )
        await idem.cache_put("tk_x", "code-1", entry)
        got = await idem.cache_get("tk_x", "code-1")
        assert got is not None
        assert got.response_body == {"access_token": "tok"}
        assert got.body_signature == "sig-abc"

    @pytest.mark.asyncio
    async def test_miss_returns_none(self):
        assert await idem.cache_get("tk_x", "missing") is None

    @pytest.mark.asyncio
    async def test_tenant_scoped_keys_do_not_collide(self):
        entry_a = idem.IdempotencyEntry(
            response_body={"who": "tenant_a"},
            body_signature="sig-a",
        )
        entry_b = idem.IdempotencyEntry(
            response_body={"who": "tenant_b"},
            body_signature="sig-b",
        )
        await idem.cache_put("tk_a", "shared-code", entry_a)
        await idem.cache_put("tk_b", "shared-code", entry_b)
        got_a = await idem.cache_get("tk_a", "shared-code")
        got_b = await idem.cache_get("tk_b", "shared-code")
        assert got_a is not None and got_a.body_signature == "sig-a"
        assert got_b is not None and got_b.body_signature == "sig-b"
