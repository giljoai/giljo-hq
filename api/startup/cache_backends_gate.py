# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from api.app_state import APIState


logger = logging.getLogger("api.app")


async def install_saas_cache_backends(state: APIState, *, giljo_mode: str) -> None:
    is_saas = giljo_mode == "saas"
    if not is_saas:
        return

    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        state.redis_mode = "unset"
        logger.info("Cache backend mode: in-process (REDIS_URL not set)")
        return

    import importlib

    from redis.exceptions import RedisError

    cache_mod = importlib.import_module("giljo_mcp.saas.services.redis_cache_backend")
    try:
        client = await cache_mod.verify_redis_reachable(redis_url)
    except (RedisError, OSError, TimeoutError, ConnectionError) as exc:
        raise RuntimeError(
            "REDIS_URL is set but Redis is unreachable at boot "
            f"({exc}). Refusing to start silently degraded to per-process "
            "cache state (INF-3009c fail-loud policy) — fix Redis "
            "connectivity or unset REDIS_URL."
        ) from exc

    cache_mod.install_redis_cache_backends(redis_url, client=client)
    state.redis_mode = "connected"
    state.redis_client = client
    logger.info("Cache backend mode: redis (connectivity verified at boot)")
