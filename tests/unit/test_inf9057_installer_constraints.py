# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

EXPORT_EXCLUDE = REPO_ROOT / ".export-exclude"
INSTALL_PY = REPO_ROOT / "install.py"
UPDATE_PY = REPO_ROOT / "update.py"
STARTUP_PY = REPO_ROOT / "startup.py"
INSTALL_PS1 = REPO_ROOT / "scripts" / "install.ps1"
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"
LOCK = REPO_ROOT / "requirements.lock"


def test_requirements_lock_ships_with_ce_export():
    assert LOCK.exists(), "requirements.lock missing from the repo root"
    if not EXPORT_EXCLUDE.exists():
        pytest.skip(".export-exclude not present (CE export artifact / public repo)")
    active_patterns = [
        line.strip()
        for line in EXPORT_EXCLUDE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "requirements.lock" not in active_patterns, (
        ".export-exclude strips requirements.lock from the CE artifact — the "
        "installer constraints layer (INF-9057) needs it shipped."
    )


class TestInstallPyConstraints:
    @pytest.fixture(autouse=True)
    def _load(self):
        candidates = [INSTALL_PY, REPO_ROOT / "installer" / "core" / "python_env.py"]
        self.content = "".join(p.read_text(encoding="utf-8") for p in candidates if p.exists())

    def test_declares_constraints_file(self):
        assert 'self.constraints_file = self.install_dir / "requirements.lock"' in self.content

    def test_requirements_install_applies_constraints(self):
        assert "*constraints_args," in self.content, (
            "install.py's main `pip install -r requirements.txt` no longer "
            "splices in the -c requirements.lock constraint args"
        )
        assert '["-c", str(self.constraints_file)]' in self.content

    def test_editable_install_applies_constraints(self):
        assert '"-e", ".", "--quiet", *constraints_args' in self.content

    def test_missing_lock_is_tolerated_not_fatal(self):
        assert "requirements.lock not found" in self.content


def test_update_py_applies_constraints():
    content = UPDATE_PY.read_text(encoding="utf-8")
    assert 'ROOT / "requirements.lock"' in content
    assert 'cmd += ["-c", str(lock_file)]' in content


def test_startup_py_self_heal_applies_constraints():
    candidates = [STARTUP_PY, REPO_ROOT / "startup_support" / "checks.py"]
    content = "".join(p.read_text(encoding="utf-8") for p in candidates if p.exists())
    assert 'Path.cwd() / "requirements.lock"' in content
    assert 'cmd += ["-c", str(constraints_path)]' in content


def test_install_ps1_applies_constraints():
    content = INSTALL_PS1.read_text(encoding="utf-8")
    assert '$constraintsPath = Join-Path $TargetDir "requirements.lock"' in content
    assert '@("-c", $constraintsPath)' in content
    assert content.count("@constraintsArgs") >= 2, (
        "install.ps1 must splice @constraintsArgs into BOTH the -r requirements install and the editable install"
    )


def test_install_sh_applies_constraints():
    content = INSTALL_SH.read_text(encoding="utf-8")
    assert 'constraints="${target_dir}/requirements.lock"' in content
    assert 'constraint_args=(-c "$constraints")' in content
    assert content.count('${constraint_args[@]+"${constraint_args[@]}"}') >= 2, (
        "install.sh must splice the constraint args (set -u-safe expansion) into "
        "BOTH the -r requirements install and the editable install"
    )


@pytest.mark.skipif(not SECURITY_WORKFLOW.exists(), reason="private CI workflow not present in this artifact")
def test_pip_audit_scans_the_lock_not_the_floors():
    content = SECURITY_WORKFLOW.read_text(encoding="utf-8")
    assert "-r requirements.lock" in content
    assert "-r requirements.txt" not in content
