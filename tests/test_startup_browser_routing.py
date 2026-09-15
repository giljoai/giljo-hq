# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import startup
from startup_support import services


class TestChooseBrowserTarget:

    def test_saas_production_returns_none_for_suppression(self) -> None:
        assert startup._choose_browser_target("saas-production", is_first_run=True) is None
        assert startup._choose_browser_target("saas-production", is_first_run=False) is None

    def test_localhost_first_run_opens_welcome(self) -> None:
        assert startup._choose_browser_target("localhost", is_first_run=True) == "/welcome"

    def test_localhost_not_first_run_opens_dashboard_root(self) -> None:
        assert startup._choose_browser_target("localhost", is_first_run=False) == ""

    def test_lan_first_run_opens_welcome(self) -> None:
        assert startup._choose_browser_target("lan", is_first_run=True) == "/welcome"

    def test_lan_not_first_run_opens_dashboard_root(self) -> None:
        assert startup._choose_browser_target("lan", is_first_run=False) == ""


class TestBrowserRoutingIntegration:

    @pytest.mark.parametrize(
        ("deployment_context", "is_first_run", "expected_suffix"),
        [
            ("localhost", True, "/welcome"),
        ],
    )
    def test_url_suffix_matches_branch(
        self,
        deployment_context: str,
        is_first_run: bool,
        expected_suffix: str,
    ) -> None:
        http_proto = "http"
        server_host = "127.0.0.1"
        browser_port = 5173
        target_route = startup._choose_browser_target(deployment_context, is_first_run)
        assert target_route is not None
        setup_url = f"{http_proto}://{server_host}:{browser_port}{target_route}"
        assert setup_url.endswith(expected_suffix)

    def test_dashboard_url_has_no_trailing_path(self) -> None:
        http_proto = "http"
        server_host = "127.0.0.1"
        browser_port = 5173
        target_route = startup._choose_browser_target("localhost", is_first_run=False)
        assert target_route == ""
        dashboard_url = f"{http_proto}://{server_host}:{browser_port}{target_route}"
        assert dashboard_url == f"http://127.0.0.1:{browser_port}"
        assert not dashboard_url.endswith("/welcome")

    def test_saas_production_short_circuits_no_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake_open_browser(url: str, delay: int = 3) -> None:
            _ = delay
            calls.append(url)

        monkeypatch.setattr(startup, "open_browser", fake_open_browser)

        target_route = startup._choose_browser_target("saas-production", is_first_run=True)
        if target_route is not None:
            startup.open_browser(f"http://127.0.0.1:5173{target_route}", delay=0)

        assert calls == [], "open_browser must not be called in saas-production mode"


class TestWslDetection:

    def test_wsl_distro_name_env_var_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        assert services._is_wsl() is True

    def test_proc_version_microsoft_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.setattr(
            Path,
            "read_text",
            lambda self, encoding=None, errors=None: "Linux version 5.15.0-microsoft-standard-WSL2",
        )
        assert services._is_wsl() is True

    def test_native_linux_not_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.setattr(
            Path,
            "read_text",
            lambda self, encoding=None, errors=None: "Linux version 6.8.0-generic",
        )
        assert services._is_wsl() is False

    def test_missing_proc_version_not_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)

        def raise_oserror(self, encoding=None, errors=None):
            raise OSError("no such file")

        monkeypatch.setattr(Path, "read_text", raise_oserror)
        assert services._is_wsl() is False


class TestOpenBrowserWsl:

    def test_prefers_wslview_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        monkeypatch.setattr(services.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "wslview" else None)

        def fake_run(cmd, capture_output, timeout, check):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0)

        monkeypatch.setattr(services.subprocess, "run", fake_run)

        assert services._open_browser_wsl("http://localhost:7272") is True
        assert calls == [["wslview", "http://localhost:7272"]]

    def test_falls_back_to_explorer_when_wslview_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        monkeypatch.setattr(
            services.shutil, "which", lambda name: "/mnt/c/explorer.exe" if name == "explorer.exe" else None
        )

        def fake_run(cmd, capture_output, timeout, check):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0)

        monkeypatch.setattr(services.subprocess, "run", fake_run)

        assert services._open_browser_wsl("http://localhost:7272") is True
        assert calls == [["explorer.exe", "http://localhost:7272"]]

    def test_falls_back_to_powershell_when_others_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        monkeypatch.setattr(
            services.shutil, "which", lambda name: "/mnt/c/powershell.exe" if name == "powershell.exe" else None
        )

        def fake_run(cmd, capture_output, timeout, check):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0)

        monkeypatch.setattr(services.subprocess, "run", fake_run)

        assert services._open_browser_wsl("http://localhost:7272") is True
        assert calls[0][0] == "powershell.exe"

    def test_returns_false_when_no_opener_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(services.shutil, "which", lambda name: None)
        assert services._open_browser_wsl("http://localhost:7272") is False

    def test_returns_false_when_opener_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(services.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "wslview" else None)

        def fake_run(cmd, capture_output, timeout, check):
            return subprocess.CompletedProcess(cmd, returncode=1)

        monkeypatch.setattr(services.subprocess, "run", fake_run)

        assert services._open_browser_wsl("http://localhost:7272") is False

    def test_survives_opener_raising(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(services.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "wslview" else None)

        def fake_run(cmd, capture_output, timeout, check):
            raise OSError("exec failed")

        monkeypatch.setattr(services.subprocess, "run", fake_run)

        assert services._open_browser_wsl("http://localhost:7272") is False


class TestOpenBrowserHonestStatus:

    def test_success_prints_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(services, "_is_wsl", lambda: False)
        monkeypatch.setattr(services.webbrowser, "open", lambda url: True)
        successes: list[str] = []
        warnings: list[str] = []
        monkeypatch.setattr(services, "print_success", successes.append)
        monkeypatch.setattr(services, "print_warning", warnings.append)

        services.open_browser("http://localhost:7272", delay=0)

        assert successes == ["Browser opened"]
        assert warnings == []

    def test_failure_prints_soft_note_not_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(services, "_is_wsl", lambda: False)
        monkeypatch.setattr(services.webbrowser, "open", lambda url: False)
        successes: list[str] = []
        warnings: list[str] = []
        monkeypatch.setattr(services, "print_success", successes.append)
        monkeypatch.setattr(services, "print_warning", warnings.append)

        services.open_browser("http://localhost:7272", delay=0)

        assert successes == [], "must not print false [OK] when the opener failed"
        assert len(warnings) == 1
        assert "localhost:7272" in warnings[0]

    def test_wsl_failure_prints_soft_note(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(services, "_is_wsl", lambda: True)
        monkeypatch.setattr(services, "_open_browser_wsl", lambda url: False)
        successes: list[str] = []
        warnings: list[str] = []
        monkeypatch.setattr(services, "print_success", successes.append)
        monkeypatch.setattr(services, "print_warning", warnings.append)

        services.open_browser("http://localhost:7272", delay=0)

        assert successes == []
        assert len(warnings) == 1
