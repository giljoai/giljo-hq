# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def _make_installer(tmp_path, monkeypatch, migration_result: dict):
    import install

    inst = install.UnifiedInstaller(
        settings={
            "install_dir": str(tmp_path),
            "setup_only": True,
            "unattended": True,
            "headless": True,
        }
    )
    monkeypatch.setattr(inst, "welcome_screen", lambda: None)
    monkeypatch.setattr(inst, "_apply_unattended_settings", lambda: None)
    monkeypatch.setattr(inst, "generate_configs", lambda: {"success": True})
    monkeypatch.setattr(inst, "setup_database", lambda: {"success": True, "credentials": {}})
    monkeypatch.setattr(inst, "run_database_migrations", lambda: migration_result)
    summary_calls: list[bool] = []
    monkeypatch.setattr(inst, "_print_success_summary", lambda: summary_calls.append(True))
    monkeypatch.delenv("GILJO_MODE", raising=False)
    return inst, summary_calls


def test_migration_failure_fails_the_install(tmp_path, monkeypatch):
    inst, summary_calls = _make_installer(
        tmp_path,
        monkeypatch,
        {"success": False, "error": "simulated migration failure", "migrations_applied": []},
    )

    result = inst.run()

    assert result["success"] is False
    assert result["error"] == "simulated migration failure"
    assert "migrations_applied" not in result["steps"]
    assert summary_calls == [], "success summary must not print after a failed migration"


def test_migration_success_still_completes(tmp_path, monkeypatch):
    inst, summary_calls = _make_installer(
        tmp_path,
        monkeypatch,
        {"success": True, "error": None, "migrations_applied": []},
    )

    result = inst.run()

    assert result["success"] is True
    assert "migrations_applied" in result["steps"]
    assert summary_calls == [True]
