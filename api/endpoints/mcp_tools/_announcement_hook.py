# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from giljo_mcp.services.cache_backends import FIRST_REPLY_TOLD_BACKEND_NAME, get_cache_backend


logger = logging.getLogger(__name__)

AnnouncementProvider = Callable[[str, str], Awaitable[dict[str, str] | None]]
SetupHintProvider = Callable[[str, str], Awaitable[str | None]]
ViewLinkBuilder = Callable[[str, dict[str, Any]], str | None]

MAX_TOLD_SESSIONS = 4096

SHARED_TOLD_TTL_SECONDS = 48 * 3600
SHARED_TOLD_WAIT_SECONDS = 0.5

_shared_told_failed = False
_provider: AnnouncementProvider | None = None
_hint_provider: SetupHintProvider | None = None
_view_link_builder: ViewLinkBuilder | None = None
_told: OrderedDict[str, None] = OrderedDict()


def install_announcement_provider(provider: AnnouncementProvider | None) -> None:
    global _provider  # noqa: PLW0603
    _provider = provider


def install_setup_hint_provider(provider: SetupHintProvider | None) -> None:
    global _hint_provider  # noqa: PLW0603
    _hint_provider = provider


def install_view_link_builder(builder: ViewLinkBuilder | None) -> None:
    global _view_link_builder  # noqa: PLW0603
    _view_link_builder = builder


def first_reply_hook_installed() -> bool:
    return _provider is not None or _hint_provider is not None


def reset_told_sessions() -> None:
    _told.clear()


def told_session_count() -> int:
    return len(_told)


def _request(ctx: Any) -> Any:
    return getattr(getattr(ctx, "request_context", None), "request", None)


def _session_id(request: Any) -> str | None:
    return request.headers.get("mcp-session-id")


async def _first_to_tell(tenant_key: str, session_key: str) -> bool:
    global _shared_told_failed  # noqa: PLW0603
    digest = hashlib.sha256(session_key.encode()).hexdigest()
    try:
        async with asyncio.timeout(SHARED_TOLD_WAIT_SECONDS):
            won = await get_cache_backend(FIRST_REPLY_TOLD_BACKEND_NAME).setnx(
                tenant_key, f"told:{digest}", "1", ttl_seconds=SHARED_TOLD_TTL_SECONDS
            )
    except Exception:  # noqa: BLE001
        if not _shared_told_failed:
            _shared_told_failed = True
            logger.warning("shared first-reply told-set unavailable; telling once per process", exc_info=True)
        return True
    _shared_told_failed = False
    return won


async def _announcement(provider: AnnouncementProvider, tenant_key: str, user_id: str) -> dict[str, str] | None:
    try:
        return await provider(tenant_key, user_id)
    except SQLAlchemyError:
        logger.warning("announcement notice lookup failed (non-blocking)", exc_info=True)
        return None


async def _setup_hint(tenant_key: str, user_id: str | None) -> str | None:
    provider = _hint_provider
    if provider is None or not user_id:
        return None
    try:
        return await provider(tenant_key, user_id)
    except Exception:  # noqa: BLE001
        logger.warning("setup hint lookup failed (non-blocking)", exc_info=True)
        return None


async def first_reply_meta(ctx: Any, tenant_key: str, resolve_user_id: Callable[[Any], str | None]) -> dict[str, Any]:
    provider = _provider
    if provider is None and _hint_provider is None:
        return {}
    request = _request(ctx)
    if request is None:
        return {}
    user_id = resolve_user_id(ctx)
    if not user_id:
        return {}
    key = _session_id(request) or f"user:{user_id}"
    if key in _told:
        _told.move_to_end(key)
        return {}
    _told[key] = None
    if len(_told) > MAX_TOLD_SESSIONS:
        _told.popitem(last=False)
    if not await _first_to_tell(tenant_key, key):
        return {}
    additions: dict[str, Any] = {}
    if provider is not None and (notice := await _announcement(provider, tenant_key, user_id)):
        additions["announcement"] = notice
    if hint := await _setup_hint(tenant_key, user_id):
        additions["setup_hint"] = hint
    return additions


async def add_setup_hint(result: Any, tenant_key: str, user_id: str | None) -> Any:
    if _hint_provider is None or not isinstance(result, dict):
        return result
    meta = result.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    if "setup_hint" not in meta and (hint := await _setup_hint(tenant_key, user_id)):
        meta["setup_hint"] = hint
        result["_meta"] = meta
    return result


def add_view_link(method_name: str, result: dict[str, Any]) -> None:
    builder = _view_link_builder
    if builder is None:
        return
    try:
        url = builder(method_name, result)
    except Exception:  # noqa: BLE001
        logger.warning("view link build failed for %s (non-blocking)", method_name, exc_info=True)
        return
    if not url:
        return
    result["view_url"] = url
    for key in ("message", "next_step"):
        if isinstance(result.get(key), str):
            sentence_break = "" if result[key].rstrip().endswith((".", "!", "?")) else "."
            result[key] = f"{result[key].rstrip()}{sentence_break} See it here: {url}"
            return
