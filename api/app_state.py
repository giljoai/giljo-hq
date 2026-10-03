# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import os
from datetime import date
from typing import Any


_mode = os.environ.get("GILJO_MODE", "ce").lower()
if _mode not in ("ce", "saas", ""):
    raise RuntimeError(f"GILJO_MODE={_mode!r} is not a known edition; set it to 'ce' or 'saas'.")
GILJO_MODE = _mode


def member_management_enabled() -> bool:
    return False


class APIState:

    def __init__(self):
        self.db_manager: Any = None
        self.config: Any = None
        self.auth: Any = None
        self.tenant_manager: Any = None
        self.tool_accessor: Any = None
        self.websocket_manager: Any = None
        self.websocket_broker: Any = None
        self.event_bus: Any = None
        self.connections: dict[str, Any] = {}
        self.heartbeat_task: asyncio.Task | None = None
        self.cleanup_task: asyncio.Task | None = None
        self.metrics_sync_task: asyncio.Task | None = None
        self.api_key_expiry_task: asyncio.Task | None = None
        self.notification_purge_task: asyncio.Task | None = None
        self.mcp_session_cleanup_task: asyncio.Task | None = None
        self.oauth_code_cleanup_task: asyncio.Task | None = None
        self.health_monitor: Any = None
        self.health_monitor_task: asyncio.Task | None = None
        self.silence_detector: Any = None
        self.api_call_count: dict[str, int] = {}
        self.mcp_call_count: dict[str, int] = {}
        self.mcp_tool_call_count: dict[tuple[str, str, date], int] = {}
        self.system_prompt_service: Any = None
        self.startup_complete: bool = False
        self.degraded_services: list[str] = []
        self.license: Any = None
        self.pending_migration: bool | None = False
        self.update_available: dict | None = None
        self.health_detail: dict[str, str] = {}
        self.update_checker_task: asyncio.Task | None = None
        self.system_banner_refresh_task: asyncio.Task | None = None
        self.redis_mode: str = "unset"
        self.redis_client: Any = None


state = globals().get("state") or APIState()
