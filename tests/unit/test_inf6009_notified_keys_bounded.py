# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from api.endpoints.mcp_sdk_server import MCPAuthMiddleware


def _middleware() -> MCPAuthMiddleware:
    return MCPAuthMiddleware(app=object())


def test_middleware_holds_no_notified_keys_memo():
    mw = _middleware()

    assert not hasattr(mw, "_notified_keys"), (
        "A per-principal notify memo reappeared on MCPAuthMiddleware. It silences "
        "every client after a user's first (BE-9498) and grows without bound "
        "unless capped (INF-6009). Gate on the initialize handshake instead."
    )
    assert not hasattr(mw, "_mark_notified")


def test_instance_carries_no_unbounded_accumulator():
    mw = _middleware()

    growable = {name: value for name, value in vars(mw).items() if isinstance(value, (dict, list, set))}
    assert growable == {}, f"unbounded-growth candidates on the middleware instance: {sorted(growable)}"
