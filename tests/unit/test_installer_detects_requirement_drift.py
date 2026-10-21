# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from pathlib import Path

import pytest

from startup_support import checks, requirements_drift


REPO_ROOT = Path(__file__).resolve().parents[2]


def _installed(versions: dict[str, str]):
    def fake_version(name: str) -> str:
        key = name.lower().replace("_", "-")
        if key not in versions:
            raise importlib.metadata.PackageNotFoundError(name)
        return versions[key]

    return fake_version


def test_helper_reports_only_the_unsatisfied_line(tmp_path, monkeypatch):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# comment line\n"
        "\n"
        "sqlalchemy>=99.0      # inline comment\n"
        "alembic>=1.0\n"
        'pywin32>=300 ; python_version < "3.0"\n'
        "mcp>=2.3.0,<2.4\n"
        "uvicorn[standard]>=0.54.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        _installed({"sqlalchemy": "2.0.43", "alembic": "1.20.1", "uvicorn": "0.54.0"}),
    )

    lines = requirements_drift.unsatisfied_requirements(req)

    assert lines == [
        "sqlalchemy: installed 2.0.43, required >=99.0",
        "mcp: not installed, required <2.4,>=2.3.0",
    ]


def test_helper_flags_version_above_upper_bound(tmp_path, monkeypatch):
    req = tmp_path / "requirements.txt"
    req.write_text("mcp>=2.3.0,<2.4\n", encoding="utf-8")
    monkeypatch.setattr(importlib.metadata, "version", _installed({"mcp": "2.4.1"}))

    assert requirements_drift.unsatisfied_requirements(req) == ["mcp: installed 2.4.1, required <2.4,>=2.3.0"]


def test_helper_accepts_the_real_requirements_file_without_misparsing(monkeypatch):
    req = REPO_ROOT / "requirements.txt"
    seen: list[str] = []

    def fake_version(name: str) -> str:
        seen.append(name.lower())
        return "9999"

    monkeypatch.setattr(importlib.metadata, "version", fake_version)

    lines = requirements_drift.unsatisfied_requirements(req)

    assert all(line.split(":")[0] in {"fastapi", "starlette", "sqlalchemy", "mcp"} for line in lines), lines
    assert {"fastapi", "sqlalchemy", "mcp", "uvicorn", "sentry-sdk", "pyjwt", "python-multipart"} <= set(seen)


def test_helper_reports_missing_packaging_in_one_line(tmp_path, monkeypatch):
    req = tmp_path / "requirements.txt"
    req.write_text("sqlalchemy>=2.1\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "packaging.requirements", None)

    lines = requirements_drift.unsatisfied_requirements(req)

    assert len(lines) == 1
    assert "packaging" in lines[0]


@pytest.fixture
def requirements_cwd(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("sqlalchemy>=2.1.0,<2.2\n", encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("sqlalchemy==2.1.0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _drift_sequence(monkeypatch, results: list[list[str]]) -> list[Path]:
    calls: list[Path] = []

    def fake(path: Path) -> list[str]:
        calls.append(path)
        return results[min(len(calls), len(results)) - 1]

    monkeypatch.setattr(requirements_drift, "unsatisfied_requirements", fake)
    return calls


def test_install_requirements_runs_pip_when_a_version_drifted(requirements_cwd, monkeypatch, capsys):
    drift = "sqlalchemy: installed 2.0.43, required >=2.1.0,<2.2"
    _drift_sequence(monkeypatch, [[drift], []])
    pip_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        pip_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(checks.subprocess, "run", fake_run)

    assert checks.install_requirements() is True

    out = capsys.readouterr().out
    assert "Requirements changed since the last install:" in out
    assert drift in out
    assert len(pip_calls) == 1
    cmd = pip_calls[0]
    assert cmd[1:4] == ["-m", "pip", "install"]
    assert cmd[cmd.index("-r") + 1].endswith("requirements.txt")
    assert cmd[cmd.index("-c") + 1].endswith("requirements.lock")
    assert "--timeout" in cmd


def test_install_requirements_skips_pip_when_nothing_drifted(requirements_cwd, monkeypatch, capsys):
    _drift_sequence(monkeypatch, [[]])

    def boom(*args, **kwargs):
        raise AssertionError("pip must not run when requirements are satisfied")

    monkeypatch.setattr(checks.subprocess, "run", boom)

    assert checks.install_requirements() is True
    assert "Requirements already installed" in capsys.readouterr().out


def test_install_requirements_fails_loud_when_drift_survives_pip(requirements_cwd, monkeypatch, capsys):
    stuck = "sqlalchemy: installed 2.0.43, required >=2.1.0,<2.2"
    _drift_sequence(monkeypatch, [[stuck], [stuck]])
    monkeypatch.setattr(checks.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0))

    assert checks.install_requirements() is False

    out = capsys.readouterr().out
    assert out.count(stuck) == 2
    assert "pip install -r requirements.txt" in out


def test_install_requirements_fails_without_requirements_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert checks.install_requirements() is False
    assert "requirements.txt not found" in capsys.readouterr().out


def test_incident_replay_old_sqlalchemy_installed_triggers_pip_unmocked_helper(requirements_cwd, monkeypatch, capsys):
    monkeypatch.setattr(importlib.metadata, "version", _installed({"sqlalchemy": "2.0.43"}))
    pip_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        pip_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(checks.subprocess, "run", fake_run)

    assert checks.install_requirements() is False

    out = capsys.readouterr().out
    assert len(pip_calls) == 1
    assert "sqlalchemy: installed 2.0.43, required <2.2,>=2.1.0" in out
    assert "still not satisfied" in out
