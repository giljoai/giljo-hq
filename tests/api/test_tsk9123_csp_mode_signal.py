# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from api.middleware.security import is_development_mode


def _make_dist(tmp_path, monkeypatch):
    dist_dir = tmp_path / "frontend" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html></html>")
    monkeypatch.chdir(tmp_path)


def test_environment_development_with_dist_built_is_production(tmp_path, monkeypatch):
    _make_dist(tmp_path, monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("GILJO_ENV", raising=False)

    assert is_development_mode() is False


def test_environment_development_without_dist_is_development(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("GILJO_ENV", raising=False)

    assert is_development_mode() is True


def test_giljo_env_explicit_override_wins_even_with_dist_built(tmp_path, monkeypatch):
    _make_dist(tmp_path, monkeypatch)
    monkeypatch.setenv("GILJO_ENV", "development")

    assert is_development_mode() is True


def test_no_env_vars_defaults_to_production(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GILJO_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    assert is_development_mode() is False


def test_environment_production_explicit_wins_even_without_dist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("GILJO_ENV", raising=False)

    assert is_development_mode() is False
