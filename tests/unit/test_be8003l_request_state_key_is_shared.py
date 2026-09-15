# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from mcp.server.request_state import InvalidRequestState, RequestStateSecurity

from api.endpoints.mcp_tools._base import _request_state_security


_SECRET_VARS = ("JWT_SECRET", "GILJO_MCP_SECRET_KEY", "SECRET_KEY")
_PAYLOAD = b'{"kind": "be8003l.approval", "approval_id": "ap-1"}'


def _clear_secrets(monkeypatch) -> None:
    for var in _SECRET_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("var", _SECRET_VARS)
def test_two_workers_holding_the_same_secret_can_read_each_others_state(monkeypatch, var):
    _clear_secrets(monkeypatch)
    monkeypatch.setenv(var, "a-shared-application-secret")

    worker_a = _request_state_security()
    worker_b = _request_state_security()

    token = worker_a.codec.seal(_PAYLOAD)
    assert worker_b.codec.unseal(token) == _PAYLOAD, (
        "a client's round-2 retry can land on any worker; if worker B cannot read worker A's "
        "requestState the MRTR approval flow fails on ~3 of 4 requests in prod"
    )


def test_the_ephemeral_default_is_what_we_are_avoiding():
    worker_a = RequestStateSecurity.ephemeral()
    worker_b = RequestStateSecurity.ephemeral()

    token = worker_a.codec.seal(_PAYLOAD)
    with pytest.raises(InvalidRequestState):
        worker_b.codec.unseal(token)


def test_a_short_secret_still_produces_a_usable_key(monkeypatch):
    _clear_secrets(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "short")

    security = _request_state_security()
    assert security.codec.unseal(security.codec.seal(_PAYLOAD)) == _PAYLOAD


def test_the_sealed_key_is_not_the_application_secret(monkeypatch):
    _clear_secrets(monkeypatch)
    secret = "x" * 32
    monkeypatch.setenv("JWT_SECRET", secret)

    derived = _request_state_security()
    raw = RequestStateSecurity(keys=[secret])

    with pytest.raises(InvalidRequestState):
        raw.codec.unseal(derived.codec.seal(_PAYLOAD))


def test_no_secret_configured_falls_back_instead_of_failing_to_boot(monkeypatch):
    _clear_secrets(monkeypatch)
    security = _request_state_security()
    assert security.codec.unseal(security.codec.seal(_PAYLOAD)) == _PAYLOAD


def test_the_live_server_is_wired_to_the_shared_policy():
    from mcp.server.request_state import RequestStateBoundary

    from api.endpoints.mcp_tools._base import mcp

    boundaries = [m for m in mcp.middleware if isinstance(m, RequestStateBoundary)]
    assert len(boundaries) == 1, f"expected exactly one request-state boundary, got {len(boundaries)}"
    assert boundaries[0]._audience == mcp.name, (
        "the audience claim is what stops state minted by another service sharing our keys"
    )
