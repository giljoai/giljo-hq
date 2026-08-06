# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# [CE] Community Edition.

"""
Python-based validation tests for install.sh.

These tests verify structural properties of the Bash installer
without requiring execution on Linux/macOS. They run as part of
the standard pytest suite.
"""

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"

_GIT_BASH_WIN = Path("C:/Program Files/Git/bin/bash.exe")
_BASH_UNAVAILABLE = sys.platform == "win32" and not _GIT_BASH_WIN.exists()


class TestInstallShExists:
    """Verify the installer script file exists and is non-empty."""

    def test_script_file_exists(self):
        assert INSTALL_SH.exists(), f"Expected {INSTALL_SH} to exist"

    def test_script_is_not_empty(self):
        content = INSTALL_SH.read_text(encoding="utf-8")
        assert len(content) > 100, "install.sh appears to be empty or truncated"


class TestInstallShHeader:
    """Verify shebang, safety flags, and license header."""

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = INSTALL_SH.read_text(encoding="utf-8")
        self.lines = self.content.splitlines()

    def test_shebang(self):
        assert self.lines[0] == "#!/usr/bin/env bash"

    def test_set_euo_pipefail(self):
        assert "set -euo pipefail" in self.content

    def test_license_header(self):
        assert "Elastic License 2.0" in self.content


class TestInstallShParameters:
    """Verify CLI parameter handling."""

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = INSTALL_SH.read_text(encoding="utf-8")

    def test_install_dir_flag(self):
        assert "--install-dir" in self.content

    def test_skip_prereqs_flag(self):
        assert "--skip-prereqs" in self.content

    def test_update_flag(self):
        assert "--update" in self.content

    def test_yes_flag(self):
        assert "--yes" in self.content

    def test_auto_yes_variable(self):
        assert "AUTO_YES" in self.content


class TestInstallShOsDetection:
    """Verify OS detection handles both Linux and macOS."""

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = INSTALL_SH.read_text(encoding="utf-8")

    def test_uname_detection(self):
        assert "uname -s" in self.content

    def test_linux_detection(self):
        assert "Linux" in self.content

    def test_darwin_detection(self):
        assert "Darwin" in self.content

    def test_apt_detection(self):
        assert "apt-get" in self.content or "apt" in self.content

    def test_dnf_detection(self):
        assert "dnf" in self.content

    def test_brew_detection(self):
        assert "brew" in self.content

    def test_os_release_parsing(self):
        assert "/etc/os-release" in self.content


class TestInstallShPhases:
    """Verify all 6 installation phases are present."""

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = INSTALL_SH.read_text(encoding="utf-8")

    def test_phase_1_prerequisites(self):
        assert "check_prerequisites" in self.content

    def test_phase_2_download(self):
        assert "download_release" in self.content

    def test_phase_3_environment(self):
        assert "setup_environment" in self.content

    def test_phase_4_install_py(self):
        assert "run_install_py" in self.content

    def test_install_py_uses_setup_only_flag(self):
        assert "--setup-only" in self.content

    def test_phase_5_service(self):
        assert "save_service_files" in self.content

    def test_phase_6_first_run(self):
        assert "first_run" in self.content

    def test_main_function(self):
        assert "main()" in self.content or 'main "$@"' in self.content


class TestInstallShSecurity:
    """Verify SHA256 verification and download integrity checks."""

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = INSTALL_SH.read_text(encoding="utf-8")

    def test_sha256sum_linux(self):
        assert "sha256sum" in self.content

    def test_shasum_macos(self):
        assert "shasum -a 256" in self.content

    def test_sha_mismatch_abort(self):
        assert "SHA256 mismatch" in self.content

    def test_github_repo_reference(self):
        assert "giljoai/giljo-hq" in self.content

    def test_version_manifest_check(self):
        assert "version-manifest.json" in self.content


class TestInstallShServiceTemplates:
    """Verify systemd and launchd templates are correctly structured."""

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = INSTALL_SH.read_text(encoding="utf-8")

    def test_systemd_unit_section(self):
        assert "[Unit]" in self.content

    def test_systemd_service_section(self):
        assert "[Service]" in self.content

    def test_systemd_install_section(self):
        assert "[Install]" in self.content

    def test_systemd_description(self):
        assert "Description=Giljo HQ Server" in self.content

    def test_systemd_after_postgresql(self):
        assert "postgresql.service" in self.content

    def test_systemd_restart_policy(self):
        assert "Restart=on-failure" in self.content

    def test_systemd_exec_start(self):
        assert "ExecStart=" in self.content
        assert "startup.py" in self.content

    def test_launchd_plist_label(self):
        assert "com.giljoai.mcp" in self.content

    def test_launchd_run_at_load(self):
        assert "<key>RunAtLoad</key>" in self.content

    def test_launchd_keep_alive(self):
        assert "<key>KeepAlive</key>" in self.content

    def test_launchd_working_directory(self):
        assert "<key>WorkingDirectory</key>" in self.content


class TestInstallShEditionIsolation:
    """Verify no SaaS references leak into the CE installer."""

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = INSTALL_SH.read_text(encoding="utf-8")

    def test_no_saas_mode_reference(self):
        assert "GILJO_MODE=saas" not in self.content

    def test_no_saas_directory_reference(self):
        lowered = self.content.lower()
        assert "saas/" not in lowered

    def test_no_ai_signatures(self):
        lowered = self.content.lower()
        assert "co-authored-by" not in lowered
        assert "generated by" not in lowered


class TestInstallShUpdateMode:
    """Verify idempotent update functionality."""

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = INSTALL_SH.read_text(encoding="utf-8")

    def test_version_file_check(self):
        assert "VERSION" in self.content

    def test_config_backup(self):
        assert "config-backup" in self.content
        assert ".env" in self.content
        assert "config.yaml" in self.content

    def test_service_stop_before_update(self):
        assert "stop_existing_service" in self.content

    def test_service_restart_after_update(self):
        assert "restart_service" in self.content

    def test_alembic_migration_on_update(self):
        assert "alembic upgrade head" in self.content


class TestInstallShSyntax:
    """Validate Bash syntax if bash is available."""

    @pytest.mark.skipif(_BASH_UNAVAILABLE, reason="bash not found on Windows (Git Bash absent)")
    def test_bash_syntax_check(self):
        """Use bash -n to check for syntax errors."""
        bash_cmd = str(_GIT_BASH_WIN) if sys.platform == "win32" else "bash"

        result = subprocess.run(
            [bash_cmd, "-n", str(INSTALL_SH)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, f"Bash syntax errors in install.sh:\n{result.stderr}"
