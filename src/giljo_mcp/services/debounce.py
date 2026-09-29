# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import threading
import time
from collections import OrderedDict


_LAST_FIRED: dict[str, OrderedDict[str, float]] = {}
_LOCK = threading.Lock()

_MAX_KEYS_PER_NAMESPACE = 2048


def should_run(namespace: str, key: str, interval_seconds: float) -> bool:
    now = time.monotonic()
    with _LOCK:
        bucket = _LAST_FIRED.setdefault(namespace, OrderedDict())
        last = bucket.get(key)
        if last is not None and (now - last) < interval_seconds:
            return False
        bucket[key] = now
        bucket.move_to_end(key)
        if len(bucket) > _MAX_KEYS_PER_NAMESPACE:
            bucket.popitem(last=False)
        return True


def reset(namespace: str | None = None) -> None:
    with _LOCK:
        if namespace is None:
            _LAST_FIRED.clear()
        else:
            _LAST_FIRED.pop(namespace, None)
