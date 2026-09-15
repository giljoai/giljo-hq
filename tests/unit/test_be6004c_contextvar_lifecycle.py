# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from contextvars import Token

import pytest

from giljo_mcp.tenant import (
    TenantManager,
    clear_current_tenant,
    current_tenant,
    get_current_tenant,
    set_current_tenant,
    with_tenant,
)


def _key() -> str:
    return TenantManager.generate_tenant_key()


@pytest.fixture(autouse=True)
def _clean_tenant_context():
    token = current_tenant.set(None)
    try:
        yield
    finally:
        current_tenant.reset(token)


def test_set_current_tenant_returns_usable_token():
    key = _key()
    token = TenantManager.set_current_tenant(key)
    try:
        assert isinstance(token, Token)
        assert TenantManager.get_current_tenant() == key
    finally:
        current_tenant.reset(token)
    assert TenantManager.get_current_tenant() is None


def test_reset_with_token_restores_prior_value():
    outer = _key()
    outer_token = TenantManager.set_current_tenant(outer)
    inner = _key()
    inner_token = TenantManager.set_current_tenant(inner)

    assert TenantManager.get_current_tenant() == inner
    current_tenant.reset(inner_token)
    assert TenantManager.get_current_tenant() == outer
    current_tenant.reset(outer_token)
    assert TenantManager.get_current_tenant() is None


def test_clear_current_tenant_is_bare_hard_clear():
    set_current_tenant(_key())
    assert get_current_tenant() is not None
    clear_current_tenant()
    assert get_current_tenant() is None

    TenantManager.set_current_tenant(_key())
    assert TenantManager.get_current_tenant() is not None
    TenantManager.clear_current_tenant()
    assert TenantManager.get_current_tenant() is None


def test_nested_with_tenant_unwinds_to_exact_prior_value():
    tenant_a = _key()
    tenant_b = _key()

    assert TenantManager.get_current_tenant() is None
    with TenantManager.with_tenant(tenant_a):
        assert TenantManager.get_current_tenant() == tenant_a
        with TenantManager.with_tenant(tenant_b):
            assert TenantManager.get_current_tenant() == tenant_b
        assert TenantManager.get_current_tenant() == tenant_a
    assert TenantManager.get_current_tenant() is None


def test_nested_with_tenant_convenience_function_unwinds():
    tenant_a = _key()
    tenant_b = _key()

    with with_tenant(tenant_a):
        assert get_current_tenant() == tenant_a
        with with_tenant(tenant_b):
            assert get_current_tenant() == tenant_b
        assert get_current_tenant() == tenant_a
    assert get_current_tenant() is None


def test_with_tenant_restores_after_exception():
    tenant_a = _key()
    tenant_b = _key()

    def raise_inside_context() -> None:
        with TenantManager.with_tenant(tenant_b):
            assert TenantManager.get_current_tenant() == tenant_b
            raise RuntimeError("boom inside tenant context")

    set_current_tenant(tenant_a)
    try:
        with pytest.raises(RuntimeError):
            raise_inside_context()
        assert TenantManager.get_current_tenant() == tenant_a
    finally:
        TenantManager.clear_current_tenant()
    assert TenantManager.get_current_tenant() is None


def test_with_tenant_restores_none_when_no_prior_context():
    assert TenantManager.get_current_tenant() is None
    with TenantManager.with_tenant(_key()):
        assert TenantManager.get_current_tenant() is not None
    assert TenantManager.get_current_tenant() is None


def test_simulated_request_cycle_leaves_no_residue():
    assert get_current_tenant() is None

    def handle_request(tenant_key: str) -> None:
        token = set_current_tenant(tenant_key)
        try:
            assert get_current_tenant() == tenant_key
        finally:
            current_tenant.reset(token)

    handle_request(_key())
    assert get_current_tenant() is None, "tenant leaked onto the worker after request"

    handle_request(_key())
    assert get_current_tenant() is None, "tenant leaked onto the worker after second request"


def test_simulated_request_cycle_resets_even_on_exception():
    assert get_current_tenant() is None
    key = _key()

    def failing_request() -> None:
        token = set_current_tenant(key)
        try:
            raise RuntimeError("handler exploded")
        finally:
            current_tenant.reset(token)

    with pytest.raises(RuntimeError):
        failing_request()
    assert get_current_tenant() is None, "exception path left tenant residue on the worker"


def test_invalid_tenant_key_rejected_before_set():
    assert get_current_tenant() is None
    with pytest.raises(ValueError):
        set_current_tenant("not-a-valid-tenant-key")
    assert get_current_tenant() is None
