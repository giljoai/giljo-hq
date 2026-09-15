# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "hub.baton_handover"


def handover_dedupe_key(thread_id: str) -> str:
    return f"{NOTIFICATION_TYPE}:{thread_id}"


async def notify_baton_handed_to_operator(
    *,
    db_manager: Any,
    session: Any,
    tenant_key: str,
    user_id: str,
    thread_id: str,
    chat_id: str,
    handed_by: str | None,
) -> None:
    try:
        from giljo_mcp.services.notification_service import NotificationService

        service = NotificationService(db_manager=db_manager, session=session)
        await service.create(
            tenant_key=tenant_key,
            user_id=user_id,
            notification_type=NOTIFICATION_TYPE,
            severity="info",
            title="It's your call",
            body=(f"{handed_by} is waiting on you in {chat_id}" if handed_by else f"{chat_id} — waiting on you"),
            dedupe_key=handover_dedupe_key(thread_id),
            surface="bell",
            cta_label="Open",
            cta_route="Hub",
            dismissible=True,
            payload={"thread_id": thread_id, "chat_id": chat_id, "handed_by": handed_by},
        )
    except Exception:  # noqa: BLE001 — the baton is committed; the bell is the nicety
        logger.warning("BE-9296a handover notification emit failed for thread %s (non-fatal)", thread_id, exc_info=True)
