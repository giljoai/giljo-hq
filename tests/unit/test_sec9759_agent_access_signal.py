# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

from api.endpoints.mcp_auth_middleware import _announce_agent_access
from api.endpoints.mcp_transport import _stamp_client_name
from giljo_mcp.auth.dependencies import _announce_api_key_access
from giljo_mcp.signals import (
    SIGNAL_ACCOUNT_ACCESS_OBSERVED,
    clear_signal_observers,
    publish_signal,
    register_signal_observer,
)


def _request(host: str = "203.0.113.5") -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={})


def test_stamp_client_name_takes_only_a_non_empty_string_name():
    for good, expected in (({"name": "claude-code", "version": "1"}, "claude-code"),):
        scope: dict = {}
        _stamp_client_name(scope, good)
        assert scope["state"]["mcp_client_name"] == expected
    for bad in (None, {}, {"name": ""}, {"name": 7}, {"name": ["x"]}, "claude-code", 12):
        scope = {}
        _stamp_client_name(scope, bad)
        assert "mcp_client_name" not in scope.get("state", {})


def test_announcing_without_an_observer_is_a_no_op():
    clear_signal_observers(SIGNAL_ACCOUNT_ACCESS_OBSERVED)
    _announce_agent_access({}, _request(), "tk", "user-1", None)
    _announce_api_key_access(_request(), SimpleNamespace(tenant_key="tk", user_id="user-1"))
    publish_signal(SIGNAL_ACCOUNT_ACCESS_OBSERVED, {})


def test_an_mcp_call_is_announced_with_the_kind_ip_and_stamped_client_name():
    seen: list[dict] = []
    register_signal_observer(SIGNAL_ACCOUNT_ACCESS_OBSERVED, seen.append)
    try:
        scope = {"state": {"mcp_client_name": "codex-mcp-client"}}
        _announce_agent_access(scope, _request("198.51.100.8"), "tk", "user-1", None)
        _announce_agent_access({}, _request("198.51.100.9"), "tk", "user-2", "key-1")
        _announce_agent_access({}, _request(), "tk", None, None)
    finally:
        clear_signal_observers(SIGNAL_ACCOUNT_ACCESS_OBSERVED)

    assert seen == [
        {
            "tenant_key": "tk",
            "user_id": "user-1",
            "source_kind": "oauth",
            "client_ip": "198.51.100.8",
            "client_name": "codex-mcp-client",
            "surface": "mcp",
        },
        {
            "tenant_key": "tk",
            "user_id": "user-2",
            "source_kind": "api_key",
            "client_ip": "198.51.100.9",
            "client_name": None,
            "surface": "mcp",
        },
    ]


def test_a_rest_api_key_call_is_announced_as_a_rest_surface():
    seen: list[dict] = []
    register_signal_observer(SIGNAL_ACCOUNT_ACCESS_OBSERVED, seen.append)
    try:
        _announce_api_key_access(_request("203.0.113.7"), SimpleNamespace(tenant_key="tk", user_id="user-3"))
    finally:
        clear_signal_observers(SIGNAL_ACCOUNT_ACCESS_OBSERVED)

    assert seen == [
        {
            "tenant_key": "tk",
            "user_id": "user-3",
            "source_kind": "api_key",
            "client_ip": "203.0.113.7",
            "client_name": None,
            "surface": "rest",
        }
    ]
