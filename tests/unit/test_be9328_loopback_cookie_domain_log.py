# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from unittest.mock import MagicMock, patch

import pytest

from api.endpoints.auth.session import _build_cookie_params


SESSION_LOGGER = "api.endpoints.auth.session"


def _make_request(host_header: str) -> MagicMock:
    request = MagicMock()
    request.client = MagicMock()
    request.headers = {"host": host_header}
    request.url.scheme = "http"
    return request


def _cookie_domain_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == SESSION_LOGGER]


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in _cookie_domain_records(caplog) if r.levelno >= logging.WARNING]




@pytest.mark.parametrize(
    "host_header",
    [
        "localhost:7272",
        "localhost",
        "LOCALHOST:7272",
        "127.0.0.1:7272",
        "[::1]:7272",
        "[::1]",
    ],
)
@patch("api.endpoints.auth.session.get_config")
def test_loopback_host_emits_no_warning(mock_config, caplog, host_header):
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    caplog.set_level(logging.DEBUG, logger=SESSION_LOGGER)

    result = _build_cookie_params(_make_request(host_header))

    assert result["domain"] is None, "loopback must stay a host-only cookie"
    assert _warnings(caplog) == [], f"loopback host {host_header!r} must not warn, got: {_warnings(caplog)}"


@patch("api.endpoints.auth.session.get_config")
def test_loopback_still_leaves_a_debug_trail(mock_config, caplog):
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    caplog.set_level(logging.DEBUG, logger=SESSION_LOGGER)

    _build_cookie_params(_make_request("localhost:7272"))

    debug_text = " ".join(r.getMessage() for r in _cookie_domain_records(caplog) if r.levelno == logging.DEBUG)
    assert "localhost" in debug_text


@pytest.mark.parametrize("host_header", ["myapp.example.com:7272", "giljo.internal", "notlocalhost:7272"])
@patch("api.endpoints.auth.session.get_config")
def test_non_whitelisted_non_loopback_host_still_warns(mock_config, caplog, host_header):
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    caplog.set_level(logging.DEBUG, logger=SESSION_LOGGER)

    result = _build_cookie_params(_make_request(host_header))

    assert result["domain"] is None
    warnings = _warnings(caplog)
    assert len(warnings) == 1, f"expected exactly one warning for {host_header!r}, got: {warnings}"
    assert host_header.split(":")[0] in warnings[0]


@patch("api.endpoints.auth.session.get_config")
def test_remaining_warning_is_not_worded_as_a_fault(mock_config, caplog):
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    caplog.set_level(logging.DEBUG, logger=SESSION_LOGGER)

    _build_cookie_params(_make_request("myapp.example.com:7272"))

    message = _warnings(caplog)[0].lower()
    assert "unknown host" not in message
    assert "whitelist" in message or "cookie-domain" in message




def _expected(domain, secure=False) -> dict:
    return {
        "key": "access_token",
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "path": "/",
        "domain": domain,
        "max_age": 86400,
    }


@pytest.mark.parametrize(
    ("host_header", "expected_domain"),
    [
        ("localhost:7272", None),
        ("localhost", None),
        ("LOCALHOST:7272", None),
        ("127.0.0.1:7272", None),
        ("127.0.0.1", None),
        ("[::1]:7272", None),
        ("[::1]", None),
        ("192.0.2.10:7272", None),
        ("myapp.example.com:7272", None),
        ("notlocalhost:7272", None),
    ],
)
@patch("api.endpoints.auth.session.get_config")
def test_cookie_params_unchanged_without_whitelist(mock_config, host_header, expected_domain):
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}

    assert _build_cookie_params(_make_request(host_header)) == _expected(expected_domain)


@patch("api.endpoints.auth.session.get_config")
def test_explicitly_whitelisted_localhost_still_scopes_to_localhost(mock_config):
    mock_config.return_value = {"security": {"cookies": {"secure": False}, "cookie_domain_whitelist": ["localhost"]}}

    result = _build_cookie_params(_make_request("localhost:7272"))

    assert result == _expected("localhost")


@patch("api.endpoints.auth.session.get_config")
def test_whitelisted_domain_unaffected(mock_config):
    mock_config.return_value = {
        "security": {"cookies": {"secure": False}, "cookie_domain_whitelist": ["myapp.example.com"]}
    }

    result = _build_cookie_params(_make_request("myapp.example.com:7272"))

    assert result == _expected("myapp.example.com")


@patch("api.endpoints.auth.session.get_config")
def test_https_loopback_keeps_secure_upgrade(mock_config):
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    request = _make_request("localhost:7272")
    request.url.scheme = "https"

    assert _build_cookie_params(request) == _expected(None, secure=True)
