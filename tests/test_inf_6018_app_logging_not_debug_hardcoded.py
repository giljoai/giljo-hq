# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from pathlib import Path


_APP_PY = Path(__file__).resolve().parent.parent / "api" / "app.py"


def _source() -> str:
    return _APP_PY.read_text(encoding="utf-8")


def test_app_does_not_hardcode_debug_level() -> None:
    src = _source()
    assert "level=logging.DEBUG" not in src, (
        "api/app.py hardcodes logging.DEBUG at import time. This overrides "
        "LOG_LEVEL and uvicorn --log-level, forcing DEBUG on prod. Derive the "
        "level from os.getenv('LOG_LEVEL', 'INFO') instead (INF-6018)."
    )


def test_app_logging_honors_log_level_env() -> None:
    src = _source()
    assert 'os.getenv("LOG_LEVEL"' in src or "os.getenv('LOG_LEVEL'" in src, (
        "api/app.py must resolve its log level from the LOG_LEVEL env var "
        "(default INFO), mirroring giljo_mcp.logging (INF-6018)."
    )
