# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import types

import pytest

from api.startup.multiworker_guard_gate import (
    assert_multiworker_prerequisites,
    log_deploy_posture,
)


@pytest.fixture
def posture_caplog(caplog):
    caplog.set_level(logging.INFO, logger="api.app")
    return caplog


def _posture_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("Deploy posture:")]


def test_declared_policy_and_worker_count_logged(monkeypatch, posture_caplog):
    monkeypatch.setenv("GILJO_RESTART_POLICY", "ALWAYS")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")

    log_deploy_posture()

    (line,) = _posture_lines(posture_caplog)
    assert "restart_policy=ALWAYS" in line
    assert "workers=4" in line


def test_unset_policy_self_describes(monkeypatch, posture_caplog):
    monkeypatch.delenv("GILJO_RESTART_POLICY", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    log_deploy_posture()

    (line,) = _posture_lines(posture_caplog)
    assert "restart_policy=unset" in line
    assert "workers=1" in line


def test_boot_gate_emits_posture_on_single_worker_path(monkeypatch, posture_caplog):
    monkeypatch.setenv("GILJO_RESTART_POLICY", "ALWAYS")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    assert_multiworker_prerequisites(
        types.SimpleNamespace(websocket_broker=None, redis_mode="unset"),
        giljo_mode="ce",
    )

    (line,) = _posture_lines(posture_caplog)
    assert "restart_policy=ALWAYS" in line
    assert "workers=1" in line


def test_boot_gate_emits_posture_before_multiworker_refusal(monkeypatch, posture_caplog):
    monkeypatch.setenv("GILJO_RESTART_POLICY", "ALWAYS")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.setenv("GILJO_RUN_BACKGROUND_JOBS", "on")

    with pytest.raises(RuntimeError):
        assert_multiworker_prerequisites(
            types.SimpleNamespace(websocket_broker=None, redis_mode="unset"),
            giljo_mode="ce",
        )

    (line,) = _posture_lines(posture_caplog)
    assert "restart_policy=ALWAYS" in line
    assert "workers=2" in line
