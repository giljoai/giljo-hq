# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from api.app_state import APIState


logger = logging.getLogger(__name__)


async def init_silence_detector(state: APIState) -> None:
    try:
        logger.info("Initializing silence detector...")

        from giljo_mcp.services.silence_detector import SilenceDetector

        state.silence_detector = SilenceDetector(
            db_manager=state.db_manager,
            ws_manager=state.websocket_manager,
            scan_interval_seconds=60,
        )

        await state.silence_detector.start()
        logger.info("Silence detector started (scan interval: 60s)")

    except Exception as _exc:
        logger.exception("Failed to start silence detector")
        logger.warning("Continuing without silence detection")
