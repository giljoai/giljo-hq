# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[2]


def test_root_file_between_api_files_keeps_tests_api_one_package() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:xdist",
            "--no-cov",
            "tests/api/test_tsk9621_code_challenge_cap.py",
            "tests/test_app_state_restored_between_tests.py",
            "tests/api/test_be9620_oauth_authorize_state_cap.py",
        ],
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert result.stdout.count("<Package api>") == 1, result.stdout[-2000:]
