# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import itertools


_SERIES_LOW = 1000
_SERIES_SPAN = 8000
_SERIES_STEP = 100
_SERIES_COUNTER = itertools.count()


def _series_for(index: int) -> int:
    lap, position = divmod(index % _SERIES_SPAN, _SERIES_SPAN // _SERIES_STEP)
    return _SERIES_LOW + position * _SERIES_STEP + lap


def next_series_number() -> int:
    return _series_for(next(_SERIES_COUNTER))


_THREAD_SERIAL_COUNTER = itertools.count()


def next_thread_serial() -> int:
    return _series_for(next(_THREAD_SERIAL_COUNTER))
