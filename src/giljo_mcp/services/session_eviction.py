# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from giljo_mcp.models.auth import User
from giljo_mcp.services.oauth_refresh_service import revoke_all_for_user


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def evict_user_tokens(session: AsyncSession, user: User) -> int:
    await session.execute(
        select(User.id).where(User.id == str(user.id), User.tenant_key == user.tenant_key).with_for_update()
    )
    user.token_revocation_epoch = (user.token_revocation_epoch or 0) + 1
    return await revoke_all_for_user(session, user_id=str(user.id), tenant_key=user.tenant_key)


async def close_live_user_sockets(tenant_key: str, logger: logging.Logger) -> None:
    try:
        from api.app_state import state

        ws_manager = getattr(state, "websocket_manager", None)
        if ws_manager is not None:
            await ws_manager.disconnect_tenant(tenant_key, reason="account deactivated")
    except Exception:  # noqa: BLE001 - fire-and-forget; never fail the deactivation
        logger.warning("Failed to close live WebSocket sockets on deactivation", exc_info=True)
