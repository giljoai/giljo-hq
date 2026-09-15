# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import itertools


_SERIES_COUNTER = itertools.count(1000)


def next_series_number() -> int:
    return next(_SERIES_COUNTER)
