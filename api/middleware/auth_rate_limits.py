# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Configurable per-path limits + CE localhost exemption for the pre-auth
IP rate limiter (BE-6063f).

The limiter itself (``auth_rate_limiter.RateLimiter``) is unchanged in shape:
it still takes a ``limit`` per call. This module is the policy layer that decides
*what* that number is and *whether* a given client IP is exempt.

Two knobs, both env-driven so an operator can tune without a redeploy of code:

* ``limit_for(name)`` — returns the per-path limit. Defaults live in
  ``DEFAULTS``; an operator overrides any single path with
  ``GILJO_RL_<NAME>`` (e.g. ``GILJO_RL_LOGIN=20``). A missing/blank/invalid
  override falls back to the default — a typo must never silently disable a
  limit or raise at request time.

* ``is_exempt_ip(ip)`` — a **CE-only** loopback exemption. CE is self-hosted and
  typically single-operator on ``127.0.0.1``; rate-limiting that operator's own
  login risks locking them out of their own box. So in CE mode a loopback IP is
  exempt (toggleable via ``GILJO_RL_EXEMPT_LOCALHOST``, default on). In SaaS mode
  this ALWAYS returns ``False`` — a hosted, multi-tenant deployment must never
  exempt any IP, loopback or otherwise.

Edition Scope: Both. (CE gets the exemption; SaaS gets the env-tunable limits
with the exemption hard-disabled.)
"""

from __future__ import annotations

import ipaddress
import logging
import os


logger = logging.getLogger(__name__)


# Per-path defaults (requests per 60s window). These are the SAME numbers the
# call sites used as literals before BE-6063f, so behavior is unchanged unless an
# operator sets a GILJO_RL_<NAME> override.
DEFAULTS: dict[str, int] = {
    "login": 5,
    "register": 3,
    "password_reset_request": 5,
    "password_reset_confirm": 10,
    "create_first_admin": 3,
    "oauth_register": 5,
    "email_change_request": 5,
    "email_change_confirm": 10,
    "account_deletion_confirm": 5,
    "account_deletion_cancel": 10,
    # BE-6130f: restore-request creation per IP per 60s (authenticated, but capped
    # to prevent a compromised session from flooding the operator restore queue).
    "restore_request": 5,
    # BE-6060b: FAILED API-key auths per IP per 60s. Counted only on a
    # verification failure (valid keys never accrue), so a single IP cannot spray
    # garbage keys against the prefix-narrowed verify path without being throttled.
    # Generous enough that a real client fat-fingering a key a few times is fine.
    "api_key_auth_failed": 10,
    # BE-1002: social-login start/callback, per IP per 60s. Both are
    # browser-navigation GETs (not form POSTs), so the limit is generous
    # enough that Google's own redirect round-trip never trips it, while still
    # bounding an IP hammering the flow (e.g. state/code brute-forcing).
    "social_login_start": 10,
    "social_login_callback": 10,
    # BE-1004: confirm-then-link password check, per IP per 60s. Mirrors
    # "login" (5) -- this endpoint verifies a password just like /login does,
    # so it gets the same brute-force-resistant ceiling, on top of the
    # per-(identifier, IP) LoginLockoutService gate it also shares with /login.
    "social_login_confirm_link": 5,
    # BE-9032: set-initial-password, per IP per 60s. Authenticated, but a
    # password-set action gets the same brute-force-resistant ceiling as
    # "login"/"social_login_confirm_link" (5) as defense-in-depth on top of
    # the password_hash-IS-NULL guard in UserAuthService.set_initial_password.
    "set_initial_password": 5,
    # SEC-9227d (M3): the OAuth token-endpoint family (public/unauthenticated
    # by spec; every bad client_secret costs a server-side bcrypt verify, so
    # unlimited attempts are CPU amplification + secret brute-force).
    # oauth_token: per IP per 60s. Generous: a legitimate client exchanges ONE
    # code per authorization, but connector backends (ChatGPT multi-egress)
    # retry in bursts; 30 absorbs honest retry storms while capping bcrypt
    # spend. NOTE: different egress IPs bucket separately — this limit is
    # per-IP by design.
    "oauth_token": 30,
    # oauth_refresh: per IP per 60s. A healthy client refreshes ~1/hour after
    # SEC-9227c; 30/min absorbs retry bursts + multi-client households behind
    # one NAT.
    "oauth_refresh": 30,
    # oauth_revoke: per IP per 60s. Revocation is rare; RFC 7009 responses are
    # always-200 so throttling can't leak validity, but unlimited calls let an
    # attacker grind the DB-lookup path.
    "oauth_revoke": 10,
}

# Toggle for the CE loopback exemption. Default ON. Any of these (case-insensitive)
# turns it OFF: "0", "false", "no", "off".
_EXEMPT_LOCALHOST_ENV = "GILJO_RL_EXEMPT_LOCALHOST"
_FALSEY = {"0", "false", "no", "off"}


class _TestBypass:
    """Holder for the test-only bypass flag (avoids a module-level ``global``).

    Mirrors the ``_RateLimiterHolder`` idiom in ``auth_rate_limiter``.
    """

    enabled: bool = False


def set_test_bypass(enabled: bool) -> None:
    """Test-only escape hatch: turn the pre-auth rate-limit bypass on/off.

    Production code MUST NOT call this. The suite drives it from an autouse
    fixture in ``tests/conftest.py``; suites that exercise the limiter itself
    opt out via the ``real_auth_rate_limiter`` fixture.
    """
    _TestBypass.enabled = bool(enabled)


def is_test_bypass_enabled() -> bool:
    """Whether the test-only rate-limit bypass is active. Default: ``False``.

    SEC-9227 (H4). This replaced a bypass that read ``request.base_url`` — i.e.
    the inbound ``Host`` header — and exempted anything starting with
    ``http://test``. ``Host`` is attacker-controlled, so on a plain-HTTP
    deployment any client could disable every pre-auth limit (login, register,
    DCR, PIN recovery) for itself by sending ``Host: testanything``. A
    rate-limit decision must never be derived from request data.

    This flag takes no request input at all: it is process-local module state,
    settable only by calling ``set_test_bypass`` from Python, which no request
    path does. It defaults to OFF, so a production process never bypasses.

    Deliberately named ``is_test_bypass_enabled`` rather than
    ``test_bypass_enabled``: a ``test_``-prefixed name imported into a test
    module gets collected by pytest as a test case.
    """
    return _TestBypass.enabled


def limit_for(name: str) -> int:
    """Return the per-path rate limit for ``name``.

    Resolution order:
      1. ``GILJO_RL_<NAME>`` env override, if it is a positive integer.
      2. ``DEFAULTS[name]``.

    A blank, non-integer, or non-positive override is ignored (with a warning)
    and the default is used. ``name`` must be a known key in ``DEFAULTS``;
    an unknown name is a programming error and raises ``KeyError``.
    """
    default = DEFAULTS[name]
    raw = os.getenv(f"GILJO_RL_{name.upper()}")
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning(
            "Ignoring non-integer GILJO_RL_%s=%r; using default %d",
            name.upper(),
            raw,
            default,
        )
        return default
    if value <= 0:
        logger.warning(
            "Ignoring non-positive GILJO_RL_%s=%d; using default %d",
            name.upper(),
            value,
            default,
        )
        return default
    return value


def _localhost_exemption_enabled() -> bool:
    raw = os.getenv(_EXEMPT_LOCALHOST_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSEY


def is_exempt_ip(ip: str) -> bool:
    """Whether ``ip`` is exempt from pre-auth rate limiting.

    CE-only loopback exemption. Returns ``True`` only when ALL hold:
      * the deployment is CE (``GILJO_MODE`` is not ``"saas"``),
      * the exemption toggle is on (default), and
      * ``ip`` parses as a loopback address (``127.0.0.0/8`` or ``::1``).

    In SaaS mode this ALWAYS returns ``False`` — a hosted, multi-tenant
    deployment must never exempt any IP. An unparseable ``ip`` (e.g. the
    ``"unknown"`` sentinel) is never exempt.
    """
    # Read GILJO_MODE from app_state (single source of truth) rather than os.getenv
    # so it tracks the same value the rest of the app branches on.
    from api.app_state import GILJO_MODE

    if GILJO_MODE == "saas":
        return False
    if not _localhost_exemption_enabled():
        return False
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False
