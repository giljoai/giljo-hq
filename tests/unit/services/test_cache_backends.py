# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services.cache_backends import (
    InProcessDictBackend,
    get_cache_backend,
    register_cache_backend,
    reset_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


class TestInProcessDictBackend:
    @pytest.mark.asyncio
    async def test_set_then_get_round_trips(self):
        backend = InProcessDictBackend(namespace="oauth_idempotency")
        await backend.set("tk_x", "code-1", "payload", ttl_seconds=5)
        assert await backend.get("tk_x", "code-1") == "payload"

    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self):
        backend = InProcessDictBackend(namespace="oauth_idempotency")
        assert await backend.get("tk_x", "missing") is None

    @pytest.mark.asyncio
    async def test_ttl_zero_means_immediate_expiry_on_next_read(self):
        backend = InProcessDictBackend(namespace="oauth_idempotency")
        await backend.set("tk_x", "code-1", "payload", ttl_seconds=0)
        assert await backend.get("tk_x", "code-1") is None

    @pytest.mark.asyncio
    async def test_setnx_returns_true_on_first_write_false_on_conflict(self):
        backend = InProcessDictBackend(namespace="oauth_idempotency")
        assert await backend.setnx("tk_x", "code-1", "first", ttl_seconds=5) is True
        assert await backend.setnx("tk_x", "code-1", "second", ttl_seconds=5) is False
        assert await backend.get("tk_x", "code-1") == "first"

    @pytest.mark.asyncio
    async def test_setnx_after_expiry_allows_new_write(self):
        backend = InProcessDictBackend(namespace="oauth_idempotency")
        await backend.setnx("tk_x", "code-1", "first", ttl_seconds=0)
        assert await backend.setnx("tk_x", "code-1", "second", ttl_seconds=5) is True
        assert await backend.get("tk_x", "code-1") == "second"

    @pytest.mark.asyncio
    async def test_delete_removes_entry(self):
        backend = InProcessDictBackend(namespace="oauth_idempotency")
        await backend.set("tk_x", "code-1", "payload", ttl_seconds=5)
        await backend.delete("tk_x", "code-1")
        assert await backend.get("tk_x", "code-1") is None

    @pytest.mark.asyncio
    async def test_delete_is_idempotent(self):
        backend = InProcessDictBackend(namespace="oauth_idempotency")
        await backend.delete("tk_x", "never-existed")

    @pytest.mark.asyncio
    async def test_tenant_keys_are_isolated(self):
        backend = InProcessDictBackend(namespace="oauth_idempotency")
        await backend.set("tk_a", "shared-code", "alpha", ttl_seconds=5)
        await backend.set("tk_b", "shared-code", "beta", ttl_seconds=5)
        assert await backend.get("tk_a", "shared-code") == "alpha"
        assert await backend.get("tk_b", "shared-code") == "beta"

    @pytest.mark.asyncio
    async def test_namespaces_are_isolated(self):
        idemp = InProcessDictBackend(namespace="oauth_idempotency")
        refresh = InProcessDictBackend(namespace="oauth_refresh")
        await idemp.set("tk_x", "same-key", "from-idemp", ttl_seconds=5)
        await refresh.set("tk_x", "same-key", "from-refresh", ttl_seconds=5)
        assert await idemp.get("tk_x", "same-key") == "from-idemp"
        assert await refresh.get("tk_x", "same-key") == "from-refresh"

    @pytest.mark.asyncio
    async def test_soft_cap_evicts_oldest_by_expiry(self):
        backend = InProcessDictBackend(namespace="oauth_idempotency", max_entries=3)
        await backend.set("tk_x", "k0", "v0", ttl_seconds=10)
        await backend.set("tk_x", "k1", "v1", ttl_seconds=20)
        await backend.set("tk_x", "k2", "v2", ttl_seconds=30)
        await backend.set("tk_x", "k3", "v3", ttl_seconds=40)
        assert await backend.get("tk_x", "k0") is None
        assert await backend.get("tk_x", "k3") == "v3"


    @pytest.mark.asyncio
    async def test_incr_counts_up_from_one(self):
        backend = InProcessDictBackend(namespace="auth_rate_limiter")
        assert await backend.incr("tk_rl", "ip:bucket", ttl_seconds=60) == 1
        assert await backend.incr("tk_rl", "ip:bucket", ttl_seconds=60) == 2
        assert await backend.incr("tk_rl", "ip:bucket", ttl_seconds=60) == 3

    @pytest.mark.asyncio
    async def test_incr_resets_after_window_expiry(self):
        backend = InProcessDictBackend(namespace="auth_rate_limiter")
        assert await backend.incr("tk_rl", "ip:bucket", ttl_seconds=0) == 1
        assert await backend.incr("tk_rl", "ip:bucket", ttl_seconds=60) == 1

    @pytest.mark.asyncio
    async def test_incr_is_tenant_and_key_isolated(self):
        backend = InProcessDictBackend(namespace="auth_rate_limiter")
        assert await backend.incr("tk_a", "ip:bucket", ttl_seconds=60) == 1
        assert await backend.incr("tk_b", "ip:bucket", ttl_seconds=60) == 1
        assert await backend.incr("tk_a", "other:bucket", ttl_seconds=60) == 1
        assert await backend.incr("tk_a", "ip:bucket", ttl_seconds=60) == 2

    @pytest.mark.asyncio
    async def test_concurrent_incr_yields_distinct_counts(self):
        import asyncio

        backend = InProcessDictBackend(namespace="auth_rate_limiter")
        results = await asyncio.gather(*(backend.incr("tk_rl", "ip:bucket", ttl_seconds=60) for _ in range(50)))
        assert sorted(results) == list(range(1, 51))


class TestRegistry:
    def test_get_cache_backend_creates_default_on_first_miss(self):
        backend = get_cache_backend("oauth_idempotency")
        assert isinstance(backend, InProcessDictBackend)
        assert get_cache_backend("oauth_idempotency") is backend

    def test_register_cache_backend_swaps_the_impl(self):
        first = get_cache_backend("oauth_idempotency")
        replacement = InProcessDictBackend(namespace="replacement")
        register_cache_backend("oauth_idempotency", replacement)
        assert get_cache_backend("oauth_idempotency") is replacement
        assert get_cache_backend("oauth_idempotency") is not first

    def test_reset_registry_drops_registrations(self):
        register_cache_backend("oauth_idempotency", InProcessDictBackend(namespace="custom"))
        reset_registry_for_tests()
        backend = get_cache_backend("oauth_idempotency")
        assert isinstance(backend, InProcessDictBackend)
        assert backend.namespace == "oauth_idempotency"


class TestSingleWorkerBoundary:

    @pytest.mark.asyncio
    async def test_two_dict_backends_do_not_share_state(self):
        backend_a = InProcessDictBackend(namespace="oauth_idempotency")
        backend_b = InProcessDictBackend(namespace="oauth_idempotency")
        await backend_a.set("tk_x", "code-1", "from-worker-A", ttl_seconds=5)
        assert await backend_b.get("tk_x", "code-1") is None
