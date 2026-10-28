# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError


logger = logging.getLogger(__name__)

AnnouncementProvider = Callable[[str, str], Awaitable[dict[str, str] | None]]

MAX_TOLD_SESSIONS = 4096

_provider: AnnouncementProvider | None = None
_told: OrderedDict[str, None] = OrderedDict()


def install_announcement_provider(provider: AnnouncementProvider | None) -> None:
    global _provider  # noqa: PLW0603
    _provider = provider


def reset_told_sessions() -> None:
    _told.clear()


def told_session_count() -> int:
    return len(_told)


def _request(ctx: Any) -> Any:
    return getattr(getattr(ctx, "request_context", None), "request", None)


def _session_id(request: Any) -> str | None:
    return request.headers.get("mcp-session-id")


async def announcement_notice(
    ctx: Any, tenant_key: str, resolve_user_id: Callable[[Any], str | None]
) -> dict[str, str] | None:
    provider = _provider
    if provider is None:
        return None
    request = _request(ctx)
    if request is None:
        return None
    user_id = resolve_user_id(ctx)
    if not user_id:
        return None
    key = _session_id(request) or f"user:{user_id}"
    if key in _told:
        _told.move_to_end(key)
        return None
    _told[key] = None
    if len(_told) > MAX_TOLD_SESSIONS:
        _told.popitem(last=False)
    try:
        return await provider(tenant_key, user_id)
    except SQLAlchemyError:
        logger.warning("announcement notice lookup failed (non-blocking)", exc_info=True)
        return None
