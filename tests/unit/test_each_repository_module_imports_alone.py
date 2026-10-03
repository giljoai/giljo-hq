# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[2]
_MODULES = sorted(
    f"giljo_mcp.repositories.{path.stem}"
    for path in (_REPO / "src" / "giljo_mcp" / "repositories").glob("*.py")
    if path.stem != "__init__"
)


@pytest.mark.parametrize("module", _MODULES)
def test_repository_module_imports_alone(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        cwd=_REPO,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr.strip().splitlines()[-1]
