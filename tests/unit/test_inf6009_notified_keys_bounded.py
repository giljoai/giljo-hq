# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-6009 #7 — MCPAuthMiddleware must hold no unbounded per-principal memo.

History. The ``setup:tool_connected`` de-dup memo once grew without bound (one
entry per distinct ``tenant:principal``), a slow memory leak for long-lived SaaS
workers. INF-6009 bounded it into an insertion-ordered ordered-set with
oldest-first eviction, and these tests pinned that cap.

BE-9498 removed the memo outright rather than bounding it. Keying on
``tenant:api_key_id or user_id`` carried no client identity, so the first client
a user connected consumed the announcement and every client after it was
silenced -- connect a second tool and the setup wizard waited forever. The emit
is now gated on the JSON-RPC ``initialize`` handshake, which the protocol sends
once per client connection and therefore needs no de-dup state at all.

INF-6009's INVARIANT still stands and is what these tests now pin: this
middleware accumulates no unbounded per-principal state. Deleting the container
is a stronger guarantee than capping it. If a future change reintroduces a memo
here, these fail and INF-6009's bounding requirement applies to it again.
"""

from api.endpoints.mcp_sdk_server import MCPAuthMiddleware


def _middleware() -> MCPAuthMiddleware:
    # The middleware's __init__ does not touch the wrapped app, so a sentinel is fine.
    return MCPAuthMiddleware(app=object())


def test_middleware_holds_no_notified_keys_memo():
    """The unbounded-growth container is gone, not merely capped."""
    mw = _middleware()

    assert not hasattr(mw, "_notified_keys"), (
        "A per-principal notify memo reappeared on MCPAuthMiddleware. It silences "
        "every client after a user's first (BE-9498) and grows without bound "
        "unless capped (INF-6009). Gate on the initialize handshake instead."
    )
    assert not hasattr(mw, "_mark_notified")


def test_instance_carries_no_unbounded_accumulator():
    """No instance attribute is a growable container that requests could fill.

    Guards the INF-6009 leak shape generally, not just the one attribute name it
    was originally reported under.
    """
    mw = _middleware()

    growable = {name: value for name, value in vars(mw).items() if isinstance(value, (dict, list, set))}
    assert growable == {}, f"unbounded-growth candidates on the middleware instance: {sorted(growable)}"
