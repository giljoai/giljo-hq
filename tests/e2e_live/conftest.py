# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

import pytest


E2E_LIVE_ENV = "GILJO_E2E_LIVE"
E2E_BASE_URL_ENV = "GILJO_E2E_BASE_URL"

DEFAULT_TIMEOUT = float(os.environ.get("GILJO_E2E_TIMEOUT", "15"))


def _live_enabled() -> bool:
    return os.environ.get(E2E_LIVE_ENV) == "1"


_HERE = Path(__file__).resolve().parent


def _is_live_item(item) -> bool:
    try:
        item_path = Path(str(item.fspath)).resolve()
    except Exception:
        return False
    return item_path == _HERE or _HERE in item_path.parents


def pytest_collection_modifyitems(config, items):
    if _live_enabled():
        return
    skip = pytest.mark.skip(reason=f"live E2E disabled ({E2E_LIVE_ENV} != '1')")
    for item in items:
        if _is_live_item(item):
            item.add_marker(skip)


class Target(NamedTuple):
    base_url: str
    scheme: str
    host: str
    port: int


@pytest.fixture(scope="session")
def target() -> Target:
    raw = os.environ.get(E2E_BASE_URL_ENV, "").strip()
    if not raw:
        pytest.skip(reason=f"{E2E_BASE_URL_ENV} not set (no committed default host)")
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        pytest.skip(reason=f"{E2E_BASE_URL_ENV} is not a valid http(s) URL: {raw!r}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return Target(base_url=raw.rstrip("/"), scheme=parts.scheme, host=parts.hostname, port=port)


@pytest.fixture(scope="session")
def http_client(target):
    import httpx

    with httpx.Client(
        base_url=target.base_url,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=False,
    ) as client:
        yield client
