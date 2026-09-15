# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import time

import pytest

from giljo_mcp.services import oauth_revocation_service as rev


@pytest.fixture(autouse=True)
def _clear_cache():
    rev.clear_revocation_cache()
    yield
    rev.clear_revocation_cache()


class TestRevocationCachePositive:
    def test_put_then_get_returns_true(self):
        rev._cache_put("tenant_a", "jti-1", is_revoked=True)
        assert rev._cache_get("tenant_a", "jti-1") is True

    def test_miss_returns_none(self):
        assert rev._cache_get("tenant_a", "nope") is None


class TestRevocationCacheNegative:
    def test_negative_entry_returns_false(self):
        rev._cache_put("tenant_a", "jti-1", is_revoked=False)
        assert rev._cache_get("tenant_a", "jti-1") is False


class TestRevocationCacheTenantIsolation:
    def test_revoked_in_a_does_not_poison_b(self):
        rev._cache_put("tenant_a", "shared-jti", is_revoked=True)
        assert rev._cache_get("tenant_a", "shared-jti") is True
        assert rev._cache_get("tenant_b", "shared-jti") is None


class TestRevocationCacheTtl:
    def test_expired_entry_pops_on_read(self, monkeypatch):
        clock = {"now": 1000.0}
        monkeypatch.setattr(rev.time, "monotonic", lambda: clock["now"])

        rev._cache_put("tenant_a", "jti-x", is_revoked=True)
        assert rev._cache_get("tenant_a", "jti-x") is True

        clock["now"] += rev.REVOCATION_CACHE_TTL_POSITIVE + 0.1
        assert rev._cache_get("tenant_a", "jti-x") is None

    def test_negative_ttl_is_shorter_than_positive(self):
        assert rev.REVOCATION_CACHE_TTL_NEGATIVE < rev.REVOCATION_CACHE_TTL_POSITIVE


class TestRevocationCacheEviction:
    def test_cache_does_not_grow_unbounded(self, monkeypatch):
        monkeypatch.setattr(rev, "_REVOCATION_CACHE_MAX_ENTRIES", 4)
        for i in range(10):
            rev._cache_put("tenant", f"jti-{i}", is_revoked=True)
        assert len(rev._revocation_cache) <= 4


class TestClearRevocationCacheHelper:
    def test_clear_drops_everything(self):
        rev._cache_put("tenant", "jti", is_revoked=True)
        assert rev._cache_get("tenant", "jti") is True
        rev.clear_revocation_cache()
        assert rev._cache_get("tenant", "jti") is None


def test_module_exports_expected_symbols():
    assert callable(rev.revoke_token)
    assert callable(rev.is_access_token_jti_revoked)
    assert callable(rev.clear_revocation_cache)
    assert rev.TOKEN_TYPE_ACCESS == "access_token"
    assert rev.TOKEN_TYPE_REFRESH == "refresh_token"


_ = time
