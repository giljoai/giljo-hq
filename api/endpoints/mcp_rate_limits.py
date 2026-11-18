# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import os
import time

from starlette.requests import Request
from starlette.types import Send

from api.endpoints.auth.session import _resolve_client_ip
from api.endpoints.mcp_transport import _INITIALIZE_METHOD, _send_raw_status
from api.middleware.auth_rate_limits import is_exempt_ip
from api.middleware.rate_limiter import is_test_bypass_enabled
from giljo_mcp.services.cache_backends import GLOBAL_RATE_LIMIT_BACKEND_NAME, get_cache_backend


logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60
_STORE_NAMESPACE = "_ratelimit"

DEFAULT_LIMITS: dict[str, int] = {
    "unauthenticated_per_ip": 120,
    "per_tenant": 1200,
    "initialize_per_tenant": 60,
}


def _clock() -> float:
    return time.time()


def limit_for(name: str) -> int:
    raw = os.getenv(f"GILJO_MCP_RL_{name.upper()}", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_LIMITS[name]


async def _over_budget(name: str, subject: str) -> bool:
    if is_test_bypass_enabled():
        return False
    slot = int(_clock()) // _WINDOW_SECONDS
    try:
        count = await get_cache_backend(GLOBAL_RATE_LIMIT_BACKEND_NAME).incr(
            _STORE_NAMESPACE, f"mcp:{name}:{subject}:{slot}", ttl_seconds=_WINDOW_SECONDS
        )
    except Exception:  # noqa: BLE001 - a store fault must cost throttling accuracy, never availability
        logger.warning("mcp_rate_limit_store_error budget=%s; admitting", name, exc_info=True)
        return False
    return count > limit_for(name)


async def _send_429(send: Send) -> None:
    retry_after = _WINDOW_SECONDS - int(_clock()) % _WINDOW_SECONDS
    await _send_raw_status(send, status=429, headers=[(b"retry-after", str(retry_after).encode("ascii"))])


async def refuse_unauthenticated_flood(request: Request, send: Send) -> bool:
    client_ip = _resolve_client_ip(request)
    if is_exempt_ip(client_ip) or not await _over_budget("unauthenticated_per_ip", client_ip):
        return False
    logger.warning("mcp_unauthenticated_rate_limited ip=%s", client_ip)
    await _send_429(send)
    return True


async def refuse_account_over_budget(tenant_key: str, method: str | None, send: Send) -> bool:
    over = await _over_budget("per_tenant", tenant_key)
    if not over and method == _INITIALIZE_METHOD:
        over = await _over_budget("initialize_per_tenant", tenant_key)
    if not over:
        return False
    logger.warning("mcp_account_rate_limited tenant=%s method=%s", tenant_key, method)
    await _send_429(send)
    return True
