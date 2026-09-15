# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest  # noqa: E402

import startup  # noqa: E402




def _run_start_api_server(monkeypatch, *, giljo_mode, verbose, api_port=None):
    if giljo_mode is None:
        monkeypatch.delenv("GILJO_MODE", raising=False)
    else:
        monkeypatch.setenv("GILJO_MODE", giljo_mode)

    proc = MagicMock()
    proc.pid = 99999
    viewer_spy = MagicMock()

    with (
        patch.object(startup, "_launch_log_viewer", viewer_spy),
        patch("startup.subprocess.Popen", return_value=proc) as popen_spy,
        patch("startup.os.open", return_value=5),
        patch("startup.os.close"),
        patch("startup.platform.system", return_value="Linux"),
        patch("startup.Path.exists", return_value=True),
        patch("startup.Path.mkdir"),
        patch("startup.print_success"),
        patch("startup.print_info"),
        patch("startup.print_warning"),
        patch("startup.print_error"),
    ):
        startup.start_api_server(verbose=verbose, api_port=api_port)

    return viewer_spy, popen_spy


class TestViewerGating:
    def test_no_viewer_when_not_verbose(self, monkeypatch: pytest.MonkeyPatch) -> None:
        viewer_spy, _ = _run_start_api_server(monkeypatch, giljo_mode=None, verbose=False)
        viewer_spy.assert_not_called()

    def test_viewer_opens_when_verbose_ce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        viewer_spy, _ = _run_start_api_server(monkeypatch, giljo_mode="ce", verbose=True)
        viewer_spy.assert_called_once()

    def test_viewer_opens_when_verbose_ce_default_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        viewer_spy, _ = _run_start_api_server(monkeypatch, giljo_mode=None, verbose=True)
        viewer_spy.assert_called_once()

    def test_no_viewer_in_saas_even_when_verbose(self, monkeypatch: pytest.MonkeyPatch) -> None:
        viewer_spy, popen_spy = _run_start_api_server(monkeypatch, giljo_mode="saas", verbose=True)
        viewer_spy.assert_not_called()
        assert popen_spy.call_count == 1


class TestStrictPortArgv:
    def test_strict_port_passed_when_api_port_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, popen_spy = _run_start_api_server(monkeypatch, giljo_mode="ce", verbose=False, api_port=7272)
        argv = list(popen_spy.call_args_list[0].args[0])
        assert "--strict-port" in argv
        assert "--port" in argv
        assert argv[argv.index("--port") + 1] == "7272"

    def test_no_strict_port_when_api_port_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, popen_spy = _run_start_api_server(monkeypatch, giljo_mode="ce", verbose=False, api_port=None)
        argv = list(popen_spy.call_args_list[0].args[0])
        assert "--strict-port" not in argv




class TestSingleInstanceLock:
    def test_lock_yields_normally(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(startup.Path, "cwd", classmethod(lambda cls: tmp_path))
        ran = False
        with startup._single_instance_lock(timeout=1.0):
            ran = True
        assert ran is True

    def test_lock_is_fail_open(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(startup.Path, "cwd", classmethod(lambda cls: tmp_path))

        def _boom(*_a, **_k):
            raise OSError("simulated lock failure")

        ran = False
        with patch("startup.os.open", _boom), patch("startup.print_warning"):
            with startup._single_instance_lock(timeout=1.0):
                ran = True
        assert ran is True




def test_launch_log_viewer_does_not_raise(tmp_path: Path) -> None:
    with (
        patch("startup.subprocess.Popen", return_value=MagicMock()),
        patch("startup.shutil.which", return_value="/usr/bin/gnome-terminal"),
        patch("startup.print_success"),
        patch("startup.print_info"),
        patch("startup.print_warning"),
    ):
        startup._launch_log_viewer(tmp_path / "api_stdout.log", "2026-06-03_10-00-00")




class TestStrictPortAvailable:
    def test_active_listener_is_unavailable(self) -> None:
        from api.run_api import _strict_port_available

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(128)
        port = srv.getsockname()[1]
        try:
            assert _strict_port_available("127.0.0.1", port) is False
            assert _strict_port_available("0.0.0.0", port) is False
        finally:
            srv.close()

    def test_free_port_is_available(self) -> None:
        from api.run_api import _strict_port_available

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        assert _strict_port_available("127.0.0.1", port) is True
