# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


INSTALL_SH = Path(__file__).resolve().parents[2] / "scripts" / "install.sh"
MARKER = "install log redaction failed; raw log not persisted"
SECRET = "hunter2"
RAW_LINE = b"[step] connecting password=" + SECRET.encode() + b" \xff\xfe bad-byte line\n"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _persist_install_log_source() -> str:
    source = INSTALL_SH.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^persist_install_log\(\) \{\n.*?^\}\n", source, re.DOTALL | re.MULTILINE)
    assert match, "persist_install_log() not found in scripts/install.sh"
    return match.group(0)


def _run_persist(tmp_path: Path, *, failing_sed: bool) -> tuple[Path, Path]:
    temp_log = tmp_path / "tmp-install.log"
    temp_log.write_bytes(RAW_LINE)
    target = tmp_path / "target"
    target.mkdir()

    env = dict(os.environ)
    if failing_sed:
        shim_dir = tmp_path / "shim"
        shim_dir.mkdir()
        shim = shim_dir / "sed"
        shim.write_text("#!/bin/sh\nexit 1\n")
        shim.chmod(0o755)
        env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"

    script = f'INSTALL_LOG_TMP="{temp_log}"\nRESOLVED_TARGET_DIR="{target}"\n{_persist_install_log_source()}\npersist_install_log\n'
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    return target / "install.log", temp_log


def test_working_sed_redacts_secret(tmp_path):
    install_log, _ = _run_persist(tmp_path, failing_sed=False)
    text = install_log.read_bytes()
    assert SECRET.encode() not in text
    assert b"***REDACTED***" in text


def test_failed_redaction_persists_only_the_marker(tmp_path):
    install_log, _ = _run_persist(tmp_path, failing_sed=True)
    text = install_log.read_bytes()
    assert SECRET.encode() not in text
    assert b"bad-byte" not in text
    assert text.decode().strip() == MARKER


@pytest.mark.parametrize("failing_sed", [False, True])
def test_temp_log_is_removed_afterwards(tmp_path, failing_sed):
    _, temp_log = _run_persist(tmp_path, failing_sed=failing_sed)
    assert not temp_log.exists()
