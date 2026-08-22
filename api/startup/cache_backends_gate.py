# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SaaS cache-backend boot gate — fail-loud Redis policy (INF-3009c).

The rate limiter / OAuth idempotency layer already has a Redis-capable
`CacheBackend` seam (`giljo_mcp/services/cache_backends.py`), but nothing
enforced that a *configured* Redis was actually reachable: the previous
lifespan phase caught every exception from `install_redis_cache_backends`
and just logged a warning, leaving each worker on its own per-process dict —
the worst failure mode, because it looks like shared state is working when
it silently is not.

No-op for CE — see `saas/` for the exact configuration surface. Contract
(SaaS only):

- `REDIS_URL` unset: stay on the CE in-process backend. One INFO line states
  the mode. This is a legitimate SaaS operating mode today.
- `REDIS_URL` set and reachable: register the Redis-backed adapters, record
  the live client on `state` so `/health` can reuse it for a live ping.
- `REDIS_URL` set but unreachable at boot: raise. Callers must NOT catch this
  — it is meant to propagate out of `lifespan()` and abort uvicorn startup,
  the same fail-loud pattern as the Phase 0 license-validation check in
  `api/app.py`. Never silently degrade to per-process dicts: that would
  quietly re-introduce the multi-worker correctness bug INF-5074 fixed.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from api.app_state import APIState


logger = logging.getLogger("api.app")


async def install_saas_cache_backends(state: APIState, *, giljo_mode: str) -> None:
    """Install Redis-backed cache backends for SaaS, or record in-process mode.

    No-op when `giljo_mode != "saas"` — CE never touches Redis or imports
    anything under `giljo_mcp.saas`, so the Deletion Test holds regardless of
    whether the `saas/` tree exists.
    """
    if giljo_mode != "saas":
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
