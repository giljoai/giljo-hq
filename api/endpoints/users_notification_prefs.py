# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.endpoints.dependencies import get_user_service
from api.endpoints.users_models import NotificationPreferencesUpdate
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services import UserService


router = APIRouter()


@router.get("/me/settings/notification-preferences")
async def get_notification_preferences(
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get the current user's notification preferences.

    The stored value is MERGED OVER the defaults, so a row written
    before the notification-model keys existed still reads back complete --
    that is this column's answer to the old-shape question, and it needs no
    migration.

    A merge rather than a validate-on-read, deliberately: validation would
    raise on any unexpected key and turn a read into a 500, which is a bad
    trade for a display preference. A merge cannot fail, fills what is missing,
    and leaves anything unrecognised alone.

    This is a read and stays one: the filled shape is NEVER written back. The
    new keys reach a row the first time that user changes one, so no existing
    data is touched and a CE self-hoster needs no operator to clean anything up.
    """
    from giljo_mcp.config.defaults import DEFAULT_NOTIFICATION_PREFERENCES

    stored = current_user.notification_preferences or {}
    prefs = {**DEFAULT_NOTIFICATION_PREFERENCES, **stored}
    return {"notification_preferences": prefs}


@router.put("/me/settings/notification-preferences")
async def update_notification_preferences(
    payload: NotificationPreferencesUpdate,
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
) -> dict[str, Any]:
    """Update the current user's notification preferences.

    The fields, and why decisions / your-turn / mentions are deliberately not
    among them: see ``NotificationPreferencesUpdate`` in ``users_models.py``.
    """
    prefs = await user_service.update_notification_preferences(
        user_id=current_user.id,
        payload=payload.model_dump(exclude_unset=True),
    )

    return {"notification_preferences": prefs}
