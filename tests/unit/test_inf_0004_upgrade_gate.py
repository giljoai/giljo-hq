# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import startup  # noqa: E402


def _make_frontend(tmp_path: Path, *, with_index: bool, index_newer: bool) -> Path:
    frontend = tmp_path / "frontend"
    (frontend / "dist").mkdir(parents=True)
    package_json = frontend / "package.json"
    package_json.write_text('{"name": "frontend"}')
    if with_index:
        index_html = frontend / "dist" / "index.html"
        index_html.write_text("<html></html>")
        if index_newer:
            package_json.touch()
            _set_mtime(package_json, 1000)
            _set_mtime(index_html, 2000)
        else:
            _set_mtime(index_html, 1000)
            _set_mtime(package_json, 2000)
    return frontend


def _set_mtime(path: Path, when: float) -> None:
    import os

    os.utime(path, (when, when))




class TestFrontendConsistency:
    def test_missing_index_html_is_a_problem(self, tmp_path):
        frontend = _make_frontend(tmp_path, with_index=False, index_newer=False)
        problem = startup._frontend_consistency_problem(frontend)
        assert problem is not None
        assert "frontend/dist/index.html" in problem

    def test_stale_index_html_is_a_problem(self, tmp_path):
        frontend = _make_frontend(tmp_path, with_index=True, index_newer=False)
        problem = startup._frontend_consistency_problem(frontend)
        assert problem is not None
        assert "out of date" in problem

    def test_fresh_index_html_is_ok(self, tmp_path):
        frontend = _make_frontend(tmp_path, with_index=True, index_newer=True)
        assert startup._frontend_consistency_problem(frontend) is None

    def test_no_package_json_is_skipped(self, tmp_path):
        empty = tmp_path / "frontend"
        empty.mkdir()
        assert startup._frontend_consistency_problem(empty) is None




class TestCriticalImports:
    def test_all_present_in_test_env(self):
        assert startup._missing_critical_imports() == []

    def test_detects_a_missing_module(self, monkeypatch):
        monkeypatch.setattr(
            startup,
            "_CRITICAL_IMPORT_MODULES",
            ("fastapi", "giljo_definitely_not_a_real_module_xyz"),
        )
        missing = startup._missing_critical_imports()
        assert missing == ["giljo_definitely_not_a_real_module_xyz"]




class TestAlembicDriftFailOpen:
    def test_no_database_url_returns_none(self, monkeypatch):
        monkeypatch.setattr(startup, "_get_database_url", lambda: None)
        assert startup._alembic_revision_drift() is None

    def test_internal_error_returns_none(self, monkeypatch):
        def boom():
            raise RuntimeError("alembic exploded")

        monkeypatch.setattr(startup, "_get_database_url", boom)
        assert startup._alembic_revision_drift() is None




class TestVerifyInstallConsistency:
    def test_clean_install_reports_no_problems(self, tmp_path, monkeypatch):
        frontend = _make_frontend(tmp_path, with_index=True, index_newer=True)
        monkeypatch.setattr(startup, "_alembic_revision_drift", lambda: None)
        problems = startup.verify_install_consistency(frontend_dir=frontend, dev_mode=False, enforce_frontend=True)
        assert problems == []

    def test_broken_frontend_surfaces_in_aggregate(self, tmp_path, monkeypatch):
        frontend = _make_frontend(tmp_path, with_index=False, index_newer=False)
        monkeypatch.setattr(startup, "_alembic_revision_drift", lambda: None)
        problems = startup.verify_install_consistency(
            frontend_dir=frontend, dev_mode=False, enforce_frontend=True, check_alembic=False
        )
        assert any("index.html" in p for p in problems)

    def test_alembic_drift_surfaces_with_upgrade_hint(self, tmp_path, monkeypatch):
        frontend = _make_frontend(tmp_path, with_index=True, index_newer=True)
        monkeypatch.setattr(startup, "_alembic_revision_drift", lambda: ("ce_0001", ["ce_0044"]))
        problems = startup.verify_install_consistency(frontend_dir=frontend, dev_mode=False, enforce_frontend=True)
        assert any("alembic upgrade head" in p and "ce_0044" in p for p in problems)

    def test_dev_mode_skips_frontend(self, tmp_path, monkeypatch):
        frontend = _make_frontend(tmp_path, with_index=False, index_newer=False)
        monkeypatch.setattr(startup, "_alembic_revision_drift", lambda: None)
        problems = startup.verify_install_consistency(frontend_dir=frontend, dev_mode=True, enforce_frontend=True)
        assert problems == []

    def test_enforce_frontend_false_skips_frontend(self, tmp_path, monkeypatch):
        frontend = _make_frontend(tmp_path, with_index=False, index_newer=False)
        monkeypatch.setattr(startup, "_alembic_revision_drift", lambda: None)
        problems = startup.verify_install_consistency(frontend_dir=frontend, dev_mode=False, enforce_frontend=False)
        assert problems == []

    def test_saas_mode_skips_alembic(self, tmp_path, monkeypatch):
        frontend = _make_frontend(tmp_path, with_index=True, index_newer=True)
        monkeypatch.setenv("GILJO_MODE", "saas")

        def fail_if_called():
            raise AssertionError("alembic drift check must be skipped in SaaS mode")

        monkeypatch.setattr(startup, "_alembic_revision_drift", fail_if_called)
        problems = startup.verify_install_consistency(frontend_dir=frontend, dev_mode=False, enforce_frontend=True)
        assert problems == []
