# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Neutral in-process hub for announcements CE guards make about their own work.

A guard states a fact -- "this UPDATE could not be given a tenant predicate",
"the post-auth gate raised" -- and stops there. It does not decide what happens
next and it imports nothing in order to make anything happen. A deployment that
wants such an announcement routed somewhere registers an observer for it at
startup; a plain install registers none, so every publish is a no-op and this
module's only dependency is the standard library.

Deliberately SYNCHRONOUS. The tenant guard publishes from inside SQLAlchemy's
``do_orm_execute`` handler, which runs under both async (greenlet-driven) and
plain sync Sessions. An await-based bus would reach only the async half and
would silently drop the other one.

Best-effort by contract: :func:`publish_signal` never raises, so a broken or
slow observer can never affect the write path or the request path that
published. Payloads carry primitives only, so nothing here couples the
publisher to whatever an observer happens to be built on.

Fan-out, not replacement. A signal is an announcement, so any number of
observers may want it -- unlike a gate such as
``api/endpoints/mcp_auth_middleware.register_mcp_post_auth_gate``, where exactly
one answer makes sense and the last registration deliberately wins. Borrowing
replacement semantics here would let a second registration silently displace the
first, and nothing would report the loss. Registration is instead idempotent by
identity, so the repeated boot-time calls cannot double-announce either.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any


logger = logging.getLogger(__name__)

SignalObserver = Callable[[dict[str, Any]], None]

# The tenant guard met an UPDATE/DELETE it could not scope to the active tenant.
# Payload keys: models (list of model names), statement_type, path (may be None).
SIGNAL_UNSCOPED_WRITE = "tenant_guard.unscoped_write"

# The optional /mcp post-auth gate raised, so the request proceeded without its
# verdict. Payload key: tenant_key.
SIGNAL_POST_AUTH_GATE_FAILED = "mcp_auth.post_auth_gate_failed"

_observers: dict[str, list[SignalObserver]] = {}


def register_signal_observer(signal: str, observer: SignalObserver) -> None:
    """Add ``observer`` to ``signal``. Idempotent by identity: re-adding the same one is a no-op."""
    observers = _observers.setdefault(signal, [])
    if observer not in observers:
        observers.append(observer)


def clear_signal_observers(signal: str | None = None) -> None:
    """Remove the observers for ``signal``, or every observer when ``signal`` is None."""
    if signal is None:
        _observers.clear()
    else:
        _observers.pop(signal, None)


def get_signal_observers(signal: str) -> tuple[SignalObserver, ...]:
    """The observers currently installed for ``signal`` (a copy; callers must not mutate)."""
    return tuple(_observers.get(signal, ()))


def publish_signal(signal: str, payload: dict[str, Any]) -> None:
    """Announce ``signal`` to every installed observer. Never raises.

    Each observer is isolated: one that fails does not stop the ones after it.
    """
    for observer in tuple(_observers.get(signal, ())):
        try:
            observer(payload)
        except Exception:  # noqa: BLE001 - an observer must never affect the path that published
            logger.debug("signal observer failed for %s (non-blocking)", signal, exc_info=True)
