# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE+SaaS] Module is import-safe in CE; init_sentry is a no-op outside saas.

"""Sentry SDK initialization with PII scrubbing (INF-5063).

Edition gating lives in this module: ``init_sentry()`` is a no-op unless
``GILJO_MODE == "saas"``. CE imports remain safe — the ``sentry_sdk``
package is only imported lazily inside the gate, so a CE deployment with no
``sentry-sdk`` installed will still start cleanly as long as ``init_sentry``
short-circuits before the import.

This is the boundary: api/observability/ lives in CE-shared territory, but
the runtime path is SaaS only.
"""

from __future__ import annotations

import logging
import os
from typing import Any


logger = logging.getLogger(__name__)


_PII_HEADERS_LOWER = frozenset(
    {
        "authorization",
        "cookie",
        "x-api-key",
        "x-csrf-token",
    }
)


# INF-5070: Defense-in-depth event-drop filter.
#
# Some log records semantically represent expected protocol traffic (an
# anonymous /api/auth/me probe, a normal "session-missing" credential
# rejection) and have no business creating Sentry issues. The log-level
# downgrade in src/giljo_mcp/auth/dependencies.py is the primary fix; this
# filter is the backstop in case a future refactor accidentally raises the
# level back to ERROR. Each entry pairs a logger name with message prefixes
# that should be dropped even if they reach the SDK as event-level records.
_EVENT_DROP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "giljo_mcp.auth.dependencies",
        (
            "[AUTH] FAILED",
            "[AUTH] anonymous",
        ),
    ),
    # INF-5070: BaseGiljoError handler in api/exception_handlers.py logs the
    # exception's error_code as a prefix. The runtime fix downgrades 4xx
    # cases to WARNING so they never become events; this filter is the
    # backstop for known-noisy 4xx error codes in case a future refactor
    # reintroduces error-level logging.
    (
        "api.exception_handlers",
        (
            "AUTHENTICATIONERROR:",
            "AUTHENTICATION_ERROR:",
            "AUTHORIZATIONERROR:",
            "AUTHORIZATION_ERROR:",
            "VALIDATION_ERROR:",
            "NOT_FOUND:",
            "NOTFOUND:",
            "CONFLICT:",
            "FORBIDDEN:",
            "RATE_LIMIT_EXCEEDED:",
        ),
    ),
)


def _event_message(event: dict[str, Any]) -> str:
    """Extract the log message from a Sentry event in a format-agnostic way."""
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        formatted = logentry.get("formatted") or logentry.get("message")
        if isinstance(formatted, str):
            return formatted
    msg = event.get("message")
    if isinstance(msg, str):
        return msg
    return ""


def _should_drop_event(event: dict[str, Any]) -> bool:
    """Return True when an event matches the noise-suppression rules."""
    logger_name = event.get("logger")
    if not isinstance(logger_name, str):
        return False
    message = _event_message(event)
    for target_logger, prefixes in _EVENT_DROP_RULES:
        if logger_name != target_logger:
            continue
        for prefix in prefixes:
            if message.startswith(prefix):
                return True
    return False


def _scrub_request_pii(event: dict[str, Any]) -> None:
    """Strip body, cookies, query string, and PII headers from ``event["request"]`` in place.

    Query strings are dropped wholesale (SEC-9174 #35): some request paths carry
    sensitive material directly in the query string (tokens, auth codes), and
    no Sentry triage flow needs the raw query, so removal beats a param allowlist.
    """
    request = event.get("request")
    if not isinstance(request, dict):
        return
    request.pop("data", None)
    request.pop("cookies", None)
    if "query_string" in request:
        request["query_string"] = ""
    url = request.get("url")
    if isinstance(url, str):
        request["url"] = url.partition("?")[0]
    headers = request.get("headers")
    if isinstance(headers, dict):
        request["headers"] = {k: v for k, v in headers.items() if k.lower() not in _PII_HEADERS_LOWER}


def _scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Drop request body + PII headers, and suppress known-noisy log events.

    Order matters: the drop check runs first so noisy events do not even get
    their PII scrubbed (small CPU savings + clearer reasoning when reading
    the filter). PII scrubbing then runs on the events that survive.
    """
    if _should_drop_event(event):
        return None
    _scrub_request_pii(event)
    return event


def _scrub_transaction(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """``before_send_transaction`` hook (SEC-9174 #35).

    ``before_send`` only runs for error events — sampled transaction envelopes
    shipped ``request.query_string`` intact. Same PII scrub, no drop rules
    (the noise-suppression prefixes are log-event concepts).
    """
    _scrub_request_pii(event)
    return event


def init_sentry(mode: str | None = None) -> bool:
    """Initialize Sentry for SaaS. No-op for CE or missing DSN.

    Returns True when ``sentry_sdk.init`` was actually called.
    """
    if mode is None:
        # BE-1000c: read the LIVE env, not the api.app_state.GILJO_MODE constant
        # frozen at first module import. Under xdist that constant is poisoned to
        # whatever GILJO_MODE was set on a worker's first app_state import, which
        # a later CE test cannot un-freeze via os.environ — causing a flake.
        resolved_mode = os.environ.get("GILJO_MODE", "ce").lower()
    else:
        resolved_mode = mode
    if resolved_mode != "saas":
        return False

    dsn = os.environ.get("SENTRY_DSN_BACKEND")
    if not dsn:
        logger.warning(
            "SENTRY_DSN_BACKEND not set in %s mode — backend error tracking disabled",
            resolved_mode,
        )
        return False

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=resolved_mode,
        traces_sample_rate=0.1,
        sample_rate=1.0,
        send_default_pii=False,
        # SEC-9174 #35: exception frames must not capture local variables —
        # reset/verification flows hold plaintext tokens and secrets in locals.
        include_local_variables=False,
        integrations=[FastApiIntegration()],
        before_send=_scrub_event,
        before_send_transaction=_scrub_transaction,
    )
    logger.info("Sentry initialized (environment=%s)", resolved_mode)
    return True


def set_tenant_context(tenant_key: str | None, user_id: str | None = None) -> None:
    """Tag the current Sentry scope with tenant_key and (optionally) user id.

    Safe to call in any edition: import is local, no-op when sentry_sdk
    isn't installed or hasn't been initialized.
    """
    if not tenant_key:
        return
    try:
        import sentry_sdk
    except ImportError:
        return

    sentry_sdk.set_tag("tenant_key", tenant_key)
    if user_id:
        sentry_sdk.set_user({"id": user_id})
