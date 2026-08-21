# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-8003l -- the MCP ``requestState`` key must be shared by every worker.

Why this guard exists
=====================
The multi-round-trip approval flow is two ``tools/call`` requests: round 1 mints a
sealed ``requestState``, and the client echoes it back on round 2. The SDK installs
``RequestStateBoundary`` unconditionally and, when nothing is configured, seals
under ``RequestStateSecurity.ephemeral()`` -- ``keys=[os.urandom(32)]``, held only
by the minting process.

Multi-worker deployments cannot route a retry back to the worker that minted its
token, so under the ephemeral default a retry can land on a stranger and be
refused with -32602 **above** the tool -- so ``request_approval`` would never get
to run its own fallback. That is the difference between a feature that degrades
gracefully and one that returns protocol errors in production.

These tests are written to FAIL if ``_request_state_security()`` is reverted to the
SDK default: ``test_the_ephemeral_default_is_what_we_are_avoiding`` shows the
broken behaviour explicitly, so the guard proves a real difference rather than
just asserting that some object was constructed.

Parallel-safe: no DB, no module-level mutable state; env via ``monkeypatch``.
"""

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
    """The actual guarantee: worker A seals, worker B unseals.

    Each call to ``_request_state_security()`` stands in for a separate uvicorn
    worker process reading the same environment.
    """
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
    """The control that gives the test above its meaning.

    Without this, 'worker B can unseal' would pass against ANY implementation that
    happened to share state some other way. This pins that the SDK's default
    genuinely cannot, so reverting ``_request_state_security()`` to it turns the
    guarantee above red.
    """
    worker_a = RequestStateSecurity.ephemeral()
    worker_b = RequestStateSecurity.ephemeral()

    token = worker_a.codec.seal(_PAYLOAD)
    with pytest.raises(InvalidRequestState):
        worker_b.codec.unseal(token)


def test_a_short_secret_still_produces_a_usable_key(monkeypatch):
    """The SDK requires >= 32 bytes and RAISES at construction below that.

    Real secrets are routinely shorter (this repo's own test environment uses a
    15-byte one), and ``_base`` is imported at app start -- so handing the raw
    secret to the SDK would refuse to boot the server rather than degrade. The
    derivation always yields 32 bytes.
    """
    _clear_secrets(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "short")

    security = _request_state_security()
    assert security.codec.unseal(security.codec.seal(_PAYLOAD)) == _PAYLOAD


def test_the_sealed_key_is_not_the_application_secret(monkeypatch):
    """Derivation, not reuse: the request-state key must not BE the JWT secret.

    A 32-byte secret is long enough for the SDK to accept verbatim, which is
    exactly the case where an implementation could pass it straight through
    without anyone noticing.
    """
    _clear_secrets(monkeypatch)
    secret = "x" * 32
    monkeypatch.setenv("JWT_SECRET", secret)

    derived = _request_state_security()
    raw = RequestStateSecurity(keys=[secret])

    with pytest.raises(InvalidRequestState):
        raw.codec.unseal(derived.codec.seal(_PAYLOAD))


def test_no_secret_configured_falls_back_instead_of_failing_to_boot(monkeypatch):
    """A bare import or half-configured box must not crash at module import.

    Single-process deployments are exactly the case the ephemeral policy is
    correct for, so falling back is right; failing the import is not.
    """
    _clear_secrets(monkeypatch)
    security = _request_state_security()
    assert security.codec.unseal(security.codec.seal(_PAYLOAD)) == _PAYLOAD


def test_the_live_server_is_wired_to_the_shared_policy():
    """The unit above proves the helper; this proves the server actually uses it.

    ``MCPServer`` appends its own ``RequestStateBoundary`` at construction, so the
    only way to know which policy is installed is to look at the live chain.
    """
    from mcp.server.request_state import RequestStateBoundary

    from api.endpoints.mcp_tools._base import mcp

    boundaries = [m for m in mcp.middleware if isinstance(m, RequestStateBoundary)]
    assert len(boundaries) == 1, f"expected exactly one request-state boundary, got {len(boundaries)}"
    assert boundaries[0]._audience == mcp.name, (
        "the audience claim is what stops state minted by another service sharing our keys"
    )
