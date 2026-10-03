# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


class _StaticConfig:

    def __init__(self, static_dir: str) -> None:
        self._static_dir = static_dir
        self.edition = "community"

    def get_nested(self, key, default=None):
        return self._static_dir if key == "paths.static" else default


def _build(monkeypatch, mode: str, static_dir: str | None):
    import api.app as app_module

    monkeypatch.setattr(app_module, "GILJO_MODE", mode)
    monkeypatch.setattr(app_module.state, "config", _StaticConfig(static_dir) if static_dir else None)
    monkeypatch.setattr("api.wiring.events.read_config", lambda path=None: {"paths": {"static": static_dir}})
    return app_module.create_app()


@pytest.fixture
def spa_dist(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><html><body>SPA</body></html>")
    return str(tmp_path)


@pytest.mark.parametrize("path", DOC_PATHS)
@pytest.mark.parametrize("with_spa", [False, True], ids=["api-only", "single-port-spa"])
def test_saas_hides_docs_and_schema(monkeypatch, spa_dist, tmp_path, path, with_spa):
    static_dir = spa_dist if with_spa else str(tmp_path / "no-dist")
    app = _build(monkeypatch, "saas", static_dir)
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None

    response = TestClient(app).get(path)

    assert response.status_code == 404, f"{path} leaked on SaaS: {response.status_code}"
    assert "text/html" not in response.headers.get("content-type", "")
    assert "<html" not in response.text.lower()


@pytest.mark.parametrize("path", DOC_PATHS)
@pytest.mark.parametrize("mode", ["ce", ""], ids=["ce", "unset"])
def test_ce_keeps_docs_and_schema(monkeypatch, spa_dist, path, mode):
    app = _build(monkeypatch, mode, spa_dist)

    response = TestClient(app).get(path)

    assert response.status_code == 200, f"{path} missing on CE: {response.status_code}"
    if path == "/openapi.json":
        assert "openapi" in response.json()


def test_saas_root_does_not_advertise_docs(monkeypatch, tmp_path):
    app = _build(monkeypatch, "saas", str(tmp_path / "no-dist"))

    endpoints = TestClient(app).get("/").json()["endpoints"]

    assert "api" not in endpoints
    assert endpoints["health"] == "/health"


def test_ce_root_advertises_docs(monkeypatch, tmp_path):
    app = _build(monkeypatch, "ce", str(tmp_path / "no-dist"))

    endpoints = TestClient(app).get("/").json()["endpoints"]

    assert endpoints["api"] == "/docs"
