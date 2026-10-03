# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ipaddress
import logging
import os


logger = logging.getLogger(__name__)


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
    "restore_request": 5,
    "account_export": 3,
    "api_key_auth_failed": 10,
    "social_login_start": 10,
    "social_login_callback": 10,
    "social_login_confirm_link": 5,
    "set_initial_password": 5,
    "oauth_token": 30,
    "oauth_refresh": 30,
    "oauth_revoke": 10,
}

_EXEMPT_LOCALHOST_ENV = "GILJO_RL_EXEMPT_LOCALHOST"
_FALSEY = {"0", "false", "no", "off"}


class _TestBypass:

    enabled: bool = False


def set_test_bypass(enabled: bool) -> None:
    _TestBypass.enabled = bool(enabled)


def is_test_bypass_enabled() -> bool:
    return _TestBypass.enabled


def limit_for(name: str) -> int:
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
    from api.app_state import GILJO_MODE

    if GILJO_MODE == "saas":
        return False
    if not _localhost_exemption_enabled():
        return False
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False
