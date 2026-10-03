# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.app_state import APIState


def _state() -> APIState:
    state = APIState()
    state.config = MagicMock()
    state.config.get_nested = MagicMock(
        side_effect=lambda key, default=None: {} if key == "health_monitoring" else default
    )
    state.db_manager = MagicMock()
    return state


@pytest.mark.asyncio
async def test_health_monitor_failure_is_named(monkeypatch):
    from api.startup.health_monitor import init_health_monitor
    from giljo_mcp.monitoring import agent_health_monitor

    async def _boom(self):
        raise RuntimeError("scheduler refused")

    monkeypatch.setattr(agent_health_monitor.AgentHealthMonitor, "start", _boom)
    state = _state()
    await init_health_monitor(state)
    assert "health_monitor" in state.degraded_services


@pytest.mark.asyncio
async def test_silence_detector_failure_is_named(monkeypatch):
    from api.startup.silence_detector import init_silence_detector
    from giljo_mcp.services import silence_detector

    async def _boom(self):
        raise RuntimeError("scheduler refused")

    monkeypatch.setattr(silence_detector.SilenceDetector, "start", _boom)
    state = _state()
    await init_silence_detector(state)
    assert "silence_detector" in state.degraded_services


@pytest.mark.asyncio
async def test_setup_validation_failure_is_named(monkeypatch):
    from api.startup.validation import init_validation
    from giljo_mcp.setup import state_manager

    def _boom(*args, **kwargs):
        raise RuntimeError("state file unreadable")

    monkeypatch.setattr(state_manager, "SetupStateManager", SimpleNamespace(get_instance=_boom))
    state = _state()
    await init_validation(state)
    assert "setup_validation" in state.degraded_services


@pytest.mark.asyncio
async def test_update_checker_start_failure_is_named(monkeypatch):
    from api.startup import update_checker

    async def _boom(*args, **kwargs):
        raise RuntimeError("git exploded")

    monkeypatch.delenv("GILJO_MODE", raising=False)
    monkeypatch.setattr(update_checker, "_is_git_repo", _boom)
    state = _state()
    assert await update_checker.start_update_checker(state) is None
    assert "update_checker" in state.degraded_services
