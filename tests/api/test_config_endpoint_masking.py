# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.endpoints import configuration
from giljo_mcp.auth.dependencies import get_current_active_user


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(configuration.router, prefix="/api/v1/config")
    app.dependency_overrides[get_current_active_user] = object
    yield TestClient(app)
    app.dependency_overrides.clear()


def _patch_config(monkeypatch, config):
    monkeypatch.setattr("giljo_mcp._config_io.read_config", lambda: config)


def test_database_password_is_masked(client, monkeypatch):
    _patch_config(monkeypatch, {"database": {"host": "db.internal", "password": "supersecret"}})

    response = client.get("/api/v1/config/")

    assert response.status_code == 200
    body = response.json()
    assert body["database"]["password"] == "****"
    assert body["database"]["host"] == "db.internal"


def test_empty_database_password_becomes_empty_string(client, monkeypatch):
    _patch_config(monkeypatch, {"database": {"password": ""}})

    response = client.get("/api/v1/config/")

    assert response.status_code == 200
    assert response.json()["database"]["password"] == ""


def test_api_keys_string_values_masked_non_strings_untouched(client, monkeypatch):
    _patch_config(monkeypatch, {"security": {"api_keys": {"admin": "secretkey", "rotation_count": 5}}})

    response = client.get("/api/v1/config/")

    api_keys = response.json()["security"]["api_keys"]
    assert api_keys["admin"] == "****"
    assert api_keys["rotation_count"] == 5


def test_empty_config_returns_500(client, monkeypatch):
    _patch_config(monkeypatch, {})

    response = client.get("/api/v1/config/")

    assert response.status_code == 500


def test_non_sensitive_sections_pass_through(client, monkeypatch):
    _patch_config(monkeypatch, {"installation": {"mode": "localhost"}, "database": {"password": "x"}})

    body = client.get("/api/v1/config/").json()

    assert body["installation"]["mode"] == "localhost"
