# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_app_state(mode: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GILJO_MODE": mode}
    return subprocess.run(
        [sys.executable, "-c", "import api.app_state as s; print(s.GILJO_MODE)"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("mode", ["sass", "demo", "saas-production"])
def test_an_unknown_mode_refuses_to_start(mode):
    result = _import_app_state(mode)
    assert result.returncode != 0, f"GILJO_MODE={mode} booted: {result.stdout!r}"
    assert "GILJO_MODE" in result.stderr


@pytest.mark.parametrize(("mode", "expected"), [("ce", "ce"), ("saas", "saas"), ("SaaS", "saas"), ("", "")])
def test_known_modes_still_start(mode, expected):
    result = _import_app_state(mode)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
