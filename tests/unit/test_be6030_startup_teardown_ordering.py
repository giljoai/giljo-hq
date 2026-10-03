# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def test_be6030_stop_services_called_before_start_api_server(tmp_path):
    import startup

    call_order: list[str] = []

    def _record_stop_services():
        call_order.append("stop_services")
        return 0

    def _record_start_api_server(verbose=False, api_port=None):
        call_order.append("start_api_server")
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        return mock_proc


    patches = [
        patch.object(startup, "check_dependencies", return_value=True),
        patch.object(startup, "install_requirements", return_value=True),
        patch.object(startup, "_patch_env_from_config", return_value=None),
        patch.object(startup, "run_database_migrations", return_value=True),
        patch.object(startup, "check_database_connectivity", return_value=(True, None)),
        patch.object(startup, "seed_default_settings", return_value=None),
        patch.object(startup, "check_first_run", return_value=(False, MagicMock())),
        patch.object(startup, "get_config_ports", return_value=(8000, 5173)),
        patch.object(startup, "verify_install_consistency", return_value=[]),
        patch.object(startup, "stop_services", side_effect=_record_stop_services),
        patch.object(startup, "is_port_available", return_value=True),
        patch.object(startup, "_single_instance_lock", side_effect=lambda *a, **k: contextlib.nullcontext()),
        patch.object(startup, "start_api_server", side_effect=_record_start_api_server),
        patch.object(startup, "start_frontend_server", return_value=MagicMock()),
        patch.object(startup, "wait_for_api_ready", return_value=True),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
        patch.object(sys, "argv", ["startup.py"]),
        patch("shutil.which", return_value=None),
        patch.object(startup, "open_browser", return_value=None) if hasattr(startup, "open_browser") else None,
    ]

    active_patches = [p for p in patches if p is not None]

    for p in active_patches:
        p.start()

    try:
        startup.run_startup(
            no_migrations=True,
            no_browser=True,
        )
    finally:
        for p in active_patches:
            p.stop()

    assert "stop_services" in call_order, (
        "stop_services() was never called by run_startup(). "
        "BE-6030 Fix B requires stop_services() to be called unconditionally "
        "before starting any new server process."
    )
    assert "start_api_server" in call_order, (
        "start_api_server() was never called by run_startup() during this test. "
        "Check that the stubs allow execution to reach line ~1669."
    )

    stop_idx = call_order.index("stop_services")
    start_idx = call_order.index("start_api_server")

    assert stop_idx < start_idx, (
        f"stop_services() must be called BEFORE start_api_server() "
        f"(single-writer guarantee — BE-6030 Fix B). "
        f"Observed order: {call_order!r}. "
        f"stop_services at position {stop_idx}, start_api_server at position {start_idx}."
    )
