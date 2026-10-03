# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
_DB_ENV = ("DB_PASSWORD", "DATABASE_URL", "POSTGRES_PASSWORD", "POSTGRES_OWNER_PASSWORD", "POSTGRES_SUPERUSER_PASSWORD")


def test_the_app_imports_with_no_database_configuration():
    env = {k: v for k, v in os.environ.items() if k not in _DB_ENV}
    env.update(
        {
            "GILJO_MODE": "",
            "TESTING": "true",
            "PYTHONPATH": os.pathsep.join([str(REPO_ROOT), str(REPO_ROOT / "src")]),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", "import api.app"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
