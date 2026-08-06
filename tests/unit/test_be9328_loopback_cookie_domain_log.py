# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9328: a loopback host is not an "unknown host" worth warning about.

A fresh localhost install logged a WARNING at the exact moment the user created
their first administrator account::

    Cookie domain set to None for unknown host 'localhost' (not in whitelist: []).
    Add it in Settings -> Network if cross-domain auth is needed.

The cookie behaviour it describes is CORRECT -- ``domain=None`` is a host-only
cookie, which is exactly right for loopback. Only the message was wrong: it
called the documented default install posture an "unknown host" and told a
first-time user to go configure something that does nothing for them.

These tests therefore split into two halves:

* the LOG half (what this project changes) -- loopback must not WARN, a
  genuinely unknown host must still WARN;
* the BEHAVIOUR half (what this project must NOT change) -- the exact cookie
  parameter dict is pinned for every host shape, loopback and not. That pin is
  the load-bearing test here: it is what proves the fix is a logging change and
  nothing more.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from api.endpoints.auth.session import _build_cookie_params


SESSION_LOGGER = "api.endpoints.auth.session"


def _make_request(host_header: str) -> MagicMock:
    """Mock Request carrying ``host_header``, plain http (the CE-localhost shape).

    Deliberately not ``spec=Request``: ``MagicMock(spec=Request)`` is falsy, which
    would short-circuit the ``if request and request.client:`` guard under test.
    """
    request = MagicMock()
    request.client = MagicMock()
    request.headers = {"host": host_header}
    request.url.scheme = "http"
    return request


def _cookie_domain_records(caplog) -> list[logging.LogRecord]:
    """Every record the cookie-domain resolution site emitted."""
    return [r for r in caplog.records if r.name == SESSION_LOGGER]


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in _cookie_domain_records(caplog) if r.levelno >= logging.WARNING]


# --- The LOG half: what this project changes -------------------------------


@pytest.mark.parametrize(
    "host_header",
    [
        "localhost:7272",  # installer option 1, the default
        "localhost",  # no port
        "LOCALHOST:7272",  # case-insensitive
        "127.0.0.1:7272",  # already quiet pre-fix (IP branch) -- pinned so it stays quiet
        "[::1]:7272",  # IPv6 loopback, bracketed per RFC 3986
        "[::1]",
    ],
)
@patch("api.endpoints.auth.session.get_config")
def test_loopback_host_emits_no_warning(mock_config, caplog, host_header):
    """A loopback host must not warn -- it is the documented default posture.

    This is the first thing a new user ever does (create-first-admin on a fresh
    localhost install), so a warning here trains them to distrust the logs.
    """
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    caplog.set_level(logging.DEBUG, logger=SESSION_LOGGER)

    result = _build_cookie_params(_make_request(host_header))

    assert result["domain"] is None, "loopback must stay a host-only cookie"
    assert _warnings(caplog) == [], f"loopback host {host_header!r} must not warn, got: {_warnings(caplog)}"


@patch("api.endpoints.auth.session.get_config")
def test_loopback_still_leaves_a_debug_trail(mock_config, caplog):
    """Silencing the warning must not silence the diagnosis -- DEBUG still records it."""
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    caplog.set_level(logging.DEBUG, logger=SESSION_LOGGER)

    _build_cookie_params(_make_request("localhost:7272"))

    debug_text = " ".join(r.getMessage() for r in _cookie_domain_records(caplog) if r.levelno == logging.DEBUG)
    assert "localhost" in debug_text


@pytest.mark.parametrize("host_header", ["myapp.example.com:7272", "giljo.internal", "notlocalhost:7272"])
@patch("api.endpoints.auth.session.get_config")
def test_non_whitelisted_non_loopback_host_still_warns(mock_config, caplog, host_header):
    """The warning is NOT weakened generally.

    A LAN or custom-domain install that is not whitelisted is a real case where
    cross-domain auth silently will not work, and it still deserves the warning.
    """
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    caplog.set_level(logging.DEBUG, logger=SESSION_LOGGER)

    result = _build_cookie_params(_make_request(host_header))

    assert result["domain"] is None
    warnings = _warnings(caplog)
    assert len(warnings) == 1, f"expected exactly one warning for {host_header!r}, got: {warnings}"
    assert host_header.split(":")[0] in warnings[0]


@patch("api.endpoints.auth.session.get_config")
def test_remaining_warning_is_not_worded_as_a_fault(mock_config, caplog):
    """The surviving warning states a condition, not an accusation.

    "unknown host" reads as an error to someone who has done nothing wrong. The
    actual meaning is: this host is not whitelisted for cross-domain cookies,
    which only matters if you need cross-domain auth.
    """
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    caplog.set_level(logging.DEBUG, logger=SESSION_LOGGER)

    _build_cookie_params(_make_request("myapp.example.com:7272"))

    message = _warnings(caplog)[0].lower()
    assert "unknown host" not in message
    assert "whitelist" in message or "cookie-domain" in message


# --- The BEHAVIOUR half: what this project must NOT change -----------------
#
# The cookie was already correct. These pins are the point of the project: they
# hold the full parameter dict byte-identical across the logging change, so a
# diff that touches cookie construction cannot pass.


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
    """LOAD-BEARING: the exact cookie dict, pinned for every host shape.

    Every one of these is a host-only cookie (``domain=None``) and was already
    correct before BE-9328. If this test moves, the fix has changed behaviour and
    is wrong by definition.
    """
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}

    assert _build_cookie_params(_make_request(host_header)) == _expected(expected_domain)


@patch("api.endpoints.auth.session.get_config")
def test_explicitly_whitelisted_localhost_still_scopes_to_localhost(mock_config):
    """The loopback log branch must not preempt the whitelist lookup.

    An operator who deliberately whitelisted ``localhost`` gets ``domain=localhost``
    exactly as before -- quieting the log must not quietly re-scope their cookie.
    """
    mock_config.return_value = {"security": {"cookies": {"secure": False}, "cookie_domain_whitelist": ["localhost"]}}

    result = _build_cookie_params(_make_request("localhost:7272"))

    assert result == _expected("localhost")


@patch("api.endpoints.auth.session.get_config")
def test_whitelisted_domain_unaffected(mock_config):
    """A normal whitelisted domain is untouched by the loopback branch."""
    mock_config.return_value = {
        "security": {"cookies": {"secure": False}, "cookie_domain_whitelist": ["myapp.example.com"]}
    }

    result = _build_cookie_params(_make_request("myapp.example.com:7272"))

    assert result == _expected("myapp.example.com")


@patch("api.endpoints.auth.session.get_config")
def test_https_loopback_keeps_secure_upgrade(mock_config):
    """The scheme-derived Secure flag is orthogonal and must survive untouched."""
    mock_config.return_value = {"security": {"cookies": {"secure": False}}}
    request = _make_request("localhost:7272")
    request.url.scheme = "https"

    assert _build_cookie_params(request) == _expected(None, secure=True)
