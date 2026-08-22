# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9192 — boot "Deploy posture" log line (restart policy + worker count).

Failing layer this regression-locks: the 2026-07-16 prod outage (platform
SIGTERM -> clean exit -> ON_FAILURE treated it terminal) had to be diagnosed by
reconstructing the restart policy and worker posture from deployment platform
state after the fact — nothing in the boot log stated either. ``log_deploy_posture`` puts
both in every boot log, and it must fire on the SAME path every boot takes
(``assert_multiworker_prerequisites``, lifespan Phase 8.55, both editions),
including the single-worker early-return branch.

``GILJO_RESTART_POLICY`` is exported by the deployment start command, so
``restart_policy=unset`` deliberately self-describes a process NOT launched by
that start command (CE, local dev, or dashboard override drift).

Parallel-safe: env via monkeypatch only, no DB, no module-level mutable state.
"""

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
    """Deployment posture: the platform's start command exported both vars -> the line states both."""
    monkeypatch.setenv("GILJO_RESTART_POLICY", "ALWAYS")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")

    log_deploy_posture()

    (line,) = _posture_lines(posture_caplog)
    assert "restart_policy=ALWAYS" in line
    assert "workers=4" in line


def test_unset_policy_self_describes(monkeypatch, posture_caplog):
    """CE / local dev / dashboard-override drift: no exported policy -> 'unset'
    (a signal the config-as-code startCommand did not launch this process)."""
    monkeypatch.delenv("GILJO_RESTART_POLICY", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    log_deploy_posture()

    (line,) = _posture_lines(posture_caplog)
    assert "restart_policy=unset" in line
    assert "workers=1" in line


def test_boot_gate_emits_posture_on_single_worker_path(monkeypatch, posture_caplog):
    """The line must ride the gate every boot already runs — including the
    single-worker early return, where the gate is otherwise silent."""
    monkeypatch.setenv("GILJO_RESTART_POLICY", "ALWAYS")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    # Single worker: any config is acceptable to the fence; must not raise.
    assert_multiworker_prerequisites(
        types.SimpleNamespace(websocket_broker=None, redis_mode="unset"),
        giljo_mode="ce",
    )

    (line,) = _posture_lines(posture_caplog)
    assert "restart_policy=ALWAYS" in line
    assert "workers=1" in line


def test_boot_gate_emits_posture_before_multiworker_refusal(monkeypatch, posture_caplog):
    """Even a boot the fence ABORTS logs its posture first — that refusal log is
    exactly the incident-forensics moment the line exists for."""
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
