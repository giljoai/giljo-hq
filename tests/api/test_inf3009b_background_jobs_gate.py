# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from api.startup import background_tasks as bt
from api.startup import oauth_code_reaper
from api.startup.background_jobs_gate import ENV_VAR, should_run_background_jobs


_TELEMETRY_LOOPS = {"sync_api_metrics_to_db", "sync_ws_metrics_to_db"}

_GATED_LOOPS = {
    "cleanup_expired_download_tokens",
    "scan_expiring_api_keys_task",
    "purge_old_notifications_task",
    "cleanup_expired_mcp_sessions_task",
    "cleanup_expired_oauth_codes_task",
}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        ("", True),
        ("   ", True),
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("on", True),
        ("yes", True),
        ("anything-else", True),
        ("0", False),
        ("false", False),
        ("False", False),
        ("no", False),
        ("off", False),
        ("  off  ", False),
    ],
)
def test_should_run_background_jobs_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(ENV_VAR, value)
    assert should_run_background_jobs() is expected


def _patch_create_task(monkeypatch):
    created: list[str] = []

    def fake_create_task(coro, *args, **kwargs):
        created.append(coro.cr_code.co_name)
        coro.close()
        return MagicMock(name="task")

    monkeypatch.setattr(bt.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(oauth_code_reaper.asyncio, "create_task", fake_create_task)
    return created


@pytest.mark.asyncio
async def test_gate_off_starts_only_per_worker_telemetry(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "off")
    monkeypatch.setenv("GILJO_MODE", "saas")
    created = _patch_create_task(monkeypatch)

    state = types.SimpleNamespace(db_manager=None, tenant_manager=None)
    await bt.init_background_tasks(state)

    assert set(created) == _TELEMETRY_LOOPS
    assert not (_GATED_LOOPS & set(created))


@pytest.mark.asyncio
async def test_gate_on_starts_all_loops(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv("GILJO_MODE", "saas")
    created = _patch_create_task(monkeypatch)

    state = types.SimpleNamespace(db_manager=None, tenant_manager=None)
    await bt.init_background_tasks(state)

    started = set(created)
    assert started >= _TELEMETRY_LOOPS
    assert started >= _GATED_LOOPS


@pytest.mark.asyncio
async def test_gate_default_is_on_when_unset(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv("GILJO_MODE", "saas")
    created = _patch_create_task(monkeypatch)

    state = types.SimpleNamespace(db_manager=None, tenant_manager=None)
    await bt.init_background_tasks(state)

    assert "cleanup_expired_download_tokens" in created
