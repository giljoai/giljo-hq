# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from api.app_state import APIState


logger = logging.getLogger(__name__)


async def init_event_bus(state: APIState) -> None:
    logger.info("=" * 70)
    logger.info("STARTING EVENT BUS INITIALIZATION")
    logger.info("=" * 70)
    try:
        logger.info("Step 1: About to import EventBus...")
        from api.event_bus import EventBus

        logger.info("Step 1: EventBus imported successfully")

        logger.info("Step 2: About to import WebSocketEventListener...")
        from api.websocket_event_listener import WebSocketEventListener

        logger.info("Step 2: WebSocketEventListener imported successfully")

        logger.info("Step 3: Creating EventBus instance...")
        state.event_bus = EventBus()
        logger.info(f"Step 3: EventBus created: {state.event_bus}")
        logger.info(f"Step 3: EventBus type: {type(state.event_bus)}")
        logger.info("Event bus initialized successfully")

        logger.info("Step 4: Creating WebSocketEventListener instance...")
        ws_listener = WebSocketEventListener(state.event_bus, state.websocket_manager)
        logger.info(f"Step 4: WebSocketEventListener created: {ws_listener}")

        logger.info("Step 5: Starting WebSocketEventListener (registering handlers)...")
        await ws_listener.start()
        logger.info("Step 5: WebSocket event listener handlers registered")
        logger.info("WebSocket event listener registered successfully")
        logger.info("=" * 70)
        logger.info("EVENT BUS INITIALIZATION COMPLETE")
        logger.info("=" * 70)
    except Exception as e:
        logger.exception("=" * 70)
        logger.exception("FAILED TO INITIALIZE EVENT BUS")
        logger.exception("=" * 70)
        logger.exception(f"Exception type: {type(e).__name__}")
        logger.exception(f"Exception args: {e.args}")
        logger.warning("Optional startup phase [event_bus] failed: %s — running in degraded mode", e)
        state.event_bus = None
