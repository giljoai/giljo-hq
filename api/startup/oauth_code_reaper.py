# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import logging

from api.app_state import APIState
from api.startup.metrics_flushers import log_task_death


logger = logging.getLogger(__name__)


async def cleanup_expired_oauth_codes_task(state: APIState):
    from giljo_mcp.services.oauth_service import OAuthService

    while True:
        await asyncio.sleep(86400)
        if not state.db_manager:
            continue
        try:
            async with state.db_manager.get_session_async() as session:
                service = OAuthService(db_session=session)
                removed = await service.cleanup_expired_codes()
            if removed:
                logger.info("OAuth code cleanup: %d expired/used code(s) removed", removed)
            else:
                logger.debug("OAuth code cleanup: nothing to remove")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error during OAuth code cleanup: %s", e, exc_info=True)


def start_oauth_code_cleanup_task(state: APIState) -> None:
    try:
        logger.info("Starting OAuth authorization code cleanup task...")
        task = asyncio.create_task(cleanup_expired_oauth_codes_task(state), name="oauth-code-cleanup")
        task.add_done_callback(log_task_death)
        state.oauth_code_cleanup_task = task
        logger.info("OAuth authorization code cleanup task started (runs daily)")
    except Exception as e:
        logger.error(f"Failed to start OAuth authorization code cleanup task: {e}", exc_info=True)
