# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from api.app_state import APIState


logger = logging.getLogger(__name__)


async def init_health_monitor(state: APIState) -> None:
    try:
        logger.info("Initializing agent health monitoring...")

        health_config_dict = state.config.get_nested("health_monitoring", {})

        if health_config_dict.get("enabled", True):
            from giljo_mcp.monitoring.agent_health_monitor import AgentHealthMonitor
            from giljo_mcp.monitoring.health_config import HealthCheckConfig

            timeout_config = health_config_dict.get("timeouts", {})
            health_config = HealthCheckConfig(
                waiting_timeout_minutes=timeout_config.get("waiting_timeout", 2),
                active_no_progress_minutes=timeout_config.get("active_no_progress", 5),
                heartbeat_timeout_minutes=timeout_config.get("heartbeat_timeout", 10),
                timeout_overrides={
                    "orchestrator": timeout_config.get("orchestrator", 15),
                    "implementer": timeout_config.get("implementer", 10),
                    "tester": timeout_config.get("tester", 8),
                    "analyzer": timeout_config.get("analyzer", 5),
                    "reviewer": timeout_config.get("reviewer", 6),
                    "documenter": timeout_config.get("documenter", 5),
                },
                scan_interval_seconds=health_config_dict.get("scan_interval_seconds", 300),
                auto_fail_on_timeout=health_config_dict.get("auto_fail_on_timeout", False),
                notify_orchestrator=health_config_dict.get("notify_orchestrator", True),
            )

            state.health_monitor = AgentHealthMonitor(
                db_manager=state.db_manager,
                ws_manager=state.websocket_manager,
                config=health_config,
            )

            await state.health_monitor.start()
            logger.info(f"Agent health monitoring started (scan interval: {health_config.scan_interval_seconds}s)")
        else:
            logger.info("Agent health monitoring disabled in configuration")
    except Exception:
        logger.exception("Optional startup phase [health_monitor] failed; running without agent health monitoring")
        state.degraded_services.append("health_monitor")
