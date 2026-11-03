# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

from importlib import metadata
from pathlib import Path

import pytest

from startup_support import package_record


def _checkout(tmp_path: Path, version: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "giljo-mcp"\nversion = "{version}"\n')
    return tmp_path


@pytest.mark.parametrize(
    ("installed", "expected"),
    [("2.9.1", True), ("2.12.0", False)],
)
def test_record_is_stale_only_when_installed_version_differs(tmp_path, monkeypatch, installed, expected):
    monkeypatch.setattr(package_record.metadata, "version", lambda name: installed)
    assert package_record.package_record_is_stale(_checkout(tmp_path, "2.12.0")) is expected


def test_not_installed_is_not_stale(tmp_path, monkeypatch):
    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(package_record.metadata, "version", missing)
    assert package_record.package_record_is_stale(_checkout(tmp_path, "2.12.0")) is False


def test_unreadable_pyproject_is_not_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(package_record.metadata, "version", lambda name: "2.9.1")
    assert package_record.package_record_is_stale(tmp_path) is False


def test_refresh_never_touches_dependencies(tmp_path, monkeypatch):
    calls = []

    class _Done:
        returncode = 0

    monkeypatch.setattr(package_record.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or _Done())
    assert package_record.refresh_package_record(tmp_path) is True
    assert calls[0][-5:] == ["install", "-e", str(tmp_path), "--no-deps", "--quiet"]
