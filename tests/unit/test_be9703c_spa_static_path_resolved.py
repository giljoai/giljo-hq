# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


def _spa_mounted(app) -> bool:
    return any(getattr(route, "name", None) == "static" for route in app.routes)


def test_configured_static_path_is_mounted_from_any_working_directory(tmp_path, monkeypatch):
    import api.app as app_module

    dist = tmp_path / "install" / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>t</title>")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    monkeypatch.setattr("api.wiring.events.read_config", lambda path=None: {"paths": {"static": str(dist)}})
    monkeypatch.setattr(app_module.state, "config", None)

    assert _spa_mounted(app_module.create_app())
