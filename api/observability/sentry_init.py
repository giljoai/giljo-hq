# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


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


_EVENT_DROP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "giljo_mcp.auth.dependencies",
        (
            "[AUTH] FAILED",
            "[AUTH] anonymous",
        ),
    ),
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
    if _should_drop_event(event):
        return None
    _scrub_request_pii(event)
    return event


def _scrub_transaction(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    _scrub_request_pii(event)
    return event


def init_sentry(mode: str | None = None) -> bool:
    if mode is None:
        resolved_mode = os.environ.get("GILJO_MODE", "ce").lower()
    else:
        resolved_mode = mode
    is_saas = resolved_mode == "saas"
    if not is_saas:
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
        include_local_variables=False,
        integrations=[FastApiIntegration()],
        before_send=_scrub_event,
        before_send_transaction=_scrub_transaction,
    )
    logger.info("Sentry initialized (environment=%s)", resolved_mode)
    return True


def set_tenant_context(tenant_key: str | None, user_id: str | None = None) -> None:
    if not tenant_key:
        return
    try:
        import sentry_sdk
    except ImportError:
        return

    sentry_sdk.set_tag("tenant_key", tenant_key)
    if user_id:
        sentry_sdk.set_user({"id": user_id})
