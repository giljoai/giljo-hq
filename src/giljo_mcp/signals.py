# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any


logger = logging.getLogger(__name__)

SignalObserver = Callable[[dict[str, Any]], None]

SIGNAL_UNSCOPED_WRITE = "tenant_guard.unscoped_write"

SIGNAL_POST_AUTH_GATE_FAILED = "mcp_auth.post_auth_gate_failed"

_observers: dict[str, list[SignalObserver]] = {}


def register_signal_observer(signal: str, observer: SignalObserver) -> None:
    observers = _observers.setdefault(signal, [])
    if observer not in observers:
        observers.append(observer)


def clear_signal_observers(signal: str | None = None) -> None:
    if signal is None:
        _observers.clear()
    else:
        _observers.pop(signal, None)


def get_signal_observers(signal: str) -> tuple[SignalObserver, ...]:
    return tuple(_observers.get(signal, ()))


def publish_signal(signal: str, payload: dict[str, Any]) -> None:
    for observer in tuple(_observers.get(signal, ())):
        try:
            observer(payload)
        except Exception:  # noqa: BLE001 - an observer must never affect the path that published
            logger.debug("signal observer failed for %s (non-blocking)", signal, exc_info=True)
