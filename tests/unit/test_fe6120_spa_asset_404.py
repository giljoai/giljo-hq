# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app import _install_spa_fallback, _should_serve_spa


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>giljo-spa</title>")
    (dist / "assets" / "real.js").write_text("console.log('real')")

    app = FastAPI()
    _install_spa_fallback(app, dist)
    return TestClient(app)


def test_missing_asset_returns_404_not_index_html(client: TestClient):
    resp = client.get("/assets/does-not-exist.js")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}
    assert "text/html" not in resp.headers.get("content-type", "")
    assert "giljo-spa" not in resp.text


def test_real_asset_is_still_served(client: TestClient):
    resp = client.get("/assets/real.js")
    assert resp.status_code == 200
    assert "console.log('real')" in resp.text


def test_unknown_spa_route_falls_through_to_index_html(client: TestClient):
    resp = client.get("/projects/123")
    assert resp.status_code == 200
    assert "giljo-spa" in resp.text


def test_unknown_api_path_returns_json_404(client: TestClient):
    resp = client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}
    assert "giljo-spa" not in resp.text


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/projects/42", True),
        ("/home", True),
        ("/", True),
        ("/assets/app.123.js", False),
        ("/assets/app.123.css", False),
        ("/api/v1/products", False),
        ("/ws/abc", False),
        ("/mcp", False),
        ("/health", False),
        ("/openapi.json", False),
    ],
)
def test_should_serve_spa_decision(path: str, expected: bool):
    assert _should_serve_spa(path) is expected
