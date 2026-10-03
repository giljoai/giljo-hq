# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.platform_registry import Platform
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.protocol_sections.chapters_coordination import _build_thread_loop_directive


def append_loop_directive(full_protocol: str, active: bool, preset: Platform | None = None) -> str:
    if not active:
        return full_protocol
    return full_protocol + "\n" + _build_thread_loop_directive(preset)


async def compose_loop_directive(
    full_protocol: str,
    open_session: Any,
    tenant_key: str,
    agent_id: str,
    logger: logging.Logger | None = None,
    preset: Platform | None = None,
) -> str:
    try:
        async with open_session(tenant_key) as session:
            active = await CommThreadRepository().has_active_loop_directive(session, tenant_key, agent_id)
    except Exception:  # noqa: BLE001 - resilience: never block a mission on this read
        if logger is not None:
            logger.warning("[LOOP-DIRECTIVE] Failed to read loop-directive state")
        active = False
    return append_loop_directive(full_protocol, active, preset)
