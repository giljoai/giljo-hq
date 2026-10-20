# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Literal


SYNC_SCHEME = "postgresql+psycopg2"
ASYNC_SCHEME = "postgresql+asyncpg"

_TARGET_SCHEME = {"sync": SYNC_SCHEME, "async": ASYNC_SCHEME}

_REWRITABLE_SCHEMES = frozenset({"postgres", "postgresql", SYNC_SCHEME, ASYNC_SCHEME})


def normalize_database_url(url: str, driver: Literal["sync", "async"]) -> str:
    target = _TARGET_SCHEME.get(driver)
    if target is None:
        raise ValueError(f"driver must be 'sync' or 'async', got {driver!r}")
    scheme, separator, rest = url.partition("://")
    if not separator or scheme.lower() not in _REWRITABLE_SCHEMES:
        return url
    return f"{target}://{rest}"
