# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The durable record of a hand-off to the operator (BE-9296a).

FE-9289c already drops a bell entry when a baton lands on the operator, but it is
built from the live WebSocket event and stored client-side. So a hand-off that
arrived while the dashboard was closed was never seen at all, and one seen on the
laptop did not exist on the phone. The agent had done everything right and the
request still evaporated.

This writes the SERVER row, which is what survives a reload and reaches a second
browser. The frontend already renders server notification rows; only the emitter
was missing.

Best-effort by construction: the baton write is the load-bearing act and is already
committed by the time this runs. A bell that fails to appear is a degraded
notification, not a lost hand-off — ``get_my_turn`` and the thread itself still show
it — so this must never unwind or fail the caller.

Edition Scope: CE.
"""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "hub.baton_handover"


def handover_dedupe_key(thread_id: str) -> str:
    """One OPEN row per thread.

    ``NotificationService.create`` de-duplicates against open rows, so a thread that
    bounces between an agent and the operator several times leaves ONE unread bell
    entry rather than a stack of identical ones. Once the operator resolves it, the
    next hand-off on that thread opens a fresh row.
    """
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
    """Write the durable bell row for a baton that landed on the operator.

    MUST be called only AFTER the baton write has committed, for the same reason the
    wake signal is: a row pointing at a hand-off that then rolled back would tell the
    operator to go look at something that never happened.

    No ``websocket_manager`` is threaded in, deliberately. This module lives in the
    service layer, and reaching into ``api.app_state`` for the live socket would make
    a service depend on the transport. The live half is already covered — the
    ``thread_update`` event fires on the same hand-off — so what is genuinely missing,
    and all this adds, is the durable row.
    """
    try:
        from giljo_mcp.services.notification_service import NotificationService

        # Thread the test session when present so a test does not persist a stray row
        # on a real session; production passes None and the service opens its own.
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
